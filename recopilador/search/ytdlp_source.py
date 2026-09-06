# -*- coding: utf-8 -*-
"""Busqueda de Shorts con yt-dlp, sin API key.

La busqueda de texto de YouTube (/results) practicamente no devuelve Shorts:
se comprobo que ni con los filtros `sp` de tipo o duracion aparecen. Los Shorts
viven en superficies propias, y de ahi salen los candidatos:

1. Paginas de hashtag: youtube.com/hashtag/<etiqueta>/shorts -> 100% Shorts,
   y tematicos por construccion. Es la fuente principal.
2. Pestanas /shorts de los canales que aparecen al buscar el tema en texto.
   Tambien son 100% Shorts, y el canal aporta el tema.
3. Los propios resultados de texto, verificando uno a uno contra
   youtube.com/shorts/<id>, que solo responde 200 para Shorts de verdad.

Las dos primeras fuentes no traen duracion; el filtro fino lo aplica el
descargador sobre la ficha, antes de bajar un solo byte.
"""

import unicodedata
import urllib.parse
from typing import Callable, List, Optional, Set

from ..models import Candidato
from . import shorts_check

NOMBRE = "ytdlp"

TOPE_BUSQUEDA_TEXTO = 60
SHORTS_POR_HASHTAG = 60
SHORTS_POR_CANAL = 12          # tope bajo: da variedad en vez de vaciar un canal
MAX_CANALES = 10
VACIAS = set("de del la el los las en y con para por un una al lo se su sus que".split())


def _sin_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _hashtags(tema: str) -> List[str]:
    """Etiquetas a probar, de la mas especifica a la mas general."""
    limpio = _sin_acentos(tema).lower()
    palabras = [p for p in "".join(c if c.isalnum() else " " for c in limpio).split()
                if p not in VACIAS and len(p) > 2]
    if not palabras:
        return []
    etiquetas = ["".join(palabras)]
    for p in palabras:
        if p not in etiquetas:
            etiquetas.append(p)
    return etiquetas


def _plano(url: str, tope: Optional[int] = None) -> List[dict]:
    from yt_dlp import YoutubeDL

    opciones = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "ignoreerrors": True,
    }
    if tope:
        opciones["playlistend"] = tope
    with YoutubeDL(opciones) as ydl:
        info = ydl.extract_info(url, download=False)
    return [e for e in ((info or {}).get("entries") or []) if e and e.get("id")]


def _candidato(entrada: dict) -> Candidato:
    vid = entrada["id"]
    return Candidato(
        video_id=vid,
        titulo=entrada.get("title") or "",
        url="https://www.youtube.com/shorts/%s" % vid,
        duracion=entrada.get("duration"),
        canal=entrada.get("channel") or entrada.get("uploader") or "",
        origen=NOMBRE,
    )


class _Acumulador(object):
    """Junta candidatos evitando que un solo canal cope el corpus.

    Lo que excede el cupo de su canal no se tira: va a una reserva con la que
    se completa al final si las fuentes no dieron para el objetivo.
    """

    def __init__(self, objetivo, excluir, max_por_canal):
        self.objetivo = objetivo
        self.excluir = excluir
        self.max_por_canal = max_por_canal
        self.vistos = set()
        self.items = []
        self.reserva = []
        self.por_canal = {}

    def lleno(self) -> bool:
        return len(self.items) >= self.objetivo

    @staticmethod
    def _canal(entrada) -> str:
        return (entrada.get("channel_id") or entrada.get("channel")
                or entrada.get("uploader") or "?")

    def agregar(self, entradas, tope=None) -> int:
        nuevos = 0
        for e in entradas:
            if self.lleno() or (tope is not None and nuevos >= tope):
                break
            vid = e["id"]
            if vid in self.vistos or vid in self.excluir:
                continue
            self.vistos.add(vid)
            canal = self._canal(e)
            if self.por_canal.get(canal, 0) >= self.max_por_canal:
                self.reserva.append(e)
                continue
            self.por_canal[canal] = self.por_canal.get(canal, 0) + 1
            self.items.append(_candidato(e))
            nuevos += 1
        return nuevos

    def completar_con_reserva(self) -> int:
        nuevos = 0
        while self.reserva and not self.lleno():
            self.items.append(_candidato(self.reserva.pop(0)))
            nuevos += 1
        return nuevos


def _cerrar(acc, log):
    """Completa con la reserva si las fuentes no dieron para el objetivo."""
    extra = acc.completar_con_reserva()
    if extra:
        log("  se recuperan %d candidatos de canales ya representados" % extra)
    return acc.items


def buscar(tema: str,
           n: int,
           settings,
           excluir: Optional[Set[str]] = None,
           log: Optional[Callable[[str], None]] = None,
           cancel_event=None) -> List[Candidato]:
    """Devuelve hasta ~2n Shorts sobre el tema."""
    log = log or (lambda _m: None)
    cancelado = lambda: cancel_event is not None and cancel_event.is_set()
    objetivo = max(n * 2, n + 10)
    acc = _Acumulador(objetivo, set(excluir or ()),
                      max_por_canal=max(2, objetivo // 4))

    # -- 1) paginas de hashtag ------------------------------------------
    for etiqueta in _hashtags(tema):
        if cancelado() or acc.lleno():
            break
        url = "https://www.youtube.com/hashtag/%s/shorts" % urllib.parse.quote(etiqueta)
        try:
            entradas = _plano(url, SHORTS_POR_HASHTAG)
        except Exception as exc:
            log("  #%s: %s" % (etiqueta, str(exc)[:80]))
            continue
        nuevos = acc.agregar(entradas)
        log("#%s -> %d Shorts (total %d)" % (etiqueta, nuevos, len(acc.items)))

    if acc.lleno() or cancelado():
        return _cerrar(acc, log)

    # -- 2) pestanas /shorts de los canales del tema ---------------------
    log("faltan candidatos; se buscan canales del tema")
    canales = []
    try:
        for e in _plano("ytsearch%d:%s" % (TOPE_BUSQUEDA_TEXTO, tema)):
            url_canal = e.get("channel_url")
            if url_canal and url_canal not in canales:
                canales.append(url_canal)
    except Exception as exc:
        log("  la busqueda de texto fallo: %s" % str(exc)[:80])

    for url_canal in canales[:MAX_CANALES]:
        if cancelado() or acc.lleno():
            break
        try:
            entradas = _plano(url_canal.rstrip("/") + "/shorts", SHORTS_POR_CANAL)
        except Exception as exc:
            log("  %s: %s" % (url_canal.rsplit("/", 1)[-1], str(exc)[:60]))
            continue
        nuevos = acc.agregar(entradas, tope=SHORTS_POR_CANAL)
        if nuevos:
            log("  canal %s -> %d Shorts (total %d)"
                % (url_canal.rsplit("/", 1)[-1], nuevos, len(acc.items)))

    if acc.lleno() or cancelado():
        return _cerrar(acc, log)

    # -- 3) resultados de texto, verificados uno a uno -------------------
    log("faltan candidatos; se verifican los resultados de texto")
    try:
        entradas = _plano("ytsearch%d:%s" % (TOPE_BUSQUEDA_TEXTO, tema))
    except Exception as exc:
        log("  la busqueda de texto fallo: %s" % str(exc)[:80])
        return acc.items

    posibles = {e["id"]: e for e in entradas
                if e["id"] not in acc.vistos and e["id"] not in acc.excluir}
    if posibles:
        confirmados = shorts_check.filtrar(list(posibles.keys()))
        nuevos = acc.agregar([posibles[v] for v in confirmados])
        log("  %d de %d resultados de texto son Shorts (total %d)"
            % (nuevos, len(posibles), len(acc.items)))

    return _cerrar(acc, log)
