# -*- coding: utf-8 -*-
"""Pais declarado de un canal, via YouTube Data API v3 (requiere YOUTUBE_API_KEY).

Coste de cuota: channels.list = 1 unidad, y admite 50 canales por llamada.
Enriquecer 10.000 videos sale por unas 200 unidades de las 10.000 diarias.

Aviso sobre el dato: YouTube **no publica desde donde se subio un video**. Lo
que devuelve `snippet.country` es el pais que el dueno del canal declara en su
perfil: es opcional, muchos canales lo dejan en blanco, y no dice donde se
grabo ni desde donde se subio. De ahi que la columna se llame `pais_canal`.
"""

from typing import Callable, Dict, Iterable, List, Optional

from .api_source import ApiNoDisponible, disponible  # noqa: F401  (reexportados)

COSTE_CHANNELS = 1
TAM_LOTE = 50               # tope que admite channels.list en un solo id=


def paises(canal_ids: Iterable[str],
           settings,
           log: Optional[Callable[[str], None]] = None) -> Dict[str, str]:
    """Devuelve {canal_id: codigo ISO-3166 alfa-2}.

    Los canales que no declaran pais simplemente no salen en el diccionario.
    Si la API no esta disponible se lanza `ApiNoDisponible` para que el
    llamador siga sin pais en vez de abortar la recoleccion.
    """
    log = log or (lambda _m: None)
    ids: List[str] = sorted({c for c in canal_ids if c})
    if not ids:
        return {}

    if not settings.youtube_api_key:
        raise ApiNoDisponible("no hay YOUTUBE_API_KEY en el .env")
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError:
        raise ApiNoDisponible("falta google-api-python-client")

    encontrados: Dict[str, str] = {}
    unidades = 0
    try:
        youtube = build("youtube", "v3", developerKey=settings.youtube_api_key,
                        cache_discovery=False)
        for inicio in range(0, len(ids), TAM_LOTE):
            lote = ids[inicio:inicio + TAM_LOTE]
            resp = youtube.channels().list(
                part="snippet", id=",".join(lote), maxResults=TAM_LOTE
            ).execute()
            unidades += COSTE_CHANNELS

            for item in resp.get("items", []):
                pais = (item.get("snippet") or {}).get("country") or ""
                if pais:
                    encontrados[item.get("id")] = pais

    except HttpError as exc:
        # 403 tipico: cuota agotada o key sin permisos. Se devuelve lo ya
        # resuelto en vez de perderlo.
        raise ApiNoDisponible("HttpError %s" % getattr(exc, "status_code", exc))
    except ApiNoDisponible:
        raise
    except Exception as exc:
        raise ApiNoDisponible(str(exc))

    log("pais de canal: %d de %d canales lo declaran (%d unidades de cuota)"
        % (len(encontrados), len(ids), unidades))
    return encontrados
