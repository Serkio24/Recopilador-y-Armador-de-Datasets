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

    Lo elige `settings.buscador` ("ytdlp" | "api" | "auto"), no la mera
    presencia de la key: esta hace falta tambien para el pais del canal, y
    antes ponerla en el .env cambiaba el buscador de paso, limitando el
    descubrimiento a las ~100 busquedas que dan 10.000 unidades de cuota.
    Con la API elegida, si falla por cuota, permisos o falta de libreria, cae
    automaticamente a yt-dlp.
    """
    log = log or (lambda _m: None)
    preferencia = (getattr(settings, "buscador", "ytdlp") or "ytdlp").lower()
    if forzar_backend is not None:
        usar_api = forzar_backend == api_source.NOMBRE
    elif preferencia == api_source.NOMBRE:
        usar_api = True
    elif preferencia == "auto":
        usar_api = api_source.disponible(settings)
    else:
        usar_api = False

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
