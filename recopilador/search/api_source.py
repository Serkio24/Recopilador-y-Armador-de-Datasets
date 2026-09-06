# -*- coding: utf-8 -*-
"""Busqueda con YouTube Data API v3 (opcional, requiere YOUTUBE_API_KEY).

Coste de cuota: search.list = 100 unidades, videos.list = 1 unidad.
Con la cuota gratuita de 10.000 unidades/dia caben ~100 busquedas.
"""

import re
from typing import Callable, List, Optional, Set

from ..models import Candidato
from . import shorts_check

NOMBRE = "api"
COSTE_SEARCH = 100
COSTE_VIDEOS = 1

_ISO = re.compile(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


class ApiNoDisponible(Exception):
    """La API no se puede usar: sin key, sin libreria, o cuota agotada."""


def disponible(settings) -> bool:
    if not settings.youtube_api_key:
        return False
    try:
        import googleapiclient.discovery  # noqa: F401
    except ImportError:
        return False
    return True


def _segundos(iso: str) -> Optional[float]:
    """Convierte una duracion ISO-8601 de YouTube (PT1M5S) a segundos."""
    if not iso:
        return None
    m = _ISO.match(iso)
    if not m:
        return None
    d, h, mi, s = (int(g) if g else 0 for g in m.groups())
    return float(d * 86400 + h * 3600 + mi * 60 + s)


def buscar(tema: str,
           n: int,
           settings,
           excluir: Optional[Set[str]] = None,
           log: Optional[Callable[[str], None]] = None,
           cancel_event=None) -> List[Candidato]:
    excluir = set(excluir or ())
    log = log or (lambda _m: None)

    if not settings.youtube_api_key:
        raise ApiNoDisponible("no hay YOUTUBE_API_KEY en el .env")
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError:
        raise ApiNoDisponible("falta google-api-python-client")

    objetivo = max(n * 2, n + 10)
    unidades = 0
    candidatos: List[Candidato] = []
    vistos: Set[str] = set()

    try:
        youtube = build("youtube", "v3", developerKey=settings.youtube_api_key,
                        cache_discovery=False)
        token = None
        while len(candidatos) < objetivo:
            if cancel_event is not None and cancel_event.is_set():
                break

            resp = youtube.search().list(
                q=tema, part="id,snippet", type="video",
                videoDuration="short",          # < 4 min; el filtro fino va abajo
                maxResults=50, pageToken=token,
                relevanceLanguage="es", order="relevance",
            ).execute()
            unidades += COSTE_SEARCH

            ids, snippets = [], {}
            for item in resp.get("items", []):
                vid = (item.get("id") or {}).get("videoId")
                if not vid or vid in vistos or vid in excluir:
                    continue
                vistos.add(vid)
                ids.append(vid)
                snippets[vid] = item.get("snippet") or {}

            if ids:
                det = youtube.videos().list(
                    part="contentDetails,statistics", id=",".join(ids)
                ).execute()
                unidades += COSTE_VIDEOS
                for item in det.get("items", []):
                    vid = item.get("id")
                    dur = _segundos((item.get("contentDetails") or {}).get("duration"))
                    if dur is None or dur > settings.max_duration:
                        continue
                    sn = snippets.get(vid, {})
                    candidatos.append(Candidato(
                        video_id=vid,
                        titulo=sn.get("title") or "",
                        url="https://www.youtube.com/watch?v=%s" % vid,
                        duracion=dur,
                        canal=sn.get("channelTitle") or "",
                        origen=NOMBRE,
                    ))

            log("  API: %d candidatos acumulados (%d unidades de cuota)"
                % (len(candidatos), unidades))

            token = resp.get("nextPageToken")
            if not token:
                break

    except HttpError as exc:
        # 403 tipico: cuota agotada o key sin permisos -> que el llamador haga fallback
        raise ApiNoDisponible("HttpError %s" % getattr(exc, "status_code", exc))
    except ApiNoDisponible:
        raise
    except Exception as exc:
        raise ApiNoDisponible(str(exc))

    # videoDuration="short" son videos de menos de 4 minutos, no Shorts: hay
    # que verificarlos igual que en el backend de yt-dlp.
    if candidatos:
        confirmados = set(shorts_check.filtrar([c.video_id for c in candidatos]))
        candidatos = [c for c in candidatos if c.video_id in confirmados]

    log("busqueda API terminada: %d Shorts, %d unidades de cuota gastadas"
        % (len(candidatos), unidades))
    return candidatos
