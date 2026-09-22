# -*- coding: utf-8 -*-
"""Indice SQLite de lo ya recolectado.

Es el punto de enganche para etapas posteriores (transcripcion, analisis):
basta con leer la tabla `videos` para saber que hay en disco y donde.
"""

import io
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .models import RegistroVideo

ESQUEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id      TEXT PRIMARY KEY,
    tema          TEXT,
    titulo        TEXT,
    url           TEXT,
    canal         TEXT,
    canal_id      TEXT,
    duracion      REAL,
    ancho         INTEGER,
    alto          INTEGER,
    vistas        INTEGER,
    fecha_subida  TEXT,
    publicado_en  TEXT,
    pais_canal    TEXT,
    ruta_video    TEXT,
    ruta_meta     TEXT,
    ruta_subs     TEXT,
    bytes_video   INTEGER,
    descargado_en TEXT,
    origen        TEXT,
    estado        TEXT,
    detalle       TEXT,
    transcrito    INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_videos_tema   ON videos(tema);
CREATE INDEX IF NOT EXISTS idx_videos_estado ON videos(estado);

CREATE TABLE IF NOT EXISTS busquedas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tema          TEXT,
    fecha         TEXT,
    backend       TEXT,
    n_pedidos     INTEGER,
    n_candidatos  INTEGER,
    n_descargados INTEGER,
    cancelado     INTEGER
);
"""

_CAMPOS = [
    "video_id", "tema", "titulo", "url", "canal", "canal_id", "duracion",
    "ancho", "alto", "vistas", "fecha_subida", "publicado_en", "pais_canal",
    "ruta_video", "ruta_meta", "ruta_subs",
    "bytes_video", "descargado_en", "origen", "estado", "detalle",
]

# Columnas anadidas despues de la primera version, para bases ya creadas.
_COLUMNAS_NUEVAS = {
    "canal_id": "TEXT",
    "publicado_en": "TEXT",
    "pais_canal": "TEXT",
}


class Store:
    """Acceso al indice. Seguro para usarse desde varios hilos."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self.init_db()

    def init_db(self):
        with self._lock:
            self._con.executescript(ESQUEMA)
            self._migrar()
            self._con.commit()

    def _migrar(self):
        """Pone al dia bases creadas por versiones anteriores.

        `CREATE TABLE IF NOT EXISTS` no toca una tabla que ya existe, asi que
        sin esto una base de antes se quedaria sin las columnas nuevas y toda
        escritura fallaria con "no such column".
        """
        columnas = {f[1] for f in self._con.execute("PRAGMA table_info(videos)")}
        for nombre, tipo in _COLUMNAS_NUEVAS.items():
            if nombre not in columnas:
                self._con.execute(
                    "ALTER TABLE videos ADD COLUMN %s %s" % (nombre, tipo))

        # `fecha_subida` se guardaba como YYYYMMDD, tal cual la da yt-dlp: Excel
        # lo abre como un numero y pandas necesita un `format=` explicito. Se
        # normaliza a ISO. Solo toca las de 8 digitos, asi que repetirlo no hace
        # nada la segunda vez.
        self._con.execute(
            "UPDATE videos SET fecha_subida = "
            "    substr(fecha_subida, 1, 4) || '-' || "
            "    substr(fecha_subida, 5, 2) || '-' || substr(fecha_subida, 7, 2) "
            "WHERE fecha_subida IS NOT NULL "
            "  AND length(fecha_subida) = 8 "
            "  AND fecha_subida GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'")

    def cerrar(self):
        with self._lock:
            self._con.close()

    # -- consultas -------------------------------------------------------
    def ya_existe(self, video_id: str) -> bool:
        """True si el video ya se descargo correctamente antes."""
        with self._lock:
            cur = self._con.execute(
                "SELECT estado FROM videos WHERE video_id = ?", (video_id,)
            )
            fila = cur.fetchone()
        return fila is not None and fila["estado"] == "ok"

    def ids_conocidos(self) -> set:
        """Ids ya descargados con exito, para filtrar candidatos de una."""
        with self._lock:
            cur = self._con.execute("SELECT video_id FROM videos WHERE estado = 'ok'")
            return set(r["video_id"] for r in cur.fetchall())

    def listar(self, tema: Optional[str] = None, solo_ok: bool = True) -> List[sqlite3.Row]:
        sql = "SELECT * FROM videos"
        cond, params = [], []
        if tema:
            cond.append("tema = ?")
            params.append(tema)
        if solo_ok:
            cond.append("estado = 'ok'")
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY descargado_en DESC"
        with self._lock:
            return self._con.execute(sql, params).fetchall()

    # -- mantenimiento ---------------------------------------------------
    def reconciliar(self, settings):
        """Pone indice, archive.txt y disco de acuerdo.

        Si se vacia `data/videos` a mano, las filas 'ok' y el archive.txt de
        yt-dlp siguen afirmando que esos videos existen: `ids_conocidos` los
        excluye de la busqueda y, si aun asi aparecieran, yt-dlp los saltaria por
        el archivo de control. El corpus quedaria imposible de reconstruir.

        Devuelve (filas_descartadas, ficheros_barridos).
        """
        with self._lock:
            filas = self._con.execute(
                "SELECT video_id, ruta_video FROM videos WHERE estado = 'ok'"
            ).fetchall()

        perdidos, vivos, recolocados = [], [], []
        for f in filas:
            # Por la ruta guardada primero y por la convencion de nombres
            # despues: la ruta del indice es absoluta y no resuelve si el corpus
            # se abre desde otro sitio --el contenedor lo ve en /app/data--, y
            # dar por perdido lo que solo esta en otra ruta borraba del indice
            # videos que seguian en disco.
            real = settings.localizar_video(f["video_id"], f["ruta_video"] or "")
            if real is None:
                perdidos.append(f["video_id"])
                continue
            vivos.append(f["video_id"])
            if str(real) != (f["ruta_video"] or ""):
                recolocados.append((str(real), f["video_id"]))

        if recolocados:
            # Se deja la ruta al dia para que la proxima pasada no tenga que
            # volver a buscar, y para que el analisis abra el fichero correcto.
            with self._lock:
                self._con.executemany(
                    "UPDATE videos SET ruta_video = ? WHERE video_id = ?",
                    recolocados)
                self._con.commit()

        if perdidos:
            with self._lock:
                self._con.executemany("DELETE FROM videos WHERE video_id = ?",
                                      [(v,) for v in perdidos])
                self._con.commit()

        self._sincronizar_archivo(Path(settings.archive_path), vivos)
        return len(perdidos), self._barrer_huerfanas(settings, set(vivos))

    @staticmethod
    def _barrer_huerfanas(settings, vivos: set) -> int:
        """Borra fichas y subtitulos cuyo video ya no esta en disco.

        Una descarga que falla despues de escribir el .info.json deja la ficha
        suelta; sin barrerla, meta/ acumula entradas que no corresponden a nada
        del corpus y falsean cualquier recuento posterior.
        """
        barridas = 0
        for carpeta in (settings.meta_dir, settings.subs_dir):
            if not carpeta.exists():
                continue
            for resto in carpeta.iterdir():
                # Los nombres son "<id>.info.json" y "<id>.es.vtt"; un id de
                # YouTube nunca lleva punto, asi que el primer trozo es el id.
                if not resto.is_file() or resto.name.split(".")[0] in vivos:
                    continue
                try:
                    resto.unlink()
                    barridas += 1
                except OSError:
                    pass
        return barridas

    @staticmethod
    def _sincronizar_archivo(ruta: Path, ids: List[str]) -> bool:
        """Deja archive.txt con exactamente los ids dados. True si hubo cambios."""
        deseado = ["youtube %s" % v for v in ids]
        actual = []
        if ruta.exists():
            with io.open(str(ruta), encoding="utf-8") as f:
                actual = [l.strip() for l in f if l.strip()]
        if actual == deseado:
            return False
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with io.open(str(ruta), "w", encoding="utf-8") as f:
            for linea in deseado:
                f.write(linea + "\n")
        return True

    # -- escritura -------------------------------------------------------
    def guardar(self, reg: RegistroVideo):
        d = reg.como_dict()
        if not d.get("descargado_en"):
            d["descargado_en"] = datetime.now().isoformat(timespec="seconds")
        valores = [d.get(c) for c in _CAMPOS]
        sql = "INSERT OR REPLACE INTO videos (%s) VALUES (%s)" % (
            ", ".join(_CAMPOS), ", ".join("?" * len(_CAMPOS))
        )
        with self._lock:
            self._con.execute(sql, valores)
            self._con.commit()

    def actualizar_campos(self, video_id: str, **campos) -> int:
        """Escribe solo los campos indicados de un video, sin tocar el resto.

        Los valores vacios se ignoran: el backfill no debe borrar un dato bueno
        cuando la re-consulta a YouTube vuelve incompleta.
        """
        utiles = {k: v for k, v in campos.items()
                  if k in _CAMPOS and k != "video_id" and v not in (None, "")}
        if not utiles:
            return 0
        nombres = sorted(utiles)
        sql = "UPDATE videos SET %s WHERE video_id = ?" % (
            ", ".join("%s = ?" % n for n in nombres))
        with self._lock:
            cur = self._con.execute(sql, [utiles[n] for n in nombres] + [video_id])
            self._con.commit()
        return cur.rowcount

    def canales_sin_pais(self) -> List[str]:
        """Ids de canal con algun video cuyo pais aun no se ha resuelto."""
        with self._lock:
            filas = self._con.execute(
                "SELECT DISTINCT canal_id FROM videos "
                "WHERE canal_id IS NOT NULL AND canal_id != '' "
                "  AND (pais_canal IS NULL OR pais_canal = '')"
            ).fetchall()
        return [f[0] for f in filas]

    def fijar_pais(self, paises: dict) -> int:
        """Escribe el pais de cada canal en todos sus videos. Devuelve filas tocadas.

        Se hace por canal y no por video: un canal con treinta Shorts se
        resuelve con una sola consulta a la API.
        """
        if not paises:
            return 0
        tocadas = 0
        with self._lock:
            for canal_id, pais in paises.items():
                if not pais:
                    continue
                cur = self._con.execute(
                    "UPDATE videos SET pais_canal = ? WHERE canal_id = ?",
                    (pais, canal_id))
                tocadas += cur.rowcount
            self._con.commit()
        return tocadas

    def registrar_busqueda(self, tema, backend, n_pedidos, n_candidatos,
                           n_descargados, cancelado=False):
        with self._lock:
            self._con.execute(
                "INSERT INTO busquedas (tema, fecha, backend, n_pedidos, "
                "n_candidatos, n_descargados, cancelado) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tema, datetime.now().isoformat(timespec="seconds"), backend,
                 n_pedidos, n_candidatos, n_descargados, 1 if cancelado else 0),
            )
            self._con.commit()
