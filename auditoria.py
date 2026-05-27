import os
import json
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory
from rapidfuzz import fuzz, process
import pandas as pd
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from io import BytesIO

app = Flask(__name__, static_folder=None)

PASTA_SLSKD = "/home/savio/slskd"
DEFAULT_DOWNLOADS = os.path.join(PASTA_SLSKD, "downloads")
DEFAULT_JSON = os.path.join(PASTA_SLSKD, "historico.json")
ultimo_relatorio = []


# ─── Serve os HTMLs ───────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(PASTA_SLSKD, "index.html")


@app.route("/auditoria")
def auditoria():
    return send_from_directory(PASTA_SLSKD, "auditoria.html")


# ─── Funções de auditoria ─────────────────────────────────

def ler_xlsx_desejadas(caminho_xlsx, col_musica="Song", col_artista="Artist"):
    df = pd.read_excel(caminho_xlsx)
    df["busca"] = df[col_musica].str.lower().fillna("") + " " + df[col_artista].str.lower().fillna("")
    df.rename(columns={col_musica: "Song", col_artista: "Artist"}, inplace=True)
    return df


def ler_arquivos_baixados(pasta):
    arquivos = []
    for ext in ["*.mp3", "*.flac", "*.m4a"]:
        arquivos.extend(Path(pasta).rglob(ext))
    dados = []
    for arq in arquivos:
        info = {"arquivo": arq.name, "caminho": str(arq),
                "tamanho_mb": round(arq.stat().st_size / 1024 / 1024, 2)}
        try:
            if arq.suffix.lower() == ".mp3":
                audio = MP3(arq, ID3=EasyID3)
                info["titulo"] = audio.get("title", [""])[0]
                info["artista"] = audio.get("artist", [""])[0]
                info["duracao"] = round(audio.info.length)
            else:
                info["titulo"] = ""; info["artista"] = ""; info["duracao"] = 0
        except Exception:
            info["titulo"] = ""; info["artista"] = ""; info["duracao"] = 0
        info["busca"] = f"{info.get('titulo','')} {info.get('artista','')} {arq.stem}".lower()
        dados.append(info)
    return pd.DataFrame(dados)


def ler_historico_index(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df = df[df["STATUS"].str.lower() == "baixado"]
    df["busca"] = df["MUSICA"].str.lower() + " " + df["ARTISTA"].str.lower()
    return df


def comparar_tudo(xlsx_path, downloads_path, json_path, sim_min, col_musica, col_artista):
    df_wanted = ler_xlsx_desejadas(xlsx_path, col_musica, col_artista)
    df_files = ler_arquivos_baixados(downloads_path)
    df_hist = ler_historico_index(json_path) if os.path.exists(json_path) else pd.DataFrame(columns=["busca"])

    relatorio = []
    for _, wanted in df_wanted.iterrows():
        match_hist = process.extractOne(wanted["busca"], df_hist["busca"], scorer=fuzz.token_sort_ratio) if len(df_hist) > 0 else None
        baixado_slskd = match_hist is not None and match_hist[1] >= sim_min
        match_file = process.extractOne(wanted["busca"], df_files["busca"], scorer=fuzz.token_sort_ratio) if len(df_files) > 0 else None
        arquivo_real = match_file is not None and match_file[1] >= sim_min

        if baixado_slskd and not arquivo_real:
            status, obs = "FALSO POSITIVO", "SLSKD disse que baixou mas arquivo não encontrado"
        elif baixado_slskd and arquivo_real:
            status = "OK"
            arq_info = df_files.iloc[match_file[2]]
            obs = f"Arquivo: {arq_info['arquivo']} | {arq_info['tamanho_mb']}MB"
        elif not baixado_slskd and arquivo_real:
            status, obs = "BAIXADO SEM REGISTRO", "Arquivo existe mas sem histórico no SLSKD"
        else:
            status, obs = "FALTANDO", "Não baixou"

        relatorio.append({
            "SONG": wanted['Song'],
            "ARTIST": wanted['Artist'],
            "STATUS_SLSKD": "baixado" if baixado_slskd else "não encontrado",
            "ARQUIVO_REAL": df_files.iloc[match_file[2]]["arquivo"] if arquivo_real else "-",
            "MATCH_%": round(match_file[1], 1) if (match_file and arquivo_real) else 0,
            "TAMANHO_MB": df_files.iloc[match_file[2]]["tamanho_mb"] if arquivo_real else 0,
            "DIAGNOSTICO": status,
            "OBS": obs,
        })
    return relatorio


# ─── API ──────────────────────────────────────────────────

@app.route("/audit", methods=["POST"])
def audit():
    global ultimo_relatorio
    body = request.get_json(force=True)
    xlsx_path = body.get("xlsx_path", "").strip()
    if not xlsx_path:
        return jsonify({"ok": False, "erro": "Caminho do XLSX não informado"})
    if not os.path.exists(xlsx_path):
        return jsonify({"ok": False, "erro": f"Arquivo não encontrado: {xlsx_path}"})
    try:
        relatorio = comparar_tudo(
            xlsx_path,
            body.get("downloads_path", "").strip() or DEFAULT_DOWNLOADS,
            body.get("json_path", "").strip() or DEFAULT_JSON,
            int(body.get("similaridade_min", 85)),
            body.get("col_musica", "Song").strip(),
            body.get("col_artista", "Artist").strip(),
        )
        ultimo_relatorio = relatorio
        return jsonify({"ok": True, "relatorio": relatorio})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})


@app.route("/export", methods=["POST"])
def export_xlsx():
    if not ultimo_relatorio:
        return jsonify({"ok": False, "erro": "Nenhum relatório"}), 400
    buf = BytesIO()
    pd.DataFrame(ultimo_relatorio).to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    return send_file(buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name="auditoria_slskd.xlsx")


if __name__ == "__main__":
    print("\n  ╔══════════════════════════════════════════════════╗")
    print("  ║  SLSKD Downloader + Auditoria                   ║")
    print("  ║                                                 ║")
    print("  ║  Downloader: http://localhost:5000              ║")
    print("  ║  Auditoria:  http://localhost:5000/auditoria    ║")
    print("  ╚══════════════════════════════════════════════════╝\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
