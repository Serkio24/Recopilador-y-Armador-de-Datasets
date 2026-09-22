# -*- coding: utf-8 -*-
"""Rellena `publicado_en`, `canal_id` y `pais_canal` en videos ya descargados.

La fecha en ISO no la toca este script: la resuelve la migracion de
`recopilador.store.Store._migrar`, que es puro string y no necesita red.

Lo que si necesita red es la hora exacta de publicacion de los videos cuya
ficha `.info.json` ya no esta en disco (el barrido de huerfanas las va
borrando). Para esos se vuelve a pedir la ficha con `skip_download=True`, que
no descarga el video.

Uso:
    python -m scripts.backfill_metadatos            # todo
    python -m scripts.backfill_metadatos --sin-red  # solo fichas locales
"""

import argparse
import io
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from recopilador.config import Settings                  # noqa: E402
from recopilador.downloader import fecha_iso, momento_iso  # noqa: E402
from recopilador.search import canal_info                # noqa: E402
from recopilador.store import Store                      # noqa: E402


def _de_ficha(ruta):
    """(canal_id, publicado_en, fecha_subida) de un .info.json ya guardado."""
    try:
        with io.open(str(ruta), encoding="utf-8") as f:
            d = json.load(f)
    except (ValueError, OSError):
        return None
    return (d.get("channel_id") or "",
            momento_iso(d.get("timestamp")),
            fecha_iso(d.get("upload_date")))


def _de_youtube(video_id, settings):
    """Lo mismo, volviendo a pedir la ficha a YouTube sin bajar el video."""
    from yt_dlp import YoutubeDL

    opciones = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    if settings.ffmpeg_dir:
        opciones["ffmpeg_location"] = settings.ffmpeg_dir
    try:
        with YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(
                "https://www.youtube.com/watch?v=%s" % video_id, download=False)
    except Exception:
        return None
    if not info:
        return None
    return (info.get("channel_id") or "",
            momento_iso(info.get("timestamp")),
            fecha_iso(info.get("upload_date")))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--carpeta", help="carpeta de datos (por defecto ./data)")
    p.add_argument("--sin-red", action="store_true",
                   help="solo leer los .info.json locales, sin consultar YouTube")
    args = p.parse_args(argv)

    settings = Settings(data_dir=Path(args.carpeta) if args.carpeta else RAIZ / "data")
    store = Store(settings.db_path)          # al abrir ya corre la migracion

    try:
        filas = store.listar(solo_ok=True)
        pendientes = [f for f in filas
                      if not (f["canal_id"] or "") or not (f["publicado_en"] or "")]
        print("%d videos indexados, %d sin hora exacta o sin canal_id"
              % (len(filas), len(pendientes)))

        de_disco = de_red = 0
        for fila in pendientes:
            vid = fila["video_id"]
            datos = None

            ficha = settings.meta_dir / ("%s.info.json" % vid)
            if ficha.exists():
                datos = _de_ficha(ficha)
                if datos:
                    de_disco += 1

            if datos is None and not args.sin_red:
                datos = _de_youtube(vid, settings)
                if datos:
                    de_red += 1

            if datos is None:
                print("  %s: no se pudo resolver" % vid)
                continue

            canal_id, publicado_en, fecha = datos
            store.actualizar_campos(vid, canal_id=canal_id,
                                    publicado_en=publicado_en,
                                    fecha_subida=fecha)

        print("hora de publicacion: %d desde fichas locales, %d re-consultados"
              % (de_disco, de_red))

        if args.sin_red:
            print("--sin-red: no se consulta el pais del canal")
            return 0

        pendientes_pais = store.canales_sin_pais()
        if not pendientes_pais:
            print("no hay canales pendientes de pais")
            return 0
        try:
            encontrados = canal_info.paises(pendientes_pais, settings,
                                            log=lambda m: print("  %s" % m))
            tocadas = store.fijar_pais(encontrados)
            print("pais anotado en %d videos (%d de %d canales lo declaran)"
                  % (tocadas, len(encontrados), len(pendientes_pais)))
        except canal_info.ApiNoDisponible as exc:
            print("sin pais de canal (%s)" % exc)
            print("  crea la key en https://console.cloud.google.com "
                  "-> YouTube Data API v3 y ponla en .env como YOUTUBE_API_KEY")
        return 0
    finally:
        store.cerrar()


if __name__ == "__main__":
    sys.exit(main())
