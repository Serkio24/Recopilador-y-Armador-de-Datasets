# -*- coding: utf-8 -*-
"""Piezas compartidas por las pestañas de la ventana.

Las dos pestañas hacen lo mismo por fuera: validan unos campos, lanzan un hilo
que trabaja y van escribiendo su progreso en un log de colores. Esto es esa
mecánica, para que no haya dos copias que se vayan separando con el tiempo.
"""

import os
from pathlib import Path
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

PADDING = 8


class PanelBase(ttk.Frame):
    """Marco con log, validación de enteros y drenaje de la cola del hilo."""

    def __init__(self, master, padding=PADDING):
        ttk.Frame.__init__(self, master, padding=padding)
        self.trabajador = None          # lo pone la subclase
        self.log = None

    # -- log ---------------------------------------------------------------
    def _crear_log(self, fila, columnspan=4, height=16):
        self.log = ScrolledText(self, height=height, wrap="word", state="disabled")
        self.log.grid(row=fila, column=0, columnspan=columnspan,
                      sticky="nsew", pady=(4, 0))
        self.rowconfigure(fila, weight=1)
        self.log.tag_configure("ok", foreground="#1a7f37")
        self.log.tag_configure("err", foreground="#b3261e")
        self.log.tag_configure("warn", foreground="#8a6d00")
        self.log.tag_configure("info", foreground="#444444")
        return self.log

    def _escribir(self, texto, tag="info"):
        self.log.configure(state="normal")
        self.log.insert("end", texto + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    # -- validacion --------------------------------------------------------
    def _entero(self, var, nombre, minimo, maximo):
        try:
            valor = int(var.get().strip())
        except ValueError:
            raise ValueError("%s debe ser un número entero." % nombre)
        if not (minimo <= valor <= maximo):
            raise ValueError("%s debe estar entre %d y %d." % (nombre, minimo, maximo))
        return valor

    # -- consumo de eventos del hilo ---------------------------------------
    def _arrancar_drenaje(self, cada_ms=100):
        self._cada_ms = cada_ms
        self.after(cada_ms, self._drenar)

    def _drenar(self):
        # El reenganche va en el finally: si un evento falla, la ventana tiene
        # que seguir refrescandose. Si no, deja de drenar la cola para siempre y
        # el boton se queda gris como si la app no dejara trabajar.
        try:
            if self.trabajador is not None:
                for tipo, datos in self.trabajador.drenar():
                    self._evento(tipo, datos)
        finally:
            self.after(self._cada_ms, self._drenar)

    def _evento(self, tipo, datos):
        raise NotImplementedError


def abrir_carpeta(ruta):
    """Abre una carpeta en el explorador del sistema, creándola si hace falta."""
    ruta = Path(ruta)
    ruta.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(str(ruta))                     # Windows
    except AttributeError:                          # otros sistemas
        import subprocess
        subprocess.Popen(["xdg-open", str(ruta)])
