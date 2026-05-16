#!/usr/bin/env python3
"""
GUI Server — Interface Web para o Downloader slskd
===================================================
Servidor Flask que expõe uma API para a interface web controlar
o baixar_musicas.py em tempo real.

Instalar:
    pip install flask flask-cors

Uso:
    python3 gui_server.py
    Acesse: http://localhost:8080
"""

import json
import os
import sys
import threading
import time
import re
import argparse
import logging
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from io import BytesIO

try:
    from flask import Flask, jsonify, request, send_from_directory, Response
    from flask_cors import CORS
except ImportError:
    print("❌ Flask não encontrado. Instale com: pip install flask flask-cors")
    sys.exit(1)

import openpyxl
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ── Config padrão ─────────────────────────────────────────
SLSKD_URL      = "http://localhost:5030"
SLSKD_USUARIO  = "slskd"
SLSKD_SENHA    = "slskd"
LOG_DIR        = Path("logs")

RAZAO_MINIMA = {"mp3": 1.8, "flac": 5.0, "wav": 5.0}
FORMATO_PRIORIDADE = {"flac": 3, "wav": 2, "mp3": 1}
# ─────────────────────────────────────────────────────────

app    = Flask(__name__)
CORS(app)

# Estado global da aplicação
state = {
    "running":     False,
    "paused":      False,
    "stop_flag":   False,
    "total":       0,
    "baixados":    0,
    "erros":       0,
    "pendentes":   0,
    "atual":       "",
    "musicas":     [],
    "config": {
        "formatos":              ["flac", "wav", "mp3"],
        "bitrate_minimo":         192,
        "tempo_busca":           20,
        "tamanho_minimo":        7_000_000,
        "organizacao_modo":      "flat",  # flat, pasta_unica, artista, pasta_personalizada
        "pasta_download":        "",
        "pasta_personalizada":   "",
    },
}

log_queue = Queue()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gui")


# ── Helpers ───────────────────────────────────────────────

def push_log(msg: str, nivel: str = "info"):
    log_queue.put({"ts": datetime.now().strftime("%H:%M:%S"), "msg": msg, "nivel": nivel})


def criar_sessao():
    session = requests.Session()
    retry   = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def obter_token(session) -> bool:
    try:
        r = session.post(
            f"{SLSKD_URL}/api/v0/session",
            json={"username": SLSKD_USUARIO, "password": SLSKD_SENHA},
            timeout=10,
        )
        if r.status_code == 200:
            token = r.json().get("token")
            if token:
                session.headers.update({"Authorization": f"Bearer {token}"})
                return True
        push_log(f"Falha autenticação slskd: {r.status_code}", "error")
    except Exception as e:
        push_log(f"Erro conexão slskd: {e}", "error")
    return False


def limpar_termo(texto: str) -> str:
    texto = re.sub(r"\(.*?\)", "", texto)
    texto = re.sub(r"\[.*?\]", "", texto)
    texto = re.sub(r"\b(feat|ft|featuring)\.?\b.*", "", texto, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", texto).strip()


def calcular_razao_mb_min(tamanho: int, duracao: int) -> float:
    if duracao <= 0:
        return 0.0
    return (tamanho / 1_000_000) / (duracao / 60)


def calcular_score(c) -> float:
    score = c["prioridade"] * 10000
    if c["formato"] == "flac":  score += 5000
    elif c["formato"] == "wav": score += 3000
    elif c["formato"] == "mp3":
        br = c["bitrate"]
        if br >= 320:   score += 3200
        elif br >= 256: score += 2560
        elif br > 0:    score += br * 5
        else:           score += 1000
    score += c["tamanho"] / 1_000_000
    return score


def aguardar_resultados(session, search_id, tempo_max) -> list:
    ultimo_total     = 0
    ultimo_crescimento = time.time()
    resultados       = []
    while True:
        try:
            r = session.get(f"{SLSKD_URL}/api/v0/searches/{search_id}/responses", timeout=10)
            if r.status_code == 200:
                resultados = r.json() or []
                total = sum(len(x.get("files", [])) for x in resultados)
                if total > ultimo_total:
                    ultimo_total       = total
                    ultimo_crescimento = time.time()
                if total > 0 and time.time() - ultimo_crescimento > 5:
                    return resultados
                if time.time() - ultimo_crescimento > tempo_max:
                    return resultados
        except Exception:
            pass
        time.sleep(1)


def fazer_busca(session, termo, tempo_max) -> list:
    try:
        r = session.post(f"{SLSKD_URL}/api/v0/searches", json={"searchText": termo}, timeout=10)
        if r.status_code == 409:
            r_list = session.get(f"{SLSKD_URL}/api/v0/searches", timeout=10)
            if r_list.status_code == 200:
                for b in r_list.json():
                    if b.get("searchText", "").lower() == termo.lower():
                        return aguardar_resultados(session, b["id"], tempo_max)
            return []
        if r.status_code not in (200, 201):
            return []
        search_id = r.json().get("id")
        return aguardar_resultados(session, search_id, tempo_max) if search_id else []
    except Exception as e:
        push_log(f"Erro busca: {e}", "error")
        return []


def buscar_musica(session, musica, artista, tempo_max) -> list:
    musica_limpa  = limpar_termo(musica)
    artista_limpo = limpar_termo(artista)
    primeiro      = artista_limpo.split(",")[0].split("&")[0].strip()
    tentativas_raw = [
        f"{artista_limpo} {musica_limpa}",
        f"{primeiro} {musica_limpa}",
        f"{primeiro} {' '.join(musica_limpa.split()[:3])}",
    ]
    vistas, tentativas = set(), []
    for t in tentativas_raw:
        if t.lower() not in vistas:
            vistas.add(t.lower())
            tentativas.append(t)

    for i, termo in enumerate(tentativas, 1):
        push_log(f"🔍 Tentativa {i}: {termo}")
        resultados = fazer_busca(session, termo, tempo_max)
        total = sum(len(r.get("files", [])) for r in resultados)
        if total > 0:
            push_log(f"📦 {total} arquivo(s) encontrado(s)")
            return resultados
    return []


def filtrar_candidatos(resultados, formatos, bitrate_min, tamanho_min, prioridade) -> list:
    candidatos = []
    for resp in resultados:
        usuario = resp.get("username", "")
        for arq in resp.get("files", []):
            nome    = arq.get("filename", "")
            ext     = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
            try:    bitrate = int(float(arq.get("bitRate") or arq.get("bitrate") or 0))
            except: bitrate = 0
            tamanho = arq.get("size", 0) or 0
            duracao = arq.get("length") or arq.get("duration") or 0

            if ext not in formatos: continue
            if tamanho < tamanho_min: continue
            if ext == "mp3" and bitrate > 0 and bitrate < bitrate_min: continue

            razao = calcular_razao_mb_min(tamanho, duracao)
            razao_min = RAZAO_MINIMA.get(ext, 0)
            if razao > 0 and razao_min > 0 and razao < razao_min: continue

            c = {
                "usuario":    usuario,
                "arquivo":    nome,
                "formato":    ext,
                "bitrate":    bitrate,
                "tamanho":    tamanho,
                "duracao":    duracao,
                "razao":      razao,
                "prioridade": prioridade.get(ext, 0),
            }
            c["score"] = calcular_score(c)
            candidatos.append(c)

    candidatos.sort(key=lambda x: x["score"], reverse=True)
    return candidatos


def sanitizar(nome: str) -> str:
    """Remove caracteres especiais para nome de pasta/arquivo"""
    if not nome:
        return "Desconhecido"
    # Remove caracteres inválidos
    for c in r'\/:*?"<>|':
        nome = nome.replace(c, "_")
    # Remove espaços extras no início e fim
    nome = nome.strip()
    # Limita tamanho
    if len(nome) > 100:
        nome = nome[:100]
    return nome or "Desconhecido"


def montar_caminho_arquivo(artista, musica, nome_arq, organizacao_modo, pasta_personalizada="", pasta_base=""):
    """
    Monta o caminho completo do arquivo baseado no modo de organização.

    Modos disponíveis:
        - "flat": Tudo diretamente na pasta base (ou raiz downloads)
        - "pasta_unica": "Artista - Musica/arquivo.mp3"
        - "artista": "Artista/Musica/arquivo.mp3"
        - "pasta_personalizada": "nome_escolhido/arquivo.mp3"
    """
    nome_limpo = sanitizar(nome_arq)
    artista_limpo = sanitizar(artista)
    musica_limpo = sanitizar(musica)

    # Define o caminho base
    if pasta_base:
        base_path = pasta_base.strip('/')
    else:
        base_path = ""

    if organizacao_modo == "flat":
        # Modo flat: todos os arquivos diretamente na pasta base (sem subpastas)
        if base_path:
            caminho_final = f"{base_path}/{nome_limpo}"
        else:
            caminho_final = nome_limpo

    elif organizacao_modo == "pasta_unica":
        # Uma pasta por música: "Artista - Musica/arquivo.mp3"
        nome_pasta = f"{artista_limpo} - {musica_limpo}"
        if base_path:
            caminho_final = f"{base_path}/{nome_pasta}/{nome_limpo}"
        else:
            caminho_final = f"{nome_pasta}/{nome_limpo}"

    elif organizacao_modo == "artista":
        # Artista/Música: "Artista/Musica/arquivo.mp3"
        if base_path:
            caminho_final = f"{base_path}/{artista_limpo}/{musica_limpo}/{nome_limpo}"
        else:
            caminho_final = f"{artista_limpo}/{musica_limpo}/{nome_limpo}"

    elif organizacao_modo == "pasta_personalizada":
        # Nome de pasta personalizado: "pasta_escolhida/arquivo.mp3"
        nome_pasta = sanitizar(pasta_personalizada) if pasta_personalizada else "Downloads"
        if base_path:
            caminho_final = f"{base_path}/{nome_pasta}/{nome_limpo}"
        else:
            caminho_final = f"{nome_pasta}/{nome_limpo}"
    else:
        # Fallback para flat
        if base_path:
            caminho_final = f"{base_path}/{nome_limpo}"
        else:
            caminho_final = nome_limpo

    return caminho_final.lstrip("/")


def baixar_arquivo(session, usuario, arquivo, tamanho, artista, musica, organizacao_modo, pasta_base="", pasta_personalizada="") -> bool:
    """
    Envia o download para o slskd com o caminho de destino correto.

    organizacao_modo:
        - "flat": Tudo na mesma pasta (sem subpastas)
        - "pasta_unica": Uma pasta por música "Artista - Musica/"
        - "artista": Pasta do artista, depois pasta da música "Artista/Musica/"
        - "pasta_personalizada": Nome de pasta personalizado
    """
    try:
        nome_arq = arquivo.replace("\\", "/").split("/")[-1]

        caminho_final = montar_caminho_arquivo(
            artista, musica, nome_arq,
            organizacao_modo, pasta_personalizada, pasta_base
        )

        # Estrutura correta para a API do slskd
        payload = {
            "filename": arquivo,
            "size": tamanho,
            "localFilename": caminho_final
        }

        push_log(f"💾 Salvando em: {caminho_final}", "info")

        r = session.post(
            f"{SLSKD_URL}/api/v0/transfers/downloads/{usuario}",
            json=[payload],
            timeout=15,
        )

        if r.status_code in (200, 201, 204):
            push_log(f"✅ Download enfileirado: {nome_arq}", "info")
            return True
        else:
            push_log(f"❌ Erro slskd: {r.status_code} - {r.text[:200]}", "error")
            return False

    except Exception as e:
        push_log(f"❌ Falha download: {e}", "error")
        return False

def atualizar_musica(idx: int, **kwargs):
    for k, v in kwargs.items():
        state["musicas"][idx][k] = v


def run_downloads():
    """Thread principal de downloads."""
    cfg        = state["config"]
    formatos   = cfg["formatos"]
    bitrate_min= cfg["bitrate_minimo"]
    tempo_busca= cfg["tempo_busca"]
    tamanho_min= cfg["tamanho_minimo"]
    organizacao_modo = cfg.get("organizacao_modo", "flat")
    pasta_base = cfg.get("pasta_download", "")
    pasta_personalizada = cfg.get("pasta_personalizada", "")
    prioridade = {f: len(formatos) - i for i, f in enumerate(formatos)}

    session = criar_sessao()
    if not obter_token(session):
        state["running"] = False
        push_log("❌ Falha ao autenticar no slskd", "error")
        return

    push_log("✅ Conectado ao slskd")
    push_log(f"📁 Modo de organização: {organizacao_modo}", "info")
    if organizacao_modo == "pasta_personalizada" and pasta_personalizada:
        push_log(f"📁 Pasta personalizada: {pasta_personalizada}", "info")

    pendentes = [i for i, m in enumerate(state["musicas"]) if m["status"] == "pendente"]
    state["pendentes"] = len(pendentes)

    for idx in pendentes:
        if state["stop_flag"]:
            push_log("⏹ Download interrompido pelo usuário", "warn")
            break

        while state["paused"] and not state["stop_flag"]:
            time.sleep(0.5)

        m      = state["musicas"][idx]
        musica = m["musica"]
        artista= m["artista"]
        label  = f"{artista} — {musica}"

        state["atual"] = label
        atualizar_musica(idx, status="buscando")
        push_log(f"\n[{idx+1}/{state['total']}] {label}")

        resultados = buscar_musica(session, musica, artista, tempo_busca)
        candidatos = filtrar_candidatos(resultados, formatos, bitrate_min, tamanho_min, prioridade)

        if not candidatos:
            atualizar_musica(idx, status="não encontrado")
            state["erros"]    += 1
            state["pendentes"] = max(0, state["pendentes"] - 1)
            push_log(f"⚠️ Nenhum candidato válido para: {label}", "warn")
            continue

        melhor   = candidatos[0]
        duracao  = melhor.get("duracao", 0)
        razao    = melhor.get("razao", 0)
        dur_str  = f"{int(duracao)//60}:{int(duracao)%60:02d}" if duracao else "?:??"
        razao_str= f"{razao:.2f} MB/min" if razao else "N/A"

        push_log(
            f"✅ {melhor['formato'].upper()} | "
            f"{melhor['bitrate']}kbps | "
            f"{melhor['tamanho']/1e6:.1f}MB | "
            f"{dur_str} | {razao_str}"
        )

        atualizar_musica(idx,
            status   = "baixando",
            formato  = melhor["formato"].upper(),
            bitrate  = melhor["bitrate"],
            tamanho  = round(melhor["tamanho"] / 1e6, 1),
            usuario  = melhor["usuario"],
            score    = round(melhor["score"], 1),
        )

        ok = baixar_arquivo(session, melhor["usuario"], melhor["arquivo"],
                            melhor["tamanho"], artista, musica,
                            organizacao_modo, pasta_base, pasta_personalizada)

        if ok:
            atualizar_musica(idx, status="baixado")
            state["baixados"]  += 1
            state["pendentes"]  = max(0, state["pendentes"] - 1)
            push_log(f"⬇️ Download iniciado: {melhor['arquivo'].split(chr(92))[-1]}")
        else:
            atualizar_musica(idx, status="erro")
            state["erros"]     += 1
            state["pendentes"]  = max(0, state["pendentes"] - 1)
            push_log(f"❌ Falha no download: {label}", "error")

        time.sleep(cfg.get("espera_download", 5))

    state["running"]    = False
    state["stop_flag"]  = False
    state["atual"]      = ""
    push_log("🏁 Pipeline concluído!")


# ── Rotas API ─────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    return jsonify({
        "running":   state["running"],
        "paused":    state["paused"],
        "total":     state["total"],
        "baixados":  state["baixados"],
        "erros":     state["erros"],
        "pendentes": state["pendentes"],
        "atual":     state["atual"],
        "musicas":   state["musicas"],
        "config":    state["config"],
    })


@app.route("/api/load", methods=["POST"])
def api_load():
    data    = request.json or {}
    print(f"[DEBUG] /api/load recebido: {data}")
    caminho = data.get("arquivo", "musicas.xlsx")
    col_m   = data.get("col_musica", "Song")
    col_a   = data.get("col_artista", "Artist")
    print(f"[DEBUG] arquivo={caminho} col_m={col_m} col_a={col_a}")

    try:
        wb = openpyxl.load_workbook(caminho)
        ws = wb.active
        cab = {str(c.value).strip().lower(): c.column - 1 for c in ws[1] if c.value}

        if col_m.lower() not in cab:
            return jsonify({"ok": False, "erro": f"Coluna '{col_m}' não encontrada. Disponíveis: {list(cab.keys())}"}), 400
        if col_a.lower() not in cab:
            return jsonify({"ok": False, "erro": f"Coluna '{col_a}' não encontrada. Disponíveis: {list(cab.keys())}"}), 400

        idx_m, idx_a = cab[col_m.lower()], cab[col_a.lower()]
        musicas = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            m = str(row[idx_m]).strip() if row[idx_m] else ""
            a = str(row[idx_a]).strip() if row[idx_a] else ""
            if m and m.lower() != "none":
                musicas.append({"musica": m, "artista": a, "status": "pendente",
                                "formato": "", "bitrate": 0, "tamanho": 0,
                                "usuario": "", "score": 0})

        state["musicas"]   = musicas
        state["total"]     = len(musicas)
        state["baixados"]  = 0
        state["erros"]     = 0
        state["pendentes"] = len(musicas)
        state["running"]   = False

        return jsonify({"ok": True, "total": len(musicas)})

    except FileNotFoundError:
        return jsonify({"ok": False, "erro": f"Arquivo não encontrado: {caminho}"}), 404
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/api/start", methods=["POST"])
def api_start():
    if state["running"]:
        return jsonify({"ok": False, "erro": "Já em execução"}), 400
    if not state["musicas"]:
        return jsonify({"ok": False, "erro": "Carregue um Excel primeiro"}), 400

    state["running"]   = True
    state["paused"]    = False
    state["stop_flag"] = False

    t = threading.Thread(target=run_downloads, daemon=True)
    t.start()
    return jsonify({"ok": True})


@app.route("/api/pause", methods=["POST"])
def api_pause():
    state["paused"] = not state["paused"]
    return jsonify({"ok": True, "paused": state["paused"]})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    state["stop_flag"] = True
    return jsonify({"ok": True})


@app.route("/api/config", methods=["POST"])
def api_config():
    data = request.json or {}
    cfg  = state["config"]
    if "formatos"              in data: cfg["formatos"]              = data["formatos"]
    if "bitrate_minimo"        in data: cfg["bitrate_minimo"]        = int(data["bitrate_minimo"])
    if "tempo_busca"           in data: cfg["tempo_busca"]           = int(data["tempo_busca"])
    if "tamanho_minimo"        in data: cfg["tamanho_minimo"]        = int(data["tamanho_minimo"])
    if "organizacao_modo"      in data: cfg["organizacao_modo"]      = data["organizacao_modo"]
    if "pasta_download"        in data: cfg["pasta_download"]        = str(data["pasta_download"]).strip()
    if "pasta_personalizada"   in data: cfg["pasta_personalizada"]   = str(data["pasta_personalizada"]).strip()
    return jsonify({"ok": True, "config": cfg})


@app.route("/api/export/not-found", methods=["POST"])
def api_export_not_found():
    """Exporta apenas as músicas não encontradas para Excel"""
    try:
        musicas_nao_encontradas = [m for m in state["musicas"] if m["status"] == "não encontrado"]

        if not musicas_nao_encontradas:
            return jsonify({"ok": False, "erro": "Nenhuma música não encontrada para exportar"}), 400

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Não Encontrados"

        headers = ["Música", "Artista", "Status"]
        ws.append(headers)

        for m in musicas_nao_encontradas:
            ws.append([m["musica"], m["artista"], m["status"]])

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        return Response(
            output.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=nao_encontrados.xlsx"}
        )

    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/api/fix-permissions", methods=["POST"])
def api_fix_permissions():
    """Executa o script remove_restrictions_download.py para corrigir permissões"""
    try:
        import subprocess

        script_path = "/workspace/user_input_files/remove_restrictions_download.py"
        
        # Verificar se o script existe
        if not os.path.exists(script_path):
            return jsonify({"ok": False, "erro": f"Script não encontrado: {script_path}"}), 404

        # Executar o script com sudo
        result = subprocess.run(
            ["sudo", "python3", script_path],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0:
            push_log("✅ Permissões corrigidas com sucesso!", "info")
            return jsonify({
                "ok": True,
                "mensagem": "Permissões corrigidas!",
                "output": result.stdout
            })
        else:
            push_log(f"⚠️ Erro ao corrigir permissões: {result.stderr}", "warn")
            return jsonify({
                "ok": False,
                "erro": result.stderr or "Erro desconhecido",
                "output": result.stdout
            }), 500

    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "erro": "Tempo limite excedido"}), 500
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/api/logs")
def api_logs_sse():
    def generate():
        while True:
            try:
                item = log_queue.get(timeout=1)
                yield f"data: {json.dumps(item)}\n\n"
            except Empty:
                yield ": ping\n\n"
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/")
def index():
    response = send_from_directory(".", "gui.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=8080, type=int)
    args = parser.parse_args()

    print(f"\n🎵 Interface web iniciada → http://localhost:{args.port}\n")
    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)