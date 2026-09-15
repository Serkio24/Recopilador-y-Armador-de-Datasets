# -*- coding: utf-8 -*-
"""Lo que cambia entre Windows y macOS, en un solo sitio.

El proyecto se escribio sobre Windows y corre tambien en un Mac Mini. Las
diferencias reales son pocas --donde deja el .venv su interprete, con que se
abre una carpeta, en que rutas esta ffmpeg cuando no aparece en el PATH y con
que gestor se instalan las dependencias externas--, pero estaban repartidas por
el codigo y por los mensajes de ayuda, que es justo donde mas duele
equivocarse: una receta que nombra `winget` en un Mac deja al usuario sin saber
que hacer.

Linux no es un objetivo, pero el contenedor de Docker corre ahi y
`abrir_carpeta` podria acabar ejecutandose dentro, asi que conserva su rama con
xdg-open.
"""

import os
import subprocess
import sys
from pathlib import Path

ES_WINDOWS = os.name == "nt"
ES_MAC = sys.platform == "darwin"

# Interprete y lanzador tal y como hay que escribirlos en una terminal de este
# sistema. Solo se usan para componer mensajes: quien necesita la ruta de
# verdad es `main.py:_python_del_venv`, que la calcula aparte porque tiene que
# hacerlo antes de poder importar nada.
PYTHON_VENV = r".venv\Scripts\python.exe" if ES_WINDOWS else ".venv/bin/python"
LANZADOR = "recopilador.bat" if ES_WINDOWS else "./recopilador.sh"

# En Windows el lanzador `py` viene con el instalador oficial; en macOS no
# existe y el `python3` del sistema es el 3.9 de Apple, que no vale (yt-dlp).
# De ahi que en el Mac se nombre el 3.11 de Homebrew de forma explicita.
CREAR_VENV = ("py -3.11 -m venv .venv" if ES_WINDOWS
              else "python3.11 -m venv .venv")

INSTALAR_FFMPEG = ("winget install --id Gyan.FFmpeg -e --scope user" if ES_WINDOWS
                   else "brew install ffmpeg")
INSTALAR_OLLAMA = ("winget install --id Ollama.Ollama -e" if ES_WINDOWS
                   else "brew install --cask ollama")


def carpetas_ffmpeg_tipicas():
    """Sitios donde buscar ffmpeg cuando no esta en el PATH.

    Hace falta porque los dos gestores instalan fuera del PATH de la sesion en
    curso: winget no refresca la variable en las terminales ya abiertas, y en
    macOS una app abierta desde el Finder hereda un PATH minimo que no incluye
    el /opt/homebrew/bin donde vive el ffmpeg de Homebrew.
    """
    candidatos = []
    if ES_WINDOWS:
        local = os.getenv("LOCALAPPDATA")
        if local:
            candidatos.extend(Path(local).glob(
                "Microsoft/WinGet/Packages/*FFmpeg*/**/bin/ffmpeg.exe"))
        for base in (r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin"):
            candidatos.append(Path(base) / "ffmpeg.exe")
    else:
        # /opt/homebrew es Apple Silicon y /usr/local el Homebrew de los Intel;
        # MacPorts usa /opt/local.
        for base in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"):
            candidatos.append(Path(base) / "ffmpeg")
    return candidatos


def abrir_carpeta(ruta):
    """Abre una carpeta en el explorador del sistema. Crea la ruta si falta.

    Devuelve True si se pudo lanzar el explorador. Antes esto asumia que todo
    lo que no fuera Windows era Linux y llamaba a xdg-open, que en un Mac no
    existe: el boton «Abrir carpeta» reventaba con FileNotFoundError.
    """
    ruta = Path(ruta)
    ruta.mkdir(parents=True, exist_ok=True)
    try:
        if ES_WINDOWS:
            os.startfile(str(ruta))                 # noqa: S606 (solo Windows)
        elif ES_MAC:
            subprocess.Popen(["open", str(ruta)])
        else:
            subprocess.Popen(["xdg-open", str(ruta)])
    except (OSError, AttributeError):
        # Sin explorador (una sesion sin escritorio, o el contenedor) no hay
        # nada que hacer, pero tampoco es motivo para tumbar la ventana.
        return False
    return True
