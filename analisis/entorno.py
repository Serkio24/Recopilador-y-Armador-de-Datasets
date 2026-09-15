# -*- coding: utf-8 -*-
"""Comprobaciones previas al analisis.

Mismo criterio que `recopilador.entorno`: si algo falta, la corrida no falla a
mitad de un lote de doscientos videos con una traza incomprensible, sino que se
dice antes y con el comando exacto que lo arregla. El comando lo pone
`recopilador.plataforma`, que sabe en que sistema estamos.
"""

from typing import List, Optional

from recopilador.plataforma import ES_MAC, INSTALAR_OLLAMA, PYTHON_VENV

from .config import AjustesAnalisis

RECETA_WHISPER = (
    "Instálalo con:\n"
    "    %s -m pip install -r requirements.txt" % PYTHON_VENV)

# En Windows/Linux con tarjeta NVIDIA la GPU es cuestión de instalar dos wheels.
# En un Mac no hay nada que instalar: CTranslate2, el motor de faster-whisper,
# solo tiene backend CUDA --no usa Metal ni MPS-- y las wheels de NVIDIA ni
# siquiera existen para macOS. Ahí la única palanca es el tamaño del modelo.
if ES_MAC:
    RECETA_GPU = (
        "En un Mac no hay forma de acelerarlo: CTranslate2, el motor de "
        "faster-whisper, solo sabe usar CUDA, y no existe versión para Metal. "
        "No instales requirements-gpu.txt: esas wheels son de NVIDIA y no hay "
        "ninguna para macOS.\n"
        "Si el lote se hace largo, la única palanca es bajar el tamaño del "
        "modelo (medium, small), teniendo en cuenta que eso deja el corpus sin "
        "comparar con lo transcrito con large-v3.")
else:
    RECETA_GPU = (
        "Para usar la tarjeta NVIDIA hacen falta las DLL de cuBLAS y cuDNN. No es "
        "necesario instalar el CUDA Toolkit; basta con:\n"
        "    %s -m pip install -r requirements-gpu.txt" % PYTHON_VENV)

RECETA_OLLAMA = (
    "Instálalo y descarga el modelo con:\n"
    "    " + INSTALAR_OLLAMA + "\n"
    "    ollama pull %s\n"
    "Ollama queda corriendo en segundo plano; si acabas de instalarlo, ábrelo "
    "una vez desde " + ("Launchpad." if ES_MAC else "el menú de inicio."))


def hay_faster_whisper() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def hay_gpu() -> bool:
    """True si CTranslate2 ve una tarjeta utilizable.

    Es una consulta barata: no carga ningun modelo, solo pregunta al runtime. En
    un Mac devuelve False siempre, porque CTranslate2 no trae mas backend que
    CUDA.
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
        if ES_MAC:
            return ["La transcripción irá por CPU: en un Mac no hay otra "
                    "opción, y un Short pasa de segundos a cerca de un "
                    "minuto.\n" + RECETA_GPU]
        return ["No se detecta GPU utilizable: la transcripción irá por CPU y "
                "tardará del orden de diez veces más.\n" + RECETA_GPU]
    return []
