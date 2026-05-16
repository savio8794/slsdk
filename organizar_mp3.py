#!/usr/bin/env python3
"""
Organizador de Músicas por Artista (e opcionalmente Gênero)
============================================================
Lê as tags ID3 / Vorbis / RIFF dos arquivos MP3, FLAC e WAV
e move para uma estrutura de pastas configurável.

Modos disponíveis:
  --modo artista          →  Artista/
  --modo genero           →  Gênero/
  --modo artista_album    →  Artista/Álbum/
  --modo genero_artista   →  Gênero/Artista/

Uso:
    python organizar_mp3.py downloads/
    python organizar_mp3.py downloads/ --modo artista_album
    python organizar_mp3.py downloads/ --destino organizado/ --simular
"""

import os
import shutil
import argparse
import logging
import json
from pathlib import Path
from datetime import datetime

try:
    from mutagen.mp3  import MP3
    from mutagen.flac import FLAC
    from mutagen.wave import WAVE
    from mutagen.id3  import ID3, ID3NoHeaderError
except ImportError:
    print("❌ Biblioteca 'mutagen' não encontrada.")
    print("   Instale com: pip install mutagen")
    raise SystemExit(1)

# ── Constantes ────────────────────────────────────────────
SEM_ARTISTA = "Artista Desconhecido"
SEM_ALBUM   = "Álbum Desconhecido"
SEM_GENERO  = "Sem Gênero"
LOG_DIR     = Path("logs")
EXTENSOES   = {".mp3", ".flac", ".wav"}
# ─────────────────────────────────────────────────────────


def configurar_logs(simular: bool):
    LOG_DIR.mkdir(exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefixo  = "simulacao" if simular else "organizacao"
    log_file = LOG_DIR / f"{prefixo}_{ts}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("organizer"), log_file


def ler_tags(caminho: Path) -> dict:
    """Extrai artista, álbum e gênero do arquivo de áudio."""
    tags = {"artista": SEM_ARTISTA, "album": SEM_ALBUM, "genero": SEM_GENERO}

    try:
        ext = caminho.suffix.lower()

        if ext == ".mp3":
            try:
                id3 = ID3(caminho)
                tags["artista"] = str(id3.get("TPE1", SEM_ARTISTA)).strip() or SEM_ARTISTA
                tags["album"]   = str(id3.get("TALB", SEM_ALBUM)).strip()   or SEM_ALBUM
                tags["genero"]  = str(id3.get("TCON", SEM_GENERO)).strip()  or SEM_GENERO
            except ID3NoHeaderError:
                pass

        elif ext == ".flac":
            audio = FLAC(caminho)
            tags["artista"] = (audio.get("artist",  [SEM_ARTISTA])[0] or SEM_ARTISTA).strip()
            tags["album"]   = (audio.get("album",   [SEM_ALBUM])[0]   or SEM_ALBUM).strip()
            tags["genero"]  = (audio.get("genre",   [SEM_GENERO])[0]  or SEM_GENERO).strip()

        elif ext == ".wav":
            try:
                audio = WAVE(caminho)
                id3   = audio.tags or {}
                tags["artista"] = str(id3.get("TPE1", SEM_ARTISTA)).strip() or SEM_ARTISTA
                tags["album"]   = str(id3.get("TALB", SEM_ALBUM)).strip()   or SEM_ALBUM
                tags["genero"]  = str(id3.get("TCON", SEM_GENERO)).strip()  or SEM_GENERO
            except Exception:
                pass

    except Exception as e:
        logging.getLogger("organizer").debug(f"Erro ao ler tags de {caminho.name}: {e}")

    return tags


def sanitizar(nome: str) -> str:
    """Remove caracteres inválidos para nomes de pasta no Windows/Linux."""
    for c in r'\/:*?"<>|':
        nome = nome.replace(c, "_")
    return nome.strip(" .") or "Desconhecido"


def montar_caminho_destino(tags: dict, modo: str) -> Path:
    """Retorna o caminho relativo da pasta de destino conforme o modo."""
    artista = sanitizar(tags["artista"])
    album   = sanitizar(tags["album"])
    genero  = sanitizar(tags["genero"])

    if modo == "artista":
        return Path(artista)
    elif modo == "artista_album":
        return Path(artista) / album
    elif modo == "genero":
        return Path(genero)
    elif modo == "genero_artista":
        return Path(genero) / artista
    else:
        return Path(artista)


def resolver_conflito(destino: Path) -> Path:
    """Se o arquivo já existir no destino, adiciona sufixo numérico."""
    if not destino.exists():
        return destino
    base, ext = destino.stem, destino.suffix
    i = 1
    while destino.exists():
        destino = destino.parent / f"{base}_{i}{ext}"
        i += 1
    return destino


def organizar(origem: Path, destino_base: Path, modo: str, simular: bool, log):
    arquivos = [
        f for f in origem.rglob("*")
        if f.is_file() and f.suffix.lower() in EXTENSOES
    ]

    if not arquivos:
        log.warning(f"Nenhum arquivo de áudio encontrado em: {origem}")
        return

    log.info(f"{'[SIMULAÇÃO] ' if simular else ''}Encontrados {len(arquivos)} arquivo(s)")
    log.info(f"Modo: {modo.upper()} | Destino base: {destino_base}")
    if simular:
        log.info("Nenhum arquivo será movido (use sem --simular para mover de verdade)\n")

    contadores = {}
    erros      = []
    movidos    = []

    for arq in sorted(arquivos):
        tags         = ler_tags(arq)
        pasta_rel    = montar_caminho_destino(tags, modo)
        pasta_dest   = destino_base / pasta_rel
        novo_caminho = resolver_conflito(pasta_dest / arq.name)

        artista_label = tags["artista"]
        log.info(f"  [{artista_label}] {arq.name}")
        log.debug(f"    → {novo_caminho}")

        if not simular:
            try:
                pasta_dest.mkdir(parents=True, exist_ok=True)
                shutil.move(str(arq), str(novo_caminho))
                contadores[str(pasta_rel)] = contadores.get(str(pasta_rel), 0) + 1
                movidos.append({"arquivo": arq.name, "destino": str(novo_caminho), **tags})
            except Exception as e:
                log.error(f"    ❌ Erro ao mover {arq.name}: {e}")
                erros.append(arq.name)
        else:
            contadores[str(pasta_rel)] = contadores.get(str(pasta_rel), 0) + 1

    # Resumo
    log.info("\n" + "=" * 55)
    log.info("📊 RESUMO")
    log.info("=" * 55)
    for pasta, qtd in sorted(contadores.items()):
        log.info(f"  {pasta:<40} {qtd:>4} arquivo(s)")
    log.info(f"\n  Total: {sum(contadores.values())} arquivo(s)")
    if erros:
        log.warning(f"  Erros: {len(erros)} arquivo(s) não movidos")
        for e in erros:
            log.warning(f"    - {e}")

    if not simular:
        # Salva relatório JSON
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        rel_path = LOG_DIR / f"organizacao_{ts}.json"
        rel_path.write_text(
            json.dumps(
                {"data": datetime.now().isoformat(), "modo": modo,
                 "movidos": movidos, "erros": erros},
                ensure_ascii=False, indent=2
            ),
            encoding="utf-8"
        )
        log.info(f"  📄 Relatório JSON → {rel_path}")
        log.info("✅ Organização concluída!")
    else:
        log.info("ℹ️  Execute sem --simular para mover de verdade.")


def main():
    parser = argparse.ArgumentParser(
        description="Organiza MP3/FLAC/WAV em pastas por artista, álbum ou gênero."
    )
    parser.add_argument("origem",  help="Pasta com os arquivos de áudio")
    parser.add_argument("--destino", default=None,
                        help="Pasta de destino (padrão: mesma que a origem)")
    parser.add_argument(
        "--modo",
        default="artista",
        choices=["artista", "artista_album", "genero", "genero_artista"],
        help=(
            "Estrutura de pastas:\n"
            "  artista         → Artista/\n"
            "  artista_album   → Artista/Álbum/\n"
            "  genero          → Gênero/\n"
            "  genero_artista  → Gênero/Artista/"
        )
    )
    parser.add_argument("--simular", action="store_true",
                        help="Mostra o que seria feito sem mover nada")
    args = parser.parse_args()

    origem = Path(args.origem).resolve()
    destino = Path(args.destino).resolve() if args.destino else origem

    if not origem.exists() or not origem.is_dir():
        print(f"❌ Pasta não encontrada: {origem}")
        raise SystemExit(1)

    log, log_file = configurar_logs(args.simular)
    log.info("🎵 Organizador de Áudio")
    log.info(f"   Log → {log_file}")

    organizar(origem, destino, args.modo, args.simular, log)


if __name__ == "__main__":
    main()
