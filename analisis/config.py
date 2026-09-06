# -*- coding: utf-8 -*-
"""Parametros de la etapa de analisis.

Las rutas de datos NO se repiten aqui: se toman de `recopilador.config.Settings`,
que ya sabe donde estan los videos y el indice. Esto solo describe los modelos y
como hablar con ellos.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from recopilador.config import RAIZ  # noqa: F401  (reexportado por comodidad)

# Tamanos de modelo de faster-whisper, del mas ligero al mas preciso.
MODELOS_WHISPER = ("tiny", "base", "small", "medium", "large-v3")

# large-v3 en int8_float16 ocupa ~1,6 GB de VRAM: cabe de sobra en una tarjeta de
# 6 GB y sigue dejando sitio al modelo de lenguaje. Para un corpus de
# investigacion en espanol la diferencia de calidad frente a `small` es grande,
# asi que se paga el rato extra por video.
MODELO_WHISPER_POR_DEFECTO = "large-v3"

MODELO_LLM_POR_DEFECTO = "qwen2.5:7b-instruct"
OLLAMA_POR_DEFECTO = "http://localhost:11434"

# Debajo de esto se considera que el video no tiene habla y no se manda al LLM.
MINIMO_PALABRAS = 10


@dataclass
class AjustesAnalisis:
    """Como transcribir y como clasificar en esta corrida."""

    # -- voz --------------------------------------------------------------
    modelo_whisper: str = MODELO_WHISPER_POR_DEFECTO
    device: str = "auto"                # "auto" | "cuda" | "cpu"
    compute_type_gpu: str = "int8_float16"
    compute_type_cpu: str = "int8"
    idioma: Optional[str] = None        # None = detectar; "es", "en", ...
    beam_size: int = 5
    # Los Shorts llevan musica y silencios, y ahi Whisper alucina frases
    # repetidas. El VAD es lo que impide que eso acabe dentro del dataset.
    vad: bool = True

    # -- lenguaje ---------------------------------------------------------
    modelo_llm: str = field(
        default_factory=lambda: os.getenv("OLLAMA_MODELO") or MODELO_LLM_POR_DEFECTO)
    ollama_url: str = field(
        default_factory=lambda: os.getenv("OLLAMA_URL") or OLLAMA_POR_DEFECTO)
    # Temperatura 0 y semilla fija: dos corridas sobre el mismo corpus dan el
    # mismo dataset, que es lo minimo exigible a un dato de investigacion.
    temperatura: float = 0.0
    semilla: int = 0
    timeout_llm: float = 180.0
    max_caracteres_prompt: int = 6000

    # -- alcance ----------------------------------------------------------
    retranscribir: bool = False
    reclasificar: bool = False
    clasificar: bool = True
    guardar_segmentos: bool = True

    def como_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


def registrar_dll_cuda() -> List[str]:
    """Hace visibles las DLL de CUDA que pip instala dentro del .venv.

    `requirements-gpu.txt` deja cublas64_12.dll y cudnn64_9.dll en
    site-packages/nvidia/*/bin, pero eso no esta en el PATH, asi que CTranslate2
    no las encuentra: el modelo llega a construirse en la GPU y revienta despues,
    al codificar el primer audio, con "Library cublas64_12.dll is not found".
    Aqui se registran esas carpetas antes de tocar el modelo.

    Devuelve las carpetas anadidas (vacio si no hay paquetes de NVIDIA).
    """
    if os.name != "nt":
        return []                       # en Linux los .so van por rpath
    import site

    anadidas = []
    raices = [Path(p) for p in site.getsitepackages()]
    raices.append(Path(sys.prefix) / "Lib" / "site-packages")
    vistas = set()
    for raiz in raices:
        for carpeta in sorted((raiz / "nvidia").glob("*/bin")):
            clave = str(carpeta).lower()
            if clave in vistas or not carpeta.is_dir():
                continue
            vistas.add(clave)
            try:
                os.add_dll_directory(str(carpeta))
            except OSError:
                continue
            # add_dll_directory basta para las cargas explicitas, pero cudnn se
            # carga desde dentro de cublas por nombre y ahi manda el PATH.
            os.environ["PATH"] = str(carpeta) + os.pathsep + os.environ.get("PATH", "")
            anadidas.append(str(carpeta))
    return anadidas


def carpeta_modelos_whisper() -> str:
    """Donde faster-whisper deja los pesos descargados.

    En el proyecto y no en el perfil del usuario, para que se vea lo que ocupa
    (large-v3 son ~1,5 GB) y se pueda borrar a mano. Fuera de `data/` a
    proposito: vaciar el corpus no debe obligar a bajar el modelo otra vez.
    """
    destino = RAIZ / "modelos"
    destino.mkdir(parents=True, exist_ok=True)
    # El proyecto vive en OneDrive, que no admite enlaces simbolicos; sin esto
    # huggingface_hub suelta un parrafo de aviso cada vez que se carga el modelo.
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    return str(destino)
