#!/usr/bin/env bash
# Equivalente de recopilador.bat para macOS: abre la interfaz grafica con el
# entorno virtual del proyecto.
#
#   ./recopilador.sh                                 -> ventana
#   ./recopilador.sh --cli --tema "pesca" --n 50     -> CLI
#
# No hay un `pythonw` que soltar la consola como en Windows: en macOS la ventana
# de Tk se queda colgando de esta terminal, asi que conviene dejarla abierta.
set -euo pipefail
cd "$(dirname "$0")"

PY=".venv/bin/python"

if [ ! -x "$PY" ]; then
    cat >&2 <<'AYUDA'
No existe el entorno del proyecto (.venv). Crealo con:

    python3.11 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt

Ojo con el interprete: el python3 que trae macOS es el 3.9 de Apple, y el
yt-dlp mas nuevo que se puede instalar ahi es de 2025, que YouTube ya rechaza.
Hace falta el 3.11 de Homebrew:

    brew install python@3.11 ffmpeg node

NO instales requirements-gpu.txt: son las libs de CUDA, no existen para macOS y
aqui la transcripcion va por CPU de todas formas.
AYUDA
    exit 1
fi

exec "$PY" main.py "$@"
