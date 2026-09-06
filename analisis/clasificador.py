# -*- coding: utf-8 -*-
"""Clasificacion con un modelo de lenguaje local servido por Ollama.

Se habla con Ollama por HTTP usando `urllib` de la biblioteca estandar: no hace
falta anadir una dependencia para mandar dos peticiones JSON, y asi
`requirements.txt` sigue tan corto como estaba.

La clave del modulo es que el JSON Schema que restringe la respuesta se genera
desde el `EsquemaDataset` que definio el usuario. El modelo no puede inventarse
columnas ni salirse de las opciones, de modo que no hay que reintentar por
formato ni parsear texto libre.
"""

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .config import AjustesAnalisis, MINIMO_PALABRAS
from .models import Clasificacion, EsquemaDataset

SISTEMA = (
    "Eres un anotador de un corpus de investigación. Recibes la ficha de un "
    "vídeo corto (título con sus hashtags, canal, tema de búsqueda) y su "
    "transcripción, y devuelves únicamente un objeto JSON con los campos "
    "pedidos.\n"
    "Reglas:\n"
    "- Puedes basarte tanto en la transcripción como en el título y los "
    "hashtags. Muchos vídeos no tienen voz y su título es la única "
    "información disponible.\n"
    "- No inventes nada que no esté ni en la transcripción ni en la ficha. Si "
    "un dato no se puede determinar, elige la opción más neutra o genérica "
    "disponible.\n"
    "- En «%s» declara en qué te has apoyado realmente para rellenar los "
    "campos.\n"
    "- No añadas explicaciones ni texto fuera del JSON."
)

# Campo reservado: lo pide el clasificador, no el usuario, y viaja al CSV en su
# propia columna. Al mezclar habla y metadatos como evidencia, saber de cual
# salio cada fila deja de ser un detalle y pasa a ser parte del dato.
CAMPO_FUENTE = "_fuente"

FUENTES = ["transcripción", "título y hashtags", "ambos"]


class ErrorOllama(Exception):
    """Ollama no responde o responde algo que no se puede usar."""


# -- transporte ----------------------------------------------------------
def _pedir(url: str, cuerpo: Optional[dict], timeout: float) -> dict:
    datos = None if cuerpo is None else json.dumps(cuerpo).encode("utf-8")
    peticion = urllib.request.Request(
        url, data=datos, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            return json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detalle = ""
        try:
            detalle = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise ErrorOllama("Ollama respondió %s: %s" % (exc.code, detalle))
    except urllib.error.URLError as exc:
        raise ErrorOllama(
            "no se puede contactar con Ollama en %s (%s). Comprueba que está "
            "instalado y en marcha." % (url, exc.reason))
    except ValueError as exc:
        raise ErrorOllama("Ollama devolvió algo que no es JSON: %s" % exc)


def modelos_disponibles(ollama_url: str, timeout: float = 10.0) -> List[str]:
    """Modelos que Ollama tiene descargados. Lanza ErrorOllama si no responde."""
    datos = _pedir(ollama_url.rstrip("/") + "/api/tags", None, timeout)
    return sorted(m.get("name", "") for m in datos.get("models", []) if m.get("name"))


# -- prompt --------------------------------------------------------------
def _mensaje(fila, transcripcion: str, esquema: EsquemaDataset,
             max_caracteres: int) -> str:
    """Ficha del video que se manda al modelo.

    El titulo lleva los hashtags dentro, que en un Short suelen decir mas del
    contenido que el propio audio.
    """
    texto = (transcripcion or "").strip()
    if len(texto) > max_caracteres:
        texto = texto[:max_caracteres] + " […]"
    # Se dice explicitamente en vez de mandar un hueco: un bloque vacio invita a
    # rellenarlo, mientras que la frase le dice que se apoye en el titulo.
    if len(texto.split()) < MINIMO_PALABRAS:
        texto = ("(el vídeo no tiene voz o es inaudible; guíate por el título "
                 "y los hashtags)" + (("\nFragmento suelto: " + texto)
                                      if texto else ""))

    def campo(clave, valor):
        return "%s: %s" % (clave, valor) if valor not in (None, "") else None

    cabecera = [c for c in (
        campo("Título", fila["titulo"]),
        campo("Canal", fila["canal"]),
        campo("Tema de búsqueda", fila["tema"]),
        campo("Duración (s)", "%.0f" % fila["duracion"] if fila["duracion"] else None),
    ) if c]

    columnas = "\n".join(
        "- %s (%s): %s%s" % (
            c.nombre, c.tipo, c.descripcion or "sin descripción",
            (" Opciones: %s." % ", ".join(c.opciones)) if c.opciones else "")
        for c in esquema.columnas)

    return ("%s\n\nTranscripción:\n\"\"\"\n%s\n\"\"\"\n\n"
            "Rellena estos campos:\n%s"
            % ("\n".join(cabecera), texto, columnas))


# -- clasificacion --------------------------------------------------------
def _esquema_con_fuente(esquema: EsquemaDataset) -> dict:
    """JSON Schema del usuario mas el campo reservado de procedencia."""
    js = esquema.json_schema()
    js["properties"][CAMPO_FUENTE] = {
        "type": "string", "enum": list(FUENTES),
        "description": "En qué te has apoyado para rellenar los campos.",
    }
    js["required"] = list(js["required"]) + [CAMPO_FUENTE]
    return js


def clasificar(fila, transcripcion: str, esquema: EsquemaDataset,
               ajustes: AjustesAnalisis) -> Clasificacion:
    """Clasifica un video a partir de su transcripcion, titulo y hashtags.

    Se clasifica tambien lo que no tiene voz: en un corpus de Shorts la mayoria
    son gameplay sin habla y su titulo es la unica informacion que hay. Lo que
    impide que eso se confunda con una etiqueta deducida del audio es el campo
    reservado de procedencia, que viaja al CSV en su propia columna.
    """
    video_id = fila["video_id"]

    cuerpo = {
        "model": ajustes.modelo_llm,
        "messages": [
            {"role": "system", "content": SISTEMA % CAMPO_FUENTE},
            {"role": "user",
             "content": _mensaje(fila, transcripcion, esquema,
                                 ajustes.max_caracteres_prompt)},
        ],
        # Ollama restringe la generacion a este esquema, asi que la respuesta ya
        # llega valida y con exactamente las columnas pedidas.
        "format": _esquema_con_fuente(esquema),
        "stream": False,
        "options": {"temperature": ajustes.temperatura, "seed": ajustes.semilla},
    }

    datos = _pedir(ajustes.ollama_url.rstrip("/") + "/api/chat", cuerpo,
                   ajustes.timeout_llm)
    contenido = (datos.get("message") or {}).get("content") or ""
    try:
        campos: Dict[str, Any] = json.loads(contenido)
    except ValueError:
        raise ErrorOllama(
            "el modelo %s no devolvió JSON válido. Si es antiguo puede no "
            "admitir salida estructurada; prueba con qwen2.5:7b-instruct."
            % ajustes.modelo_llm)

    fuente = str(campos.pop(CAMPO_FUENTE, "") or "").strip()
    if fuente not in FUENTES:
        fuente = ""
    return Clasificacion(video_id=video_id, esquema=esquema.nombre,
                         campos=esquema.normalizar(campos),
                         modelo=ajustes.modelo_llm, fuente=fuente)
