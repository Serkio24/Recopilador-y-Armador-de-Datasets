# -*- coding: utf-8 -*-
"""Verificacion barata de si un id de YouTube es realmente un Short.

youtube.com/shorts/<id> responde 200 cuando el video es un Short y redirige
(303) a /watch?v=<id> cuando no lo es. Es una peticion pequena, muchisimo mas
barata que descargar el video para descubrir que era horizontal.
"""

import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, List

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 12


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _abridor():
    op = urllib.request.build_opener(_SinRedirecciones)
    op.addheaders = [("User-Agent", UA), ("Accept-Language", "es,en;q=0.8")]
    return op


def es_short(video_id: str, abridor=None) -> bool:
    op = abridor or _abridor()
    try:
        resp = op.open("https://www.youtube.com/shorts/%s" % video_id, timeout=TIMEOUT)
        codigo = getattr(resp, "status", None) or resp.getcode()
        resp.close()
        return codigo == 200
    except urllib.error.HTTPError as exc:
        return exc.code == 200          # 303 -> es un video normal
    except Exception:
        return False                    # ante la duda, no lo damos por Short


def filtrar(video_ids: Iterable[str], hilos: int = 6) -> List[str]:
    """Devuelve, en el orden recibido, solo los ids que son Shorts."""
    ids = list(video_ids)
    if not ids:
        return []
    op = _abridor()
    with ThreadPoolExecutor(max_workers=max(1, hilos)) as ex:
        marcas = list(ex.map(lambda v: es_short(v, op), ids))
    return [vid for vid, ok in zip(ids, marcas) if ok]
