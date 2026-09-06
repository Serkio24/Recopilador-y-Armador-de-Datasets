# -*- coding: utf-8 -*-
"""Orquestacion: buscar -> filtrar -> descargar en paralelo -> indexar."""

import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Callable, Optional

from . import search
from .downloader import Cancelado, descargar, es_transitorio
from .models import (ESTADO_DESCARTADO, ESTADO_ERROR, ESTADO_OK, ESTADO_OMITIDO,
                     RegistroVideo, Resumen)
from .store import Store


class _Bandera(object):
    """Une la cancelacion del usuario con la parada interna por objetivo cumplido."""

    def __init__(self, *eventos):
        self._eventos = [e for e in eventos if e is not None]

    def is_set(self) -> bool:
        return any(e.is_set() for e in self._eventos)


def _esperar(segundos, bandera):
    """Pausa troceada para que Cancelar responda al momento. True si se corto."""
    fin = time.time() + segundos
    while time.time() < fin:
        if bandera.is_set():
            return True
        time.sleep(0.25)
    return bandera.is_set()


def _limpiar_parciales(settings):
    for p in settings.videos_dir.glob("*.part"):
        try:
            p.unlink()
        except OSError:
            pass


def recolectar(tema: str,
               n: int,
               settings,
               on_progress: Optional[Callable[..., None]] = None,
               cancel_event: Optional[threading.Event] = None,
               store: Optional[Store] = None) -> Resumen:
    """Descarga hasta `n` Shorts sobre `tema`.

    on_progress(tipo, **datos) recibe eventos: "log", "busqueda", "video", "fin".
    """
    inicio = time.time()
    emitir = on_progress or (lambda *a, **k: None)
    log = lambda m: emitir("log", mensaje=m)

    settings.preparar()
    store_propio = store is None
    store = store or Store(settings.db_path)

    parar = threading.Event()
    bandera = _Bandera(cancel_event, parar)

    resumen = Resumen(tema=tema, pedidos=n)

    try:
        faltantes, huerfanas = store.reconciliar(settings)
        if faltantes:
            log("%d videos del indice ya no estan en disco: se descartan del "
                "indice y se podran volver a descargar" % faltantes)
        if huerfanas:
            log("%d fichas o subtitulos sueltos sin video: se borran" % huerfanas)

        conocidos = store.ids_conocidos()
        if conocidos:
            log("%d videos ya en el indice se excluiran de la busqueda" % len(conocidos))

        candidatos, backend = search.buscar(
            tema, n, settings, excluir=conocidos, log=log, cancel_event=bandera)
        resumen.backend = backend
        resumen.candidatos = len(candidatos)
        emitir("busqueda", candidatos=len(candidatos), backend=backend, objetivo=n)

        if not candidatos:
            log("la busqueda no devolvio candidatos nuevos")
        elif bandera.is_set():
            resumen.cancelado = True
        else:
            _rondas(candidatos, tema, n, settings, store, resumen,
                    emitir, log, bandera, parar)

        if cancel_event is not None and cancel_event.is_set():
            resumen.cancelado = True

        _limpiar_parciales(settings)
        resumen.segundos = time.time() - inicio
        store.registrar_busqueda(tema, resumen.backend, n, resumen.candidatos,
                                 resumen.descargados, resumen.cancelado)
        emitir("fin", resumen=resumen)
        return resumen

    finally:
        if store_propio:
            store.cerrar()


def _contabilizar(reg: RegistroVideo, resumen: Resumen):
    if reg.estado == ESTADO_OK:
        resumen.descargados += 1
        resumen.bytes += reg.bytes_video or 0
    elif reg.estado == ESTADO_OMITIDO:
        resumen.omitidos += 1
    elif reg.estado == ESTADO_DESCARTADO:
        resumen.descartados += 1
    else:
        resumen.errores += 1


def _rondas(candidatos, tema, n, settings, store, resumen, emitir, log,
            bandera, parar):
    """Descarga en rondas: lo que falla por limite de YouTube se reintenta.

    Un lote entero puede fallar porque YouTube esta cortando las peticiones en
    ese momento; sin reintentos la corrida termina con cero descargas aunque
    los videos esten perfectamente disponibles.
    """
    pendientes = list(candidatos)
    for intento in range(settings.reintentos + 1):
        fallidos, sobrantes = _descargar_lote(pendientes, tema, n, settings,
                                              store, resumen, emitir, bandera,
                                              parar, intento)
        pendientes = fallidos + sobrantes
        if not pendientes or resumen.descargados >= n or bandera.is_set():
            break
        if not fallidos:
            continue                # solo quedaban candidatos sin estrenar
        log("%d descargas fallaron por limite de YouTube; se reintentan en %.0f s"
            % (len(fallidos), settings.pausa_reintento))
        if _esperar(settings.pausa_reintento, bandera):
            break

    if resumen.descargados >= n or bandera.is_set():
        return

    faltan = n - resumen.descargados
    if resumen.errores >= faltan:
        log("YouTube rechazo las descargas de forma repetida (limite de "
            "peticiones). Espera unos minutos y vuelve a intentarlo; si sigue "
            "igual, baja las descargas simultaneas a 1.")
    else:
        log("se agotaron los candidatos: %d de %d descargados "
            "(sube la cantidad pedida o amplia la duracion maxima)"
            % (resumen.descargados, n))


def _descargar_lote(candidatos, tema, n, settings, store, resumen, emitir,
                    bandera, parar, intento=0):
    """Lanza una ronda de descargas.

    Devuelve (fallidos_reintentables, no_intentados): los primeros fallaron por
    algo pasajero, los segundos ni se llegaron a pedir porque ya se habia
    cumplido el objetivo.
    """
    pendientes = iter(candidatos)
    en_vuelo = {}
    reintentables = []
    ultima_ronda = intento >= settings.reintentos

    def procesar(fut):
        cand = en_vuelo.pop(fut)
        try:
            reg = fut.result()
        except Cancelado:
            return
        except Exception as exc:                    # red de seguridad
            reg = RegistroVideo(video_id=cand.video_id, tema=tema, url=cand.url,
                                titulo=cand.titulo, estado=ESTADO_ERROR,
                                detalle=str(exc)[:300])

        # Un fallo transitorio no se indexa todavia: si la siguiente ronda lo
        # baja bien, no debe quedar como error en el resumen ni en la base.
        if (reg.estado == ESTADO_ERROR and not ultima_ronda
                and es_transitorio(reg.detalle)):
            reintentables.append(cand)
            emitir("video", registro=reg, hechos=resumen.descargados,
                   objetivo=n, reintentable=True)
            return

        store.guardar(reg)
        _contabilizar(reg, resumen)
        emitir("video", registro=reg, hechos=resumen.descargados, objetivo=n)

    with ThreadPoolExecutor(max_workers=settings.concurrency) as ex:
        def lanzar():
            # No se lanza mas de lo que falta: evita bajar videos de sobra
            # cuando las descargas en curso terminan bien.
            while (len(en_vuelo) < settings.concurrency
                   and resumen.descargados + len(en_vuelo) < n
                   and not bandera.is_set()):
                try:
                    cand = next(pendientes)
                except StopIteration:
                    return
                en_vuelo[ex.submit(descargar, cand, tema, settings, bandera,
                                   intento)] = cand

        lanzar()
        while en_vuelo:
            hechos, _ = wait(list(en_vuelo), return_when=FIRST_COMPLETED)
            for fut in hechos:
                procesar(fut)

            if resumen.descargados >= n:
                parar.set()                          # aborta lo que siga en vuelo
                break
            if bandera.is_set():
                break
            lanzar()

        # Drena lo que quedaba corriendo: si alguno alcanzo a terminar bien,
        # se indexa igual para no dejar archivos huerfanos en disco.
        while en_vuelo:
            hechos, _ = wait(list(en_vuelo), return_when=FIRST_COMPLETED)
            for fut in hechos:
                procesar(fut)

    # Lo que nunca llego a intentarse vuelve al final de la cola por si la
    # siguiente ronda lo necesita.
    return reintentables, list(pendientes)
