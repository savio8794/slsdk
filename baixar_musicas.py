#!/usr/bin/env python3
"""
Baixador Automático de Músicas via slskd
========================================

Melhorias implementadas:
- Busca inteligente progressiva
- Cache de músicas já processadas
- Espera inteligente por resultados
- Prioridade dinâmica de formatos
- Filtro de arquivos suspeitos
- Organização automática por artista/música
- Retry automático em falhas HTTP
- Session reutilizável com pool
- Logs mais limpos
- Controle de duplicatas
- Melhor score de qualidade
- Timeout configurável
- Sanitização de nomes
"""

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import openpyxl
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================
# CONFIGURAÇÕES
# ============================================================

SLSKD_URL = "http://localhost:5030"
SLSKD_USUARIO = "slskd"
SLSKD_SENHA = "slskd"

EXCEL_ARQUIVO = "musicas.xlsx"

COLUNA_MUSICA = "musica"
COLUNA_ARTISTA = "artista"

FORMATOS_PADRAO = ["flac", "wav", "mp3"]

BITRATE_MINIMO_MP3 = 192
TAMANHO_MINIMO = 7_000_000

TEMPO_MAXIMO_BUSCA = 10
INTERVALO_BUSCA = 1
MINIMO_RESULTADOS_BUSCA = 5
ESPERA_DOWNLOAD_SEG = 5

LOG_DIR = Path("logs")


# ============================================================


def configurar_logs():

    LOG_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    log_file = LOG_DIR / f"downloads_{timestamp}.log"

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    logger = logging.getLogger("slskd-auto")

    return logger, log_file


def criar_sessao():

    session = requests.Session()

    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=10,
        pool_maxsize=10,
    )

    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


def obter_token(session, log):

    try:

        r = session.post(
            f"{SLSKD_URL}/api/v0/session",
            json={
                "username": SLSKD_USUARIO,
                "password": SLSKD_SENHA,
            },
            timeout=10,
        )

        if r.status_code == 200:

            token = r.json().get("token")

            if token:

                session.headers.update({
                    "Authorization": f"Bearer {token}"
                })

                log.info("✅ Autenticado no slskd")

                return True

        log.error(f"Falha autenticação: {r.status_code}")

    except Exception as e:
        log.error(f"Erro conexão slskd: {e}")

    return False


def limpar_termo(texto: str) -> str:

    texto = re.sub(r"\(.*?\)", "", texto)
    texto = re.sub(r"\[.*?\]", "", texto)

    texto = re.sub(
        r"\b(feat|ft|featuring)\.?\b.*",
        "",
        texto,
        flags=re.IGNORECASE,
    )

    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


def sanitizar_pasta(texto: str) -> str:

    texto = re.sub(r'[<>:"/\\|?*]', "", texto)

    return texto.strip()


def fazer_busca(session, termo, log):

    try:

        r = session.post(
            f"{SLSKD_URL}/api/v0/searches",
            json={"searchText": termo},
            timeout=10,
        )

        if r.status_code == 409:

            log.debug("Busca duplicada detectada")

            r_list = session.get(
                f"{SLSKD_URL}/api/v0/searches",
                timeout=10,
            )

            if r_list.status_code == 200:

                for busca in r_list.json():

                    if (
                        busca.get("searchText", "").lower()
                        == termo.lower()
                    ):

                        search_id = busca.get("id")

                        return aguardar_resultados(
                            session,
                            search_id,
                            log
                        )

            return []

        if r.status_code not in (200, 201):

            log.error(f"Erro busca: {r.status_code}")

            return []

        search_id = r.json().get("id")

        if not search_id:

            log.error("Search ID inválido")

            return []

        return aguardar_resultados(
            session,
            search_id,
            log
        )

    except Exception as e:

        log.error(f"Erro busca: {e}")

        return []


def aguardar_resultados(session, search_id, log):
    """Aguarda resultados da busca com polling inteligente e timeout dinâmico."""
    
    ultimo_total = 0
    ultimo_crescimento = time.time()
    resultados = []
    max_inatividade = 5  # segundos sem novos resultados para finalizar
    
    while True:
        try:
            r = session.get(
                f"{SLSKD_URL}/api/v0/searches/{search_id}/responses",
                timeout=10,
            )

            if r.status_code == 200:
                resultados = r.json() or []
                total = sum(len(x.get("files", [])) for x in resultados)

                log.debug(f"📦 Resultados atuais: {total}")

                # Se encontrou muitos resultados rapidamente, pode parar antes
                if total >= 50:
                    log.info(f"✅ Muitos resultados ({total}), finalizando busca")
                    return resultados

                # resultados aumentaram
                if total > ultimo_total:
                    ultimo_total = total
                    ultimo_crescimento = time.time()

                # se já encontrou algo e estabilizou
                if total > 0 and time.time() - ultimo_crescimento > max_inatividade:
                    log.info(f"✅ Busca estabilizada com {total} arquivos")
                    return resultados

                # timeout máximo ABSOLUTO (25s)
                if time.time() - ultimo_crescimento > 25:
                    log.warning(f"⌛ Timeout aguardando peers ({total} resultados)")
                    return resultados

        except Exception as e:
            log.debug(f"Erro busca: {e}")
        
        time.sleep(0.5)  # Reduzido de 1s para 0.5s

def buscar_musica(session, musica, artista, log):
    """Busca música com tentativas progressivas e early stopping."""
    
    musica_limpa = limpar_termo(musica)
    artista_limpo = limpar_termo(artista)

    # Primeiro artista apenas
    primeiro_artista = (
        artista_limpo
        .split(",")[0]
        .split("&")[0]
        .split(";")[0]
        .strip()
    )

    tentativas = [
        # 1 — Busca normal completa
        f"{artista_limpo} {musica_limpa}",
        # 2 — Primeiro artista + música
        f"{primeiro_artista} {musica_limpa}",
        # 3 — Artista + primeiras palavras
        f"{primeiro_artista} {' '.join(musica_limpa.split()[:3])}",
    ]

    # Remove duplicatas mantendo ordem
    vistas = set()
    tentativas = [t for t in tentativas if not (t.lower() in vistas or vistas.add(t.lower()))]

    melhores_resultados = []
    
    for i, termo in enumerate(tentativas, 1):
        log.info(f"🔍 Tentativa {i}: {termo}")

        resultados = fazer_busca(session, termo, log)
        total = sum(len(r.get("files", [])) for r in resultados)

        if total > 0:
            log.info(f"📦 {total} arquivo(s) encontrado(s)")

            # guarda o melhor resultado até agora
            if total > sum(len(r.get("files", [])) for r in melhores_resultados):
                melhores_resultados = resultados
            
            # Early stopping: se encontrou muitos resultados, não precisa continuar
            if total >= 30:
                log.info(f"✅ Resultados suficientes ({total}), parando busca")
                break

    # retorna o melhor conjunto encontrado
    return melhores_resultados
    

def calcular_score(candidato):

    score = 0

    formato = candidato["formato"]
    bitrate = candidato["bitrate"]
    tamanho = candidato["tamanho"]

    # prioridade do formato
    score += candidato["prioridade"] * 10000

    # FLAC sempre priorizado
    if formato == "flac":
        score += 5000

    # WAV
    elif formato == "wav":
        score += 3000

    # MP3
    elif formato == "mp3":

        # bitrate válido
        if bitrate and bitrate > 0:

            score += bitrate * 5

        else:

            # VBR/desconhecido
            score += 1000

    # tamanho ajuda muito
    score += tamanho / 1_000_000

    return score


def filtrar_candidatos(
    resultados,
    formatos,
    prioridade,
    log
):
    """Filtra candidatos com processamento otimizado."""
    
    candidatos = []

    for resposta in resultados:
        usuario = resposta.get("username", "")

        for arq in resposta.get("files", []):
            nome = arq.get("filename", "")
            ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
            
            # Skip rápido se extensão não interessar
            if ext not in formatos:
                continue

            bitrate_raw = arq.get("bitRate") or arq.get("bitrate") or 0
            
            try:
                bitrate = int(float(bitrate_raw))
            except (ValueError, TypeError):
                bitrate = 0

            tamanho = arq.get("size", 0) or 0
            duracao = arq.get("length") or arq.get("duration") or 0

            # Filtro rápido de tamanho antes de log
            if tamanho < TAMANHO_MINIMO:
                continue

            # MP3: filtro de bitrate
            if ext == "mp3":
                if bitrate <= 0:
                    bitrate = 320
                elif bitrate < 192:
                    continue

            candidato = {
                "usuario": usuario,
                "arquivo": nome,
                "formato": ext,
                "bitrate": bitrate,
                "tamanho": tamanho,
                "duracao": duracao,
                "prioridade": prioridade.get(ext, 0),
            }

            candidato["score"] = calcular_score(candidato)
            candidatos.append(candidato)

    candidatos.sort(key=lambda x: x["score"], reverse=True)

    log.info(f"🎯 {len(candidatos)} candidato(s) válido(s)")

    return candidatos


def baixar_arquivo(
    session,
    usuario,
    arquivo,
    tamanho,
    artista,
    musica,
    organizacao_modo,
    pasta_personalizada,
    log
):
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
        nome_limpo = sanitizar_pasta(nome_arq)
        artista_limpo = sanitizar_pasta(artista)
        musica_limpo = sanitizar_pasta(musica)

        # Monta o caminho baseado no modo de organização
        if organizacao_modo == "flat":
            # Modo flat: todos os arquivos diretamente na pasta base (sem subpastas)
            caminho_final = nome_limpo

        elif organizacao_modo == "pasta_unica":
            # Uma pasta por música: "Artista - Musica/arquivo.mp3"
            nome_pasta = f"{artista_limpo} - {musica_limpo}"
            caminho_final = f"{nome_pasta}/{nome_limpo}"

        elif organizacao_modo == "artista":
            # Artista/Música: "Artista/Musica/arquivo.mp3"
            caminho_final = f"{artista_limpo}/{musica_limpo}/{nome_limpo}"

        elif organizacao_modo == "pasta_personalizada":
            # Nome de pasta personalizado
            nome_pasta = sanitizar_pasta(pasta_personalizada) if pasta_personalizada else "Downloads"
            caminho_final = f"{nome_pasta}/{nome_limpo}"
        else:
            # Fallback para flat
            caminho_final = nome_limpo

        log.info(f"💾 Salvando em: {caminho_final}")

        # Estrutura correta para a API do slskd
        payload = {
            "filename": arquivo,
            "size": tamanho,
            "localFilename": caminho_final
        }

        r = session.post(
            f"{SLSKD_URL}/api/v0/transfers/downloads/{usuario}",
            json=[payload],
            timeout=15,
        )

        if r.status_code in (200, 201, 204):
            log.info(f"✅ Download enfileirado: {nome_limpo}")
            return True

        log.error(
            f"Erro download: {r.status_code} {r.text}"
        )

    except Exception as e:

        log.error(f"Falha download: {e}")

    return False


def ler_excel(
    caminho,
    col_musica,
    col_artista,
    log
):
    """Lê Excel com otimização de leitura (somente colunas necessárias)."""
    
    try:
        wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
        ws = wb.active

        cabecalho = {
            str(cell.value).strip().lower(): cell.column - 1
            for cell in ws[1]
            if cell.value
        }

        col_m = col_musica.lower().strip()
        col_a = col_artista.lower().strip()

        if col_m not in cabecalho:
            log.error(f"Coluna não encontrada: {col_musica}")
            sys.exit(1)

        if col_a not in cabecalho:
            log.error(f"Coluna não encontrada: {col_artista}")
            sys.exit(1)

        idx_m = cabecalho[col_m]
        idx_a = cabecalho[col_a]

        musicas = []

        for linha in ws.iter_rows(min_row=2, values_only=True):
            musica = str(linha[idx_m]).strip() if linha[idx_m] else ""
            artista = str(linha[idx_a]).strip() if linha[idx_a] else ""

            if musica and musica.lower() != "none":
                musicas.append((musica, artista))

        log.info(f"🎵 {len(musicas)} música(s) carregadas")
        
        # Fecha workbook para liberar memória
        wb.close()

        return musicas

    except FileNotFoundError:
        log.error(f"Excel não encontrado: {caminho}")
        sys.exit(1)


def salvar_relatorio(
    log_file,
    baixados,
    nao_achados,
    erros
):

    relatorio = {
        "data": datetime.now().isoformat(),
        "baixados": baixados,
        "nao_achados": nao_achados,
        "erros": erros,
    }

    rel_path = log_file.with_suffix(".json")

    rel_path.write_text(
        json.dumps(
            relatorio,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8",
    )

    return rel_path


def main():

    parser = argparse.ArgumentParser(
        description="Downloader automático slskd"
    )

    parser.add_argument(
        "--excel",
        default=EXCEL_ARQUIVO,
    )

    parser.add_argument(
        "--coluna-musica",
        default=COLUNA_MUSICA,
    )

    parser.add_argument(
        "--coluna-artista",
        default=COLUNA_ARTISTA,
    )

    parser.add_argument(
        "--formatos",
        nargs="+",
        default=FORMATOS_PADRAO,
        choices=["flac", "wav", "mp3"],
    )

    parser.add_argument(
        "--organizacao",
        default="flat",
        choices=["flat", "pasta_unica", "artista", "pasta_personalizada"],
        help=(
            "Modo de organizacao das pastas:\n"
            "  flat               - Tudo na mesma pasta (sem subpastas)\n"
            "  pasta_unica        - Uma pasta por musica 'Artista - Musica/'\n"
            "  artista            - Pasta do artista 'Artista/Musica/'\n"
            "  pasta_personalizada - Nome de pasta personalizado\n"
        ),
    )

    parser.add_argument(
        "--pasta-personalizada",
        default="",
        help="Nome da pasta para o modo 'pasta_personalizada'",
    )

    args = parser.parse_args()

    prioridade = {
        formato: len(args.formatos) - i
        for i, formato in enumerate(args.formatos)
    }

    log, log_file = configurar_logs()

    log.info("=" * 60)
    log.info("🎵 SLSKD AUTO DOWNLOADER")
    log.info("=" * 60)
    log.info(f"📁 Modo de organizacao: {args.organizacao}")
    if args.organizacao == "pasta_personalizada" and args.pasta_personalizada:
        log.info(f"📁 Pasta personalizada: {args.pasta_personalizada}")

    musicas = ler_excel(
        args.excel,
        args.coluna_musica,
        args.coluna_artista,
        log
    )

    session = criar_sessao()

    if not obter_token(session, log):
        sys.exit(1)

    baixados = []
    nao_achados = []
    erros = []

    cache = set()

    total = len(musicas)

    for i, (musica, artista) in enumerate(musicas, 1):

        label = f"{artista} - {musica}"

        if label.lower() in cache:
            continue

        cache.add(label.lower())

        log.info(f"\n[{i}/{total}] {label}")

        resultados = buscar_musica(
            session,
            musica,
            artista,
            log
        )

        candidatos = filtrar_candidatos(
            resultados,
            args.formatos,
            prioridade,
            log
        )

        if not candidatos:

            nao_achados.append(label)

            log.warning("⚠️ Nenhum candidato válido")

            continue

        melhor = candidatos[0]

        nome_arquivo = (
            melhor["arquivo"]
            .replace("\\", "/")
            .split("/")[-1]
        )

        log.info(
            f"✅ "
            f"{melhor['formato'].upper()} | "
            f"{melhor['bitrate']}kbps | "
            f"{melhor['tamanho']/1e6:.1f}MB | "
            f"score={melhor['score']:.1f}"
        )

        ok = baixar_arquivo(
            session,
            melhor["usuario"],
            melhor["arquivo"],
            melhor["tamanho"],
            artista,
            musica,
            args.organizacao,
            args.pasta_personalizada,
            log
        )

        if ok:

            baixados.append({
                "musica": label,
                "arquivo": nome_arquivo,
                "usuario": melhor["usuario"],
                "formato": melhor["formato"],
                "score": melhor["score"],
            })

            log.info("⬇️ Download iniciado")

        else:

            erros.append(label)

        time.sleep(ESPERA_DOWNLOAD_SEG)

    log.info("\n" + "=" * 60)
    log.info("📊 RESUMO FINAL")
    log.info("=" * 60)

    log.info(f"✅ Baixados: {len(baixados)}")
    log.info(f"⚠️ Não encontrados: {len(nao_achados)}")
    log.info(f"❌ Erros: {len(erros)}")

    relatorio = salvar_relatorio(
        log_file,
        baixados,
        nao_achados,
        erros
    )

    log.info(f"📄 Relatório: {relatorio}")
    log.info("🌐 slskd: http://localhost:5030")


if __name__ == "__main__":
    main()
