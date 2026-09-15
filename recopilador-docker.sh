#!/usr/bin/env bash
# Equivalente de recopilador-docker.bat para macOS. Ejecuta el CLI dentro del
# contenedor, con el compose que no pide GPU.
#
#   ./recopilador-docker.sh --cli --tema "pesca artesanal" --n 50
#   ./recopilador-docker.sh --analizar --exportar
#
# La interfaz grafica no va por aqui: se abre nativa con ./recopilador.sh.
set -euo pipefail
cd "$(dirname "$0")"

exec docker compose -f docker-compose.mac.yml run --rm app "$@"
