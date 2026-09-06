# -*- coding: utf-8 -*-
"""Estructuras de datos de la etapa de analisis.

La pieza central es `EsquemaDataset`: la definicion, hecha por el usuario desde
la interfaz, de que columnas tiene que tener el dataset. De ella salen tanto el
JSON Schema que restringe al modelo de lenguaje como las cabeceras del CSV, de
modo que las dos cosas no pueden descuadrarse.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# -- tipos de columna ----------------------------------------------------
TIPO_CATEGORIA = "categoria"          # exactamente una de las opciones
TIPO_MULTIETIQUETA = "multietiqueta"  # cero o mas de las opciones
TIPO_BOOLEANO = "booleano"
TIPO_NUMERO = "numero"
TIPO_TEXTO = "texto"

TIPOS = (TIPO_CATEGORIA, TIPO_MULTIETIQUETA, TIPO_BOOLEANO, TIPO_NUMERO,
         TIPO_TEXTO)

CON_OPCIONES = (TIPO_CATEGORIA, TIPO_MULTIETIQUETA)

SEPARADOR_MULTI = "|"       # como se serializa una multietiqueta en el CSV


class Cancelado(Exception):
    """El usuario pidio parar.

    Es la gemela de `recopilador.downloader.Cancelado`, pero se declara aqui a
    proposito: importar el descargador solo para reutilizar una excepcion
    arrastraria yt-dlp a una etapa que no lo necesita.
    """


@dataclass
class Columna:
    """Una columna del dataset, tal y como la define el usuario."""

    nombre: str
    descripcion: str = ""
    tipo: str = TIPO_CATEGORIA
    opciones: List[str] = field(default_factory=list)
    minimo: Optional[float] = None
    maximo: Optional[float] = None

    def __post_init__(self):
        self.nombre = re.sub(r"\s+", " ", (self.nombre or "")).strip()
        self.descripcion = (self.descripcion or "").strip()
        if self.tipo not in TIPOS:
            self.tipo = TIPO_TEXTO
        self.opciones = [re.sub(r"\s+", " ", str(o)).strip()
                         for o in (self.opciones or []) if str(o).strip()]

    # -- validacion ------------------------------------------------------
    def problemas(self) -> List[str]:
        fallos = []
        if not self.nombre:
            fallos.append("Hay una columna sin nombre.")
        if self.tipo in CON_OPCIONES and len(self.opciones) < 2:
            fallos.append("La columna «%s» es de tipo %s y necesita al menos "
                          "dos opciones." % (self.nombre, self.tipo))
        if len(set(self.opciones)) != len(self.opciones):
            fallos.append("La columna «%s» tiene opciones repetidas." % self.nombre)
        if (self.tipo == TIPO_NUMERO and self.minimo is not None
                and self.maximo is not None and self.minimo > self.maximo):
            fallos.append("En «%s» el mínimo es mayor que el máximo." % self.nombre)
        return fallos

    # -- contrato con el modelo -------------------------------------------
    def json_schema(self) -> dict:
        """Fragmento de JSON Schema que describe esta columna.

        La descripcion viaja dentro: es lo unico que el modelo tiene para saber
        que se espera en la columna, asi que forma parte del contrato y no es un
        comentario decorativo.
        """
        if self.tipo == TIPO_CATEGORIA:
            esquema = {"type": "string", "enum": list(self.opciones)}
        elif self.tipo == TIPO_MULTIETIQUETA:
            esquema = {"type": "array",
                       "items": {"type": "string", "enum": list(self.opciones)}}
        elif self.tipo == TIPO_BOOLEANO:
            esquema = {"type": "boolean"}
        elif self.tipo == TIPO_NUMERO:
            esquema = {"type": "number"}
            if self.minimo is not None:
                esquema["minimum"] = self.minimo
            if self.maximo is not None:
                esquema["maximum"] = self.maximo
        else:
            esquema = {"type": "string"}
        if self.descripcion:
            esquema["description"] = self.descripcion
        return esquema

    def normalizar(self, valor: Any) -> Any:
        """Ajusta al tipo declarado lo que haya devuelto el modelo.

        Ollama restringe la generacion al JSON Schema, asi que casi nunca hay
        nada que corregir; cuesta poco y evita que otro modelo, o una version
        vieja sin salida estructurada, cuele texto donde va un numero.
        """
        if valor is None:
            return None
        if self.tipo == TIPO_MULTIETIQUETA:
            if isinstance(valor, str):
                valor = [v.strip() for v in valor.split(SEPARADOR_MULTI)]
            if not isinstance(valor, (list, tuple)):
                return None
            return [v for v in (str(x).strip() for x in valor)
                    if v in self.opciones]
        if self.tipo == TIPO_CATEGORIA:
            texto = str(valor).strip()
            return texto if texto in self.opciones else None
        if self.tipo == TIPO_BOOLEANO:
            if isinstance(valor, bool):
                return valor
            return str(valor).strip().lower() in ("true", "si", "sí", "1", "yes")
        if self.tipo == TIPO_NUMERO:
            try:
                numero = float(valor)
            except (TypeError, ValueError):
                return None
            if self.minimo is not None:
                numero = max(numero, self.minimo)
            if self.maximo is not None:
                numero = min(numero, self.maximo)
            return numero
        return str(valor).strip()

    def para_csv(self, valor: Any) -> str:
        if valor is None:
            return ""
        if self.tipo == TIPO_MULTIETIQUETA:
            return SEPARADOR_MULTI.join(valor) if isinstance(valor, list) else ""
        if self.tipo == TIPO_BOOLEANO:
            return "si" if valor else "no"
        if self.tipo == TIPO_NUMERO and isinstance(valor, float):
            return "%g" % valor
        return str(valor)

    def como_dict(self) -> dict:
        return asdict(self)


@dataclass
class EsquemaDataset:
    """Conjunto de columnas con nombre, guardable y reutilizable."""

    nombre: str = "general"
    columnas: List[Columna] = field(default_factory=list)

    # -- validacion ------------------------------------------------------
    def problemas(self) -> List[str]:
        fallos = []
        if not (self.nombre or "").strip():
            fallos.append("El esquema necesita un nombre.")
        if not self.columnas:
            fallos.append("El esquema no tiene ninguna columna.")
        nombres = [c.nombre for c in self.columnas]
        repetidos = sorted(set(n for n in nombres if n and nombres.count(n) > 1))
        for r in repetidos:
            fallos.append("La columna «%s» está repetida." % r)
        # Los nombres con guion bajo delante los reserva el clasificador para
        # sus propios campos (ahora mismo `_fuente`); si el usuario define uno
        # igual, uno pisaria al otro sin avisar.
        for n in nombres:
            if n.startswith("_"):
                fallos.append("El nombre «%s» empieza por guion bajo, que está "
                              "reservado. Usa otro." % n)
        for c in self.columnas:
            fallos.extend(c.problemas())
        return fallos

    # -- contrato con el modelo -------------------------------------------
    def json_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {c.nombre: c.json_schema() for c in self.columnas},
            # Todas obligatorias: una columna ausente dejaria filas del dataset
            # a medias sin que nada lo avisara.
            "required": [c.nombre for c in self.columnas],
        }

    def normalizar(self, campos: Dict[str, Any]) -> Dict[str, Any]:
        campos = campos or {}
        return {c.nombre: c.normalizar(campos.get(c.nombre))
                for c in self.columnas}

    # -- persistencia -----------------------------------------------------
    def como_json(self) -> str:
        return json.dumps(
            {"nombre": self.nombre,
             "columnas": [c.como_dict() for c in self.columnas]},
            ensure_ascii=False, indent=2)

    @classmethod
    def desde_json(cls, texto: str) -> "EsquemaDataset":
        d = json.loads(texto)
        return cls(nombre=d.get("nombre") or "general",
                   columnas=[Columna(**c) for c in d.get("columnas", [])])


def esquema_por_defecto() -> EsquemaDataset:
    """Un esquema de arranque, para que la pestaña no abra en blanco.

    Las columnas son genericas a proposito: sirven para recorrer el flujo entero
    de punta a punta y se sustituyen desde la interfaz por las de la
    investigacion real.
    """
    return EsquemaDataset(nombre="general", columnas=[
        Columna("tematica", "Tema principal del que trata el video.",
                TIPO_CATEGORIA,
                ["educativo", "entretenimiento", "noticias", "comercial",
                 "personal", "musica", "otro"]),
        Columna("idioma_hablado", "Idioma en el que habla la persona.",
                TIPO_CATEGORIA, ["español", "ingles", "otro", "sin habla"]),
        Columna("tono", "Tono predominante del discurso.", TIPO_CATEGORIA,
                ["informativo", "humoristico", "critico", "emotivo", "neutro"]),
        Columna("menciona_producto",
                "Indica si se promociona o menciona algún producto o marca.",
                TIPO_BOOLEANO),
        Columna("resumen", "Resumen del contenido del video en una sola frase.",
                TIPO_TEXTO),
    ])


@dataclass
class Transcripcion:
    """Lo que devuelve el modelo de voz para un video."""

    video_id: str
    texto: str = ""
    idioma: str = ""
    prob_idioma: Optional[float] = None
    n_segmentos: int = 0
    duracion_audio: Optional[float] = None
    modelo: str = ""
    segundos: float = 0.0
    segmentos: List[tuple] = field(default_factory=list)   # (inicio, fin, texto)

    @property
    def n_palabras(self) -> int:
        return len(self.texto.split())


@dataclass
class Clasificacion:
    """Lo que devuelve el modelo de lenguaje para un video."""

    video_id: str
    esquema: str = ""
    campos: Dict[str, Any] = field(default_factory=dict)
    modelo: str = ""
    fuente: str = ""            # en que se apoyo: habla, titulo, o ambos
    error: str = ""


@dataclass
class ResumenAnalisis:
    """Cifras finales de una corrida de analisis."""

    seleccionados: int = 0
    transcritos: int = 0
    clasificados: int = 0
    ya_estaban: int = 0
    sin_habla: int = 0
    errores: int = 0
    segundos: float = 0.0
    cancelado: bool = False
