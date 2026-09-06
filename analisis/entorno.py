# -*- coding: utf-8 -*-
"""Comprobaciones previas al analisis.

Mismo criterio que `recopilador.entorno`: si algo falta, la corrida no falla a
mitad de un lote de doscientos videos con una traza incomprensible, sino que se
dice antes y con el comando exacto que lo arregla.
"""

from typing import List, Optional

from .config import AjustesAnalisis

RECETA_WHISPER = (
    "Instálalo con:\n"
    "    .venv\\Scripts\\python.exe -m pip install -r requirements.txt")

RECETA_GPU = (
    "Para usar la tarjeta NVIDIA hacen falta las DLL de cuBLAS y cuDNN. No es "
    "necesario instalar el CUDA Toolkit; basta con:\n"
    "    .venv\\Scripts\\python.exe -m pip install -r requirements-gpu.txt")

RECETA_OLLAMA = (
    "Instálalo y descarga el modelo con:\n"
    "    winget install --id Ollama.Ollama -e\n"
    "    ollama pull %s\n"
    "Ollama queda corriendo en segundo plano; si acabas de instalarlo, ábrelo "
    "una vez desde el menú de inicio.")


def hay_faster_whisper() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def hay_gpu() -> bool:
    """True si CTranslate2 ve una tarjeta utilizable.

    Es una consulta barata: no carga ningun modelo, solo pregunta al runtime.
    """
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def problemas(ajustes: Optional[AjustesAnalisis] = None,
              clasificar: bool = True) -> List[str]:
    """Fallos que impiden analizar, en lenguaje llano. Lista vacia = todo bien."""
    ajustes = ajustes or AjustesAnalisis()
    fallos = []

    if not hay_faster_whisper():
        fallos.append("Falta faster-whisper, que es lo que transcribe.\n"
                      + RECETA_WHISPER)

    if clasificar:
        from .clasificador import ErrorOllama, modelos_disponibles
        try:
            instalados = modelos_disponibles(ajustes.ollama_url)
        except ErrorOllama as exc:
            fallos.append("%s\n%s" % (exc, RECETA_OLLAMA % ajustes.modelo_llm))
        else:
            # Ollama acepta "qwen2.5:7b-instruct" y lista "qwen2.5:7b-instruct";
            # sin etiqueta explicita, lista ":latest".
            pedido = ajustes.modelo_llm
            if not any(m == pedido or m.split(":")[0] == pedido.split(":")[0]
                       for m in instalados):
                fallos.append(
                    "Ollama funciona pero no tiene el modelo «%s».\n"
                    "Descárgalo con:\n    ollama pull %s\n"
                    "Modelos disponibles ahora mismo: %s"
                    % (pedido, pedido, ", ".join(instalados) or "ninguno"))

    return fallos


def avisos(ajustes: Optional[AjustesAnalisis] = None) -> List[str]:
    """Cosas que no impiden analizar pero conviene saber antes de empezar."""
    ajustes = ajustes or AjustesAnalisis()
    if ajustes.device != "cpu" and hay_faster_whisper() and not hay_gpu():
        return ["No se detecta GPU utilizable: la transcripción irá por CPU y "
                "tardará del orden de diez veces más.\n" + RECETA_GPU]
    return []
