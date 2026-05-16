#!/usr/bin/env python3
"""
Orquestrador — Pipeline Completo de Download
==============================================
Executa todo o fluxo em sequência:

  1. rekordbox_faltantes.py  → compara Excel com Rekordbox, gera lista de faltantes
  2. baixar_musicas.py       → baixa os faltantes via slskd (filtra 310+ kbps)
  3. verificar_qualidade.py  → analisa espectro, move upscales para quarentena/
  4. organizar_mp3.py        → organiza genuínos por artista (ou modo escolhido)

Uso:
    python orquestrador.py
    python orquestrador.py --pular-rekordbox        # se nao usar Rekordbox
    python orquestrador.py --pular-verificacao      # pula analise espectral
    python orquestrador.py --modo-organizacao artista_album
    python orquestrador.py --formatos flac wav mp3
    python orquestrador.py --simular                # roda tudo sem mover/baixar nada
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ============================================================
#  CONFIGURAÇÕES — ajuste conforme necessário
# ============================================================
EXCEL_ARQUIVO       = "musicas.xlsx"
COLUNA_MUSICA       = "musica"
COLUNA_ARTISTA      = "artista"
XML_REKORDBOX       = "rekordbox.xml"
PASTA_DOWNLOADS     = Path("/Pasta Pessoal/slkd/downloads")
PASTA_QUARENTENA    = Path("/Pasta Pessoal/slkd/quarentena")
PASTA_ORGANIZADO    = Path("/Pasta Pessoal/slkd/quarentena")
FORMATOS_PADRAO     = ["flac", "wav", "mp3"]
MODO_ORGANIZACAO    = "artista"   # artista | artista_album | genero | genero_artista
LOG_DIR             = Path("logs")
# ============================================================

SCRIPTS = {
    "rekordbox":    Path("rekordbox_faltantes.py"),
    "downloader":   Path("baixar_musicas.py"),
    "qualidade":    Path("verificar_qualidade.py"),
    "organizador":  Path("organizar_mp3.py"),
}


def configurar_logs():
    LOG_DIR.mkdir(exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"pipeline_{ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("pipeline"), log_file


def separador(log, titulo: str):
    log.info("")
    log.info("=" * 55)
    log.info(f"  {titulo}")
    log.info("=" * 55)


def rodar_script(log, script: Path, args: list, simular: bool) -> bool:
    """Executa um script Python como subprocesso e retorna True se OK."""
    if not script.exists():
        log.error(f"Script não encontrado: {script}")
        return False

    cmd = [sys.executable, str(script)] + args
    if simular:
        cmd.append("--simular")

    log.info(f"▶ Executando: {' '.join(cmd)}")
    log.info("")

    try:
        resultado = subprocess.run(cmd, check=False)
        if resultado.returncode != 0:
            log.error(f"Script encerrou com código {resultado.returncode}")
            return False
        return True
    except Exception as e:
        log.error(f"Erro ao executar {script.name}: {e}")
        return False


def encontrar_excel_faltantes() -> Path | None:
    """Procura o Excel de faltantes mais recente gerado pelo rekordbox_faltantes.py."""
    if not LOG_DIR.exists():
        return None
    candidatos = sorted(LOG_DIR.glob("faltantes_*.xlsx"), reverse=True)
    return candidatos[0] if candidatos else None


def contar_arquivos(pasta: Path) -> dict:
    """Conta arquivos de áudio na pasta."""
    ext_map = {".mp3": 0, ".flac": 0, ".wav": 0}
    for f in pasta.rglob("*"):
        if f.suffix.lower() in ext_map:
            ext_map[f.suffix.lower()] += 1
    return ext_map


def aguardar_downloads(log, pasta: Path, timeout_min: int = 60):
    """
    Aguarda o slskd terminar os downloads monitorando a pasta.
    Considera concluído quando nenhum arquivo novo aparece por 15s.
    """
    log.info(f"⏳ Aguardando downloads em '{pasta}' (timeout: {timeout_min} min)...")
    log.info("   (Você pode acompanhar em http://localhost:5030)")

    pasta.mkdir(exist_ok=True)
    ultimo_count = -1
    sem_mudanca  = 0
    inicio       = time.time()
    limite       = timeout_min * 60
    intervalo    = 2.5  # Reduzido de 5s para 2.5s
    
    # Cache de arquivos já vistos para evitar recontagem completa
    arquivos_vistos = set()

    while True:
        # Contagem mais eficiente usando list comprehension direta
        count = sum(1 for f in pasta.iterdir() if f.is_file() and f.suffix.lower() in {".mp3", ".flac", ".wav"})

        if count != ultimo_count:
            log.debug(f"  📥 Arquivos baixados até agora: {count}")
            ultimo_count = count
            sem_mudanca  = 0
        else:
            sem_mudanca += 1

        # 6 verificações sem mudança (15s) = downloads concluídos
        if sem_mudanca >= 6 and count > 0:
            log.info(f"  ✅ Downloads estabilizaram em {count} arquivo(s).")
            break

        if time.time() - inicio > limite:
            log.warning(f"  ⚠️  Timeout de {timeout_min} min atingido.")
            break

        time.sleep(intervalo)


def main():
    parser = argparse.ArgumentParser(
        description="Orquestrador do pipeline completo de download e organização."
    )
    parser.add_argument("--excel",               default=EXCEL_ARQUIVO,    help="Arquivo Excel com wishlist")
    parser.add_argument("--xml",                 default=XML_REKORDBOX,    help="XML exportado do Rekordbox")
    parser.add_argument("--coluna-musica",        default=COLUNA_MUSICA,    help="Coluna de músicas no Excel")
    parser.add_argument("--coluna-artista",       default=COLUNA_ARTISTA,   help="Coluna de artistas no Excel")
    parser.add_argument("--formatos",            nargs="+", default=FORMATOS_PADRAO,
                        choices=["flac", "wav", "mp3"],
                        help="Formatos aceitos em ordem de preferência")
    parser.add_argument("--modo-organizacao",    default=MODO_ORGANIZACAO,
                        choices=["artista", "artista_album", "genero", "genero_artista"],
                        help="Estrutura de pastas para organização")
    parser.add_argument("--pular-rekordbox",     action="store_true", help="Pula a etapa de comparação com Rekordbox")
    parser.add_argument("--pular-verificacao",   action="store_true", help="Pula a análise espectral de qualidade")
    parser.add_argument("--pular-organizacao",   action="store_true", help="Pula a organização em pastas")
    parser.add_argument("--timeout-download",    default=60, type=int,     help="Minutos para aguardar downloads (padrão: 60)")
    parser.add_argument("--simular",             action="store_true",      help="Executa tudo sem baixar ou mover arquivos")
    args = parser.parse_args()

    log, log_file = configurar_logs()

    log.info("╔══════════════════════════════════════════════════════╗")
    log.info("║   🎵 Pipeline Completo — Soulseek Auto               ║")
    log.info("╚══════════════════════════════════════════════════════╝")
    log.info(f"  Excel:       {args.excel}")
    log.info(f"  Formatos:    {' > '.join(f.upper() for f in args.formatos)}")
    log.info(f"  Organização: {args.modo_organizacao}")
    log.info(f"  Simulação:   {'SIM' if args.simular else 'NÃO'}")

    estado = {
        "inicio":       datetime.now().isoformat(),
        "etapas":       {},
        "args":         vars(args),
    }

    excel_para_baixar = args.excel

    # ──────────────────────────────────────────────────────
    # ETAPA 1 — Rekordbox: descobre o que falta
    # ──────────────────────────────────────────────────────
    if not args.pular_rekordbox:
        separador(log, "ETAPA 1 / 4 — Comparando com Rekordbox")

        xml_path = Path(args.xml)
        if not xml_path.exists():
            log.warning(f"XML do Rekordbox não encontrado: {args.xml}")
            log.warning("Pulando etapa Rekordbox e usando o Excel completo.")
            estado["etapas"]["rekordbox"] = "pulado (xml nao encontrado)"
        else:
            ok = rodar_script(log, SCRIPTS["rekordbox"], [
                "--xml",            args.xml,
                "--excel",          args.excel,
                "--coluna-musica",  args.coluna_musica,
                "--coluna-artista", args.coluna_artista,
            ], simular=False)  # rekordbox nunca precisa de --simular

            estado["etapas"]["rekordbox"] = "ok" if ok else "erro"

            if ok:
                faltantes_xlsx = encontrar_excel_faltantes()
                if faltantes_xlsx:
                    log.info(f"\n  📥 Usando lista de faltantes: {faltantes_xlsx.name}")
                    excel_para_baixar = str(faltantes_xlsx)
                else:
                    log.warning("  Nenhuma lista de faltantes gerada — todas já estão no Rekordbox?")
                    log.info("  Encerrando pipeline.")
                    sys.exit(0)
    else:
        separador(log, "ETAPA 1 / 4 — Rekordbox [PULADA]")
        log.info("  Usando Excel completo para download.")
        estado["etapas"]["rekordbox"] = "pulado"

    # ──────────────────────────────────────────────────────
    # ETAPA 2 — Download via slskd
    # ──────────────────────────────────────────────────────
    separador(log, "ETAPA 2 / 4 — Baixando músicas via Soulseek")

    ok = rodar_script(log, SCRIPTS["downloader"], [
        "--excel",          excel_para_baixar,
        "--coluna-musica",  args.coluna_musica,
        "--coluna-artista", args.coluna_artista,
        "--formatos",       *args.formatos,
    ], simular=args.simular)

    estado["etapas"]["download"] = "ok" if ok else "erro"

    if not args.simular and ok:
        # Aguarda downloads concluírem no slskd
        aguardar_downloads(log, PASTA_DOWNLOADS, timeout_min=args.timeout_download)

    # ──────────────────────────────────────────────────────
    # ETAPA 3 — Verificação de qualidade (detector de upscale)
    # ──────────────────────────────────────────────────────
    if not args.pular_verificacao:
        separador(log, "ETAPA 3 / 4 — Verificando qualidade (detector de upscale)")

        ok = rodar_script(log, SCRIPTS["qualidade"], [
            str(PASTA_DOWNLOADS),
            "--mover-ruins", str(PASTA_QUARENTENA),
        ], simular=args.simular)

        estado["etapas"]["qualidade"] = "ok" if ok else "erro"

        if not args.simular:
            contagem = contar_arquivos(PASTA_QUARENTENA)
            total_ruins = sum(contagem.values())
            if total_ruins:
                log.warning(f"\n  ⚠️  {total_ruins} arquivo(s) movidos para quarentena: {PASTA_QUARENTENA}/")
                log.warning("  Verifique manualmente se quer tentar baixar novamente.")
    else:
        separador(log, "ETAPA 3 / 4 — Verificação de qualidade [PULADA]")
        estado["etapas"]["qualidade"] = "pulado"

    # ──────────────────────────────────────────────────────
    # ETAPA 4 — Organização por artista
    # ──────────────────────────────────────────────────────
    if not args.pular_organizacao:
        separador(log, "ETAPA 4 / 4 — Organizando por artista")

        ok = rodar_script(log, SCRIPTS["organizador"], [
            str(PASTA_DOWNLOADS),
            "--destino", str(PASTA_ORGANIZADO),
            "--modo",    args.modo_organizacao,
        ], simular=args.simular)

        estado["etapas"]["organizacao"] = "ok" if ok else "erro"
    else:
        separador(log, "ETAPA 4 / 4 — Organização [PULADA]")
        estado["etapas"]["organizacao"] = "pulado"

    # ──────────────────────────────────────────────────────
    # Resumo final
    # ──────────────────────────────────────────────────────
    separador(log, "PIPELINE CONCLUÍDO")
    estado["fim"] = datetime.now().isoformat()

    for etapa, resultado in estado["etapas"].items():
        icone = "✅" if resultado == "ok" else ("⏭️ " if "pulado" in resultado else "❌")
        log.info(f"  {icone} {etapa:<20} {resultado}")

    log.info(f"\n  📂 Downloads:   {PASTA_DOWNLOADS}/")
    log.info(f"  📂 Organizado:  {PASTA_ORGANIZADO}/")
    log.info(f"  📂 Quarentena:  {PASTA_QUARENTENA}/")
    log.info(f"  📄 Log:         {log_file}")

    json_path = log_file.with_suffix(".json")
    json_path.write_text(
        json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info(f"  📄 Relatório:   {json_path}")


if __name__ == "__main__":
    main()
