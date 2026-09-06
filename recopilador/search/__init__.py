# -*- coding: utf-8 -*-
"""Seleccion de backend de busqueda: API oficial si hay key, yt-dlp si no."""

from typing import Callable, List, Optional, Set, Tuple

from ..models import Candidato
from . import api_source, ytdlp_source


def buscar(tema: str,
           n: int,
           settings,
           excluir: Optional[Set[str]] = None,
           log: Optional[Callable[[str], None]] = None,
           cancel_event=None,
           forzar_backend: Optional[str] = None) -> Tuple[List[Candidato], str]:
    """Devuelve (candidatos, nombre_del_backend_usado).

    Con YOUTUBE_API_KEY presente se usa la API de YouTube; si falla por cuota,
    permisos o falta de libreria, cae automaticamente a yt-dlp.
    """
    log = log or (lambda _m: None)
    usar_api = (forzar_backend == api_source.NOMBRE) or (
        forzar_backend is None and api_source.disponible(settings)
    )

    if usar_api:
        log("backend de busqueda: YouTube Data API v3")
        try:
            cands = api_source.buscar(tema, n, settings, excluir, log, cancel_event)
            if cands:
                return cands, api_source.NOMBRE
            log("la API no devolvio candidatos; se reintenta con yt-dlp")
        except api_source.ApiNoDisponible as exc:
            log("API no utilizable (%s); se usa yt-dlp" % exc)
    else:
        log("backend de busqueda: yt-dlp (sin API key)")

    cands = ytdlp_source.buscar(tema, n, settings, excluir, log, cancel_event)
    return cands, ytdlp_source.NOMBRE
