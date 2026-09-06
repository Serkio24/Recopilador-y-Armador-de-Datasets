# -*- coding: utf-8 -*-
"""Configuracion global del recopilador."""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

RAIZ = Path(__file__).resolve().parent.parent

# Extensiones que cuentan como video. El merge_output_format es mp4, pero yt-dlp
# puede dejar otra cosa si no hay que unir pistas.
EXT_VIDEO = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv")


def _cargar_env():
    """Lee el .env de la raiz del proyecto si python-dotenv esta disponible."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(RAIZ / ".env")


_cargar_env()


def localizar_ffmpeg() -> Optional[str]:
    """Carpeta que contiene ffmpeg.exe, o None si no se encuentra.

    Se busca tambien fuera del PATH porque winget lo instala sin refrescar la
    variable en las terminales ya abiertas.
    """
    en_path = shutil.which("ffmpeg")
    if en_path:
        return str(Path(en_path).parent)

    candidatos = []
    local = os.getenv("LOCALAPPDATA")
    if local:
        candidatos.extend(
            Path(local).glob("Microsoft/WinGet/Packages/*FFmpeg*/**/bin/ffmpeg.exe"))
    for base in (r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin"):
        candidatos.append(Path(base) / "ffmpeg.exe")

    for c in candidatos:
        if c.exists():
            return str(c.parent)
    return None


def localizar_js_runtime() -> dict:
    """Motores de JavaScript que yt-dlp puede usar, en el formato de `js_runtimes`.

    YouTube protege las URLs de sus formatos con un reto en JavaScript. Sin un
    motor para resolverlo, yt-dlp cae a un modo degradado que usa un solo
    cliente de reproduccion, y ahi YouTube responde con "The page needs to be
    reloaded" o 403 muy a menudo. yt-dlp solo habilita `deno` por su cuenta, de
    modo que aqui se declaran tambien node y bun si estan en el equipo.
    """
    runtimes = {}
    for nombre in ("deno", "node", "bun"):
        ruta = shutil.which(nombre)
        if ruta:
            runtimes[nombre] = {"path": ruta}
    return runtimes


@dataclass
class Settings:
    """Parametros de una corrida de recoleccion."""

    data_dir: Path = field(default_factory=lambda: RAIZ / "data")
    max_duration: int = 180         # segundos; tope real de un Short desde 2024
    max_resolucion: int = 720       # lado corto: en vertical la altura es el lado largo
    concurrency: int = 2
    sleep_interval: float = 1.0     # pausa minima entre peticiones de yt-dlp
    solo_vertical: bool = True
    subtitulos: bool = True
    idiomas_subs: List[str] = field(default_factory=lambda: ["es", "en"])
    youtube_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("YOUTUBE_API_KEY") or None
    )
    ffmpeg_dir: Optional[str] = field(default_factory=localizar_ffmpeg)
    js_runtimes: dict = field(default_factory=localizar_js_runtime)

    # YouTube limita el ritmo por rafagas: un lote entero puede fallar y los
    # mismos videos bajar sin problema minutos despues. De ahi los reintentos.
    reintentos: int = 2             # rondas extra sobre los fallos transitorios
    pausa_reintento: float = 25.0   # segundos de espera antes de cada ronda

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)

    # -- rutas derivadas -------------------------------------------------
    @property
    def videos_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def meta_dir(self) -> Path:
        return self.data_dir / "meta"

    @property
    def subs_dir(self) -> Path:
        return self.data_dir / "subs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "index.sqlite"

    @property
    def archive_path(self) -> Path:
        return self.data_dir / "archive.txt"

    def preparar(self) -> "Settings":
        """Crea el arbol de carpetas de datos. Idempotente."""
        for d in (self.data_dir, self.videos_dir, self.meta_dir, self.subs_dir):
            d.mkdir(parents=True, exist_ok=True)
        return self

    def localizar_video(self, video_id: str,
                        ruta_guardada: str = "") -> Optional[Path]:
        """Ruta real del video, o None si no esta en disco.

        `videos.ruta_video` guarda una ruta absoluta, y basta con abrir el mismo
        corpus desde otro sitio para que deje de resolver: dentro del contenedor
        es "/app/data/videos/x.mp4" y en Windows "C:\\...\\data\\videos\\x.mp4".
        Sin este respaldo, `Store.reconciliar` daba por perdidos videos que
        estaban ahi, los borraba del indice y barria sus fichas y subtitulos, con
        lo que abrir el corpus en los dos entornos lo iba destruyendo.

        Quien manda es la convencion de nombres --el fichero es "<video_id>.<ext>"
        dentro de `videos_dir`--; la ruta guardada solo es un atajo por si el
        corpus tiene una disposicion antigua.
        """
        if ruta_guardada:
            ruta = Path(ruta_guardada)
            if ruta.exists():
                return ruta
        encontrados = [p for p in self.videos_dir.glob("%s.*" % video_id)
                       if p.suffix.lower() in EXT_VIDEO]
        return encontrados[0] if encontrados else None
