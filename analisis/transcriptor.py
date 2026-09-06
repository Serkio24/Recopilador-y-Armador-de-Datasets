# -*- coding: utf-8 -*-
"""Transcripcion local con faster-whisper.

No hace falta el ffmpeg.exe que localiza `recopilador.config`: faster-whisper
decodifica el .mp4 con PyAV, que viene dentro del paquete. La dependencia de
ffmpeg sigue siendo solo de la etapa de descarga.
"""

import time
from pathlib import Path
from typing import Callable, Optional

from .config import (AjustesAnalisis, carpeta_modelos_whisper,
                     registrar_dll_cuda)
from .models import Cancelado, Transcripcion


class Transcriptor(object):
    """Envuelve un WhisperModel cargado una sola vez.

    Construir el modelo cuesta varios segundos y reserva memoria de la tarjeta;
    hacerlo por video dominaria el tiempo total de una corrida.
    """

    def __init__(self, ajustes: AjustesAnalisis,
                 log: Optional[Callable[[str], None]] = None):
        self.ajustes = ajustes
        self.log = log or (lambda _m: None)
        self._modelo = None
        self.device = None
        self.compute_type = None
        self._solo_cpu = False          # se activa si la GPU falla en marcha

    # -- carga ------------------------------------------------------------
    def cargar(self):
        """Construye el modelo, cayendo a CPU si la GPU no esta utilizable."""
        if self._modelo is not None:
            return self._modelo

        registrar_dll_cuda()
        from faster_whisper import WhisperModel

        intentos = []
        if self.ajustes.device in ("auto", "cuda") and not self._solo_cpu:
            intentos.append(("cuda", self.ajustes.compute_type_gpu))
        if self.ajustes.device in ("auto", "cpu") or self._solo_cpu:
            intentos.append(("cpu", self.ajustes.compute_type_cpu))

        ultimo = None
        for device, compute_type in intentos:
            try:
                self.log("Cargando %s en %s (%s)..."
                         % (self.ajustes.modelo_whisper, device, compute_type))
                self._modelo = WhisperModel(
                    self.ajustes.modelo_whisper,
                    device=device,
                    compute_type=compute_type,
                    download_root=carpeta_modelos_whisper(),
                )
                self.device, self.compute_type = device, compute_type
                return self._modelo
            except Exception as exc:            # CUDA ausente, VRAM corta, DLL...
                ultimo = exc
                if device == "cuda":
                    # Se dice en voz alta: en CPU se pasa de unos segundos por
                    # Short a cerca de un minuto, y quien lanza un lote de 200
                    # videos tiene que enterarse ahora, no al final.
                    self.log("No se pudo usar la GPU (%s). Se sigue en CPU, que "
                             "es mucho más lento; si tienes tarjeta NVIDIA, "
                             "instala las DLL de CUDA con:  "
                             ".venv\\Scripts\\python.exe -m pip install -r "
                             "requirements-gpu.txt" % str(exc)[:200])
        raise RuntimeError("no se pudo cargar el modelo de voz: %s" % ultimo)

    def descargar(self):
        """Suelta el modelo y con el la memoria de la tarjeta."""
        self._modelo = None

    @property
    def descripcion(self) -> str:
        return "%s/%s" % (self.ajustes.modelo_whisper, self.device or "?")

    def _degradar_a_cpu(self, motivo: str) -> bool:
        """Rehace el modelo en CPU tras un fallo de la GPU. False si ya estaba.

        Si el usuario pidió `cuda` explícitamente no se degrada: prefiere ver el
        error a que la corrida se le vaya a diez veces el tiempo previsto.
        """
        if self.device != "cuda" or self.ajustes.device == "cuda":
            return False
        self.log("La GPU falló al transcribir (%s). Se rehace el modelo en CPU y "
                 "se continúa; irá mucho más lento." % motivo[:160])
        self._modelo = None
        self.device = None
        self._solo_cpu = True
        self.cargar()
        return True

    # -- trabajo ----------------------------------------------------------
    def transcribir(self, video_id: str, ruta: Path, cancel=None) -> Transcripcion:
        """Transcribe un video. Lanza `Cancelado` si se pide parar por el camino."""
        try:
            return self._transcribir(video_id, ruta, cancel)
        except Cancelado:
            raise
        except Exception as exc:
            # Con las DLL de CUDA a medio instalar el modelo se construye sin
            # quejarse y revienta aqui, al codificar el primer audio. Si el
            # respaldo solo cubriera la carga, un lote entero moriria en el
            # primer video por algo que en CPU habria funcionado.
            if not self._degradar_a_cpu(str(exc)):
                raise
            return self._transcribir(video_id, ruta, cancel)

    def _transcribir(self, video_id: str, ruta: Path, cancel=None) -> Transcripcion:
        modelo = self.cargar()
        inicio = time.time()

        segmentos, info = modelo.transcribe(
            str(ruta),
            language=self.ajustes.idioma,
            beam_size=self.ajustes.beam_size,
            vad_filter=self.ajustes.vad,
            # Sin esto, un Short con musica arrastra la frase anterior y Whisper
            # entra en bucle repitiendola hasta el final del audio.
            condition_on_previous_text=False,
        )

        trozos = []
        # `segmentos` es un generador: el trabajo de verdad ocurre al recorrerlo,
        # asi que este bucle es el unico sitio donde se puede cortar a mitad de
        # un video.
        for seg in segmentos:
            if cancel is not None and cancel.is_set():
                raise Cancelado("cancelado durante la transcripcion")
            texto = (seg.text or "").strip()
            if texto:
                trozos.append((float(seg.start), float(seg.end), texto))

        return Transcripcion(
            video_id=video_id,
            texto=" ".join(t[2] for t in trozos).strip(),
            idioma=getattr(info, "language", "") or "",
            prob_idioma=getattr(info, "language_probability", None),
            n_segmentos=len(trozos),
            duracion_audio=getattr(info, "duration", None),
            modelo=self.descripcion,
            segundos=time.time() - inicio,
            segmentos=trozos,
        )
