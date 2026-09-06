# -*- coding: utf-8 -*-
"""Pestaña «Analizar»: transcribir el corpus y clasificarlo en un dataset.

Trabaja sobre lo que ya está descargado, así que se puede volver a clasificar
con otras columnas sin bajar ni transcribir nada otra vez: ese ciclo corto es la
razón de que esta etapa sea una pestaña aparte y no la cola de la descarga.
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from recopilador.config import RAIZ, Settings
from recopilador.ui.comun import PADDING, PanelBase, abrir_carpeta

from ..config import (AjustesAnalisis, MODELOS_WHISPER,
                      MODELO_WHISPER_POR_DEFECTO)
from ..models import esquema_por_defecto
from ..store import AnalisisStore
from .editor_esquema import EditorEsquema
from .worker import Trabajador

IDIOMAS = [("detectar automáticamente", None), ("español", "es"),
           ("inglés", "en")]

TODOS_LOS_TEMAS = "(todos los temas)"


class PanelAnalisis(PanelBase):
    def __init__(self, master):
        PanelBase.__init__(self, master, padding=PADDING)

        self.trabajador = Trabajador()
        self.objetivo = 0
        self.esquema = esquema_por_defecto()

        self.var_carpeta = tk.StringVar(value=str(RAIZ / "data"))
        self.var_alcance = tk.StringVar(value="pendientes")
        self.var_tema = tk.StringVar(value="")
        self.var_modelo_voz = tk.StringVar(value=MODELO_WHISPER_POR_DEFECTO)
        self.var_idioma = tk.StringVar(value=IDIOMAS[0][0])
        self.var_modelo_llm = tk.StringVar(value=AjustesAnalisis().modelo_llm)
        self.var_clasificar = tk.BooleanVar(value=True)
        self.var_retranscribir = tk.BooleanVar(value=False)
        self.var_reclasificar = tk.BooleanVar(value=False)
        self.var_esquema = tk.StringVar(value=self.esquema.nombre)
        self.var_estado = tk.StringVar(value="Listo.")
        self.var_conteos = tk.StringVar(value="")

        self._construir()
        self._arrancar_drenaje()
        self.after(200, self._refrescar_desde_indice)

    # -- construccion de la interfaz --------------------------------------
    def _construir(self):
        self.columnconfigure(1, weight=1)
        fila = 0

        # -- que analizar --------------------------------------------------
        alcance = ttk.LabelFrame(self, text="Qué analizar", padding=6)
        alcance.grid(row=fila, column=0, columnspan=4, sticky="ew")
        alcance.columnconfigure(3, weight=1)
        ttk.Radiobutton(alcance, text="Solo lo que falta", value="pendientes",
                        variable=self.var_alcance).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(alcance, text="Todo el corpus", value="todos",
                        variable=self.var_alcance).grid(row=0, column=1,
                                                        sticky="w", padx=12)
        ttk.Label(alcance, text="Tema:").grid(row=0, column=2, sticky="e")
        self.combo_tema = ttk.Combobox(alcance, textvariable=self.var_tema,
                                       state="readonly", width=30)
        self.combo_tema.grid(row=0, column=3, sticky="w", padx=4)
        ttk.Label(alcance, textvariable=self.var_conteos, foreground="#555").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        fila += 1

        # -- transcripcion -------------------------------------------------
        voz = ttk.LabelFrame(self, text="Transcripción", padding=6)
        voz.grid(row=fila, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Label(voz, text="Modelo:").pack(side="left")
        ttk.Combobox(voz, textvariable=self.var_modelo_voz,
                     values=list(MODELOS_WHISPER), state="readonly",
                     width=10).pack(side="left", padx=(4, 12))
        ttk.Label(voz, text="Idioma:").pack(side="left")
        ttk.Combobox(voz, textvariable=self.var_idioma,
                     values=[n for n, _ in IDIOMAS], state="readonly",
                     width=22).pack(side="left", padx=(4, 12))
        ttk.Checkbutton(voz, text="Volver a transcribir lo ya transcrito",
                        variable=self.var_retranscribir).pack(side="left")
        fila += 1

        # -- clasificacion -------------------------------------------------
        clas = ttk.LabelFrame(self, text="Clasificación", padding=6)
        clas.grid(row=fila, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        clas.columnconfigure(1, weight=1)

        linea1 = ttk.Frame(clas)
        linea1.grid(row=0, column=0, columnspan=3, sticky="ew")
        ttk.Label(linea1, text="Modelo de Ollama:").pack(side="left")
        ttk.Entry(linea1, textvariable=self.var_modelo_llm, width=26).pack(
            side="left", padx=4)
        ttk.Button(linea1, text="Comprobar", command=self._comprobar_ollama).pack(
            side="left", padx=(0, 12))
        ttk.Checkbutton(linea1, text="Clasificar", variable=self.var_clasificar,
                        command=self._al_cambiar_clasificar).pack(side="left")
        ttk.Checkbutton(linea1, text="Volver a clasificar lo ya clasificado",
                        variable=self.var_reclasificar).pack(side="left", padx=12)

        linea2 = ttk.Frame(clas)
        linea2.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Button(linea2, text="Columnas del dataset...",
                   command=self._editar_esquema).pack(side="left")
        self.lbl_esquema = ttk.Label(linea2, textvariable=self.var_esquema,
                                     foreground="#555")
        self.lbl_esquema.pack(side="left", padx=8)
        fila += 1

        # -- carpeta -------------------------------------------------------
        carpeta = ttk.Frame(self)
        carpeta.grid(row=fila, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        carpeta.columnconfigure(1, weight=1)
        ttk.Label(carpeta, text="Carpeta:").grid(row=0, column=0, sticky="w")
        ttk.Entry(carpeta, textvariable=self.var_carpeta).grid(
            row=0, column=1, sticky="ew", padx=4)
        ttk.Button(carpeta, text="Elegir...", command=self._elegir_carpeta).grid(
            row=0, column=2)
        fila += 1

        # -- acciones ------------------------------------------------------
        acciones = ttk.Frame(self)
        acciones.grid(row=fila, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        self.btn_iniciar = ttk.Button(acciones, text="Transcribir y clasificar",
                                      command=self._iniciar)
        self.btn_iniciar.pack(side="left")
        self.btn_cancelar = ttk.Button(acciones, text="Cancelar",
                                       command=self._cancelar, state="disabled")
        self.btn_cancelar.pack(side="left", padx=6)
        ttk.Button(acciones, text="Exportar CSV", command=self._exportar).pack(
            side="left")
        ttk.Button(acciones, text="Abrir carpeta",
                   command=lambda: abrir_carpeta(self.var_carpeta.get())).pack(
            side="left", padx=6)
        ttk.Label(acciones, textvariable=self.var_estado).pack(side="right")
        fila += 1

        self.barra = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.barra.grid(row=fila, column=0, columnspan=4, sticky="ew", pady=4)
        fila += 1

        self._crear_log(fila, height=14)

    # -- utilidades -------------------------------------------------------
    def _settings(self):
        return Settings(data_dir=Path(self.var_carpeta.get().strip()
                                      or (RAIZ / "data")))

    def _abrir_store(self):
        return AnalisisStore(self._settings().db_path)

    def _elegir_carpeta(self):
        elegida = filedialog.askdirectory(initialdir=self.var_carpeta.get() or str(RAIZ))
        if elegida:
            self.var_carpeta.set(elegida)
            self._refrescar_desde_indice()

    def _al_cambiar_clasificar(self):
        self.btn_iniciar.configure(
            text="Transcribir y clasificar" if self.var_clasificar.get()
            else "Solo transcribir")

    def al_mostrarse(self):
        """Se llama al pasar a esta pestaña.

        Entre dos visitas puede haberse descargado otro lote en la pestaña de
        al lado, y entonces la lista de temas de aquí ya no vale. Sin esto
        seguía filtrando por un tema que no existía y el CSV salía con solo la
        cabecera, sin decir por qué.
        """
        if not self.trabajador.activo():
            self._refrescar_desde_indice()

    def _refrescar_desde_indice(self):
        """Rellena temas, conteos y esquema guardado leyendo el índice.

        Se hace al abrir y al cambiar de carpeta: la pestaña tiene que reflejar
        lo que haya descargado la otra, aunque se haya descargado hace un rato.
        """
        try:
            store = self._abrir_store()
        except Exception as exc:                        # base ilegible
            self._escribir("No se puede leer el índice: %s" % exc, "err")
            return
        try:
            # Entre dos visitas a esta pestaña puede haberse descargado otro
            # lote, y con él haberse ido del índice los vídeos de antes. Sin
            # este barrido los conteos de abajo hablarían de un corpus que ya
            # no existe.
            huerfanas = store.reconciliar()
            if huerfanas:
                self._escribir(
                    "%d transcripciones eran de vídeos que ya no están en el "
                    "índice: se descartan." % huerfanas, "warn")

            temas = store.temas()
            self.combo_tema.configure(values=[TODOS_LOS_TEMAS] + temas)
            # Si el tema elegido ya no existe (se descargó otro lote, se vació
            # el corpus), se vuelve a «todos». Dejarlo puesto filtraba por algo
            # que no casa con nada y devolvía un CSV con solo la cabecera, sin
            # que nada dijera por qué.
            elegido = self.var_tema.get().strip()
            if elegido and elegido != TODOS_LOS_TEMAS and elegido not in temas:
                self.var_tema.set(TODOS_LOS_TEMAS)
                self._escribir("El tema «%s» ya no está en el índice; se vuelve "
                               "a «%s»." % (elegido, TODOS_LOS_TEMAS), "warn")
            elif not elegido:
                self.var_tema.set(TODOS_LOS_TEMAS)

            guardado = store.cargar_esquema(self.esquema.nombre)
            if guardado is not None:
                self.esquema = guardado
            self.var_esquema.set(self._texto_esquema())

            c = store.conteos(self.esquema.nombre)
            self.var_conteos.set(
                "%d vídeos descargados · %d transcritos · %d clasificados con «%s»"
                % (c["videos"], c["transcritos"], c["clasificados"],
                   self.esquema.nombre))
        finally:
            store.cerrar()

    def _texto_esquema(self):
        return "«%s»: %s" % (
            self.esquema.nombre,
            ", ".join(c.nombre for c in self.esquema.columnas) or "sin columnas")

    def _tema_elegido(self):
        tema = self.var_tema.get().strip()
        return None if tema in ("", TODOS_LOS_TEMAS) else tema

    def _ajustes(self):
        idioma = dict(IDIOMAS).get(self.var_idioma.get())
        return AjustesAnalisis(
            modelo_whisper=self.var_modelo_voz.get(),
            idioma=idioma,
            modelo_llm=self.var_modelo_llm.get().strip(),
            clasificar=self.var_clasificar.get(),
            retranscribir=self.var_retranscribir.get(),
            reclasificar=self.var_reclasificar.get(),
        )

    # -- arranque ---------------------------------------------------------
    def avisar_del_entorno(self):
        """Deja a la vista lo que impide analizar, antes de empezar el lote.

        Sin esto, un lote de doscientos vídeos se descubre a mitad de camino de
        que Ollama no está instalado, después de haber transcrito una hora.
        """
        from .. import entorno

        ajustes = self._ajustes()
        for aviso in entorno.avisos(ajustes):
            self._escribir(aviso, "warn")

        fallos = entorno.problemas(ajustes, clasificar=self.var_clasificar.get())
        if not fallos:
            return
        # No se deshabilita el botón: puede faltar solo Ollama, y transcribir
        # sin clasificar sigue siendo útil. Se avisa y se deja decidir.
        self._escribir("Antes de analizar hay que resolver esto:", "err")
        sangrado = "\n" + " " * 4
        for f in fallos:
            self._escribir("  - %s" % f.replace("\n", sangrado), "err")

    def _comprobar_ollama(self):
        from ..clasificador import ErrorOllama, modelos_disponibles

        ajustes = self._ajustes()
        try:
            modelos = modelos_disponibles(ajustes.ollama_url)
        except ErrorOllama as exc:
            messagebox.showerror("Ollama", str(exc), parent=self)
            return
        if not modelos:
            messagebox.showwarning(
                "Ollama", "Ollama responde pero no tiene ningún modelo.\n\n"
                          "Descarga uno con:\n    ollama pull %s"
                          % ajustes.modelo_llm, parent=self)
            return
        messagebox.showinfo("Ollama", "Modelos disponibles:\n\n" + "\n".join(modelos),
                            parent=self)

    def _editar_esquema(self):
        editor = EditorEsquema(self.winfo_toplevel(), self.esquema)
        if editor.resultado is None:
            return
        self.esquema = editor.resultado
        store = self._abrir_store()
        try:
            store.guardar_esquema(self.esquema)
        finally:
            store.cerrar()
        self.var_esquema.set(self._texto_esquema())
        self._escribir("Esquema guardado: %s" % self._texto_esquema(), "ok")
        self._refrescar_desde_indice()

    # -- acciones ---------------------------------------------------------
    def _iniciar(self):
        if self.trabajador.activo():
            return
        fallos = self.esquema.problemas()
        if self.var_clasificar.get() and fallos:
            messagebox.showwarning("Esquema incompleto", "\n".join(fallos),
                                   parent=self)
            return

        settings = self._settings()
        ajustes = self._ajustes()
        tema = self._tema_elegido()
        solo_pendientes = self.var_alcance.get() == "pendientes"

        store = self._abrir_store()
        try:
            n = len(store.seleccionar(tema=tema, esquema=self.esquema.nombre,
                                      solo_pendientes=solo_pendientes))
        finally:
            store.cerrar()
        if not n:
            messagebox.showinfo(
                "Nada que hacer",
                "No hay vídeos que encajen con ese filtro.\n\n"
                "Si ya está todo analizado, elige «Todo el corpus» y marca las "
                "casillas de volver a procesar.", parent=self)
            return

        self.objetivo = n
        self.barra.configure(maximum=n, value=0)
        self.var_estado.set("Cargando el modelo...")
        self.btn_iniciar.configure(state="disabled")
        self.btn_cancelar.configure(state="normal")
        self._escribir("=== %d vídeos | voz %s | %s ==="
                       % (n, ajustes.modelo_whisper,
                          ("clasificando con %s" % ajustes.modelo_llm)
                          if ajustes.clasificar else "solo transcripción"))
        self.trabajador.iniciar(settings, self.esquema, ajustes, tema=tema,
                                solo_pendientes=solo_pendientes)

    def _cancelar(self):
        if self.trabajador.activo():
            self.trabajador.cancelar()
            self.var_estado.set("Cancelando...")
            self.btn_cancelar.configure(state="disabled")
            self._escribir("Cancelación solicitada; se termina el vídeo en curso.",
                           "warn")

    def _exportar(self):
        from .. import exportador

        settings = self._settings()
        destino = filedialog.asksaveasfilename(
            parent=self, defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialdir=str(settings.data_dir),
            initialfile="dataset_%s.csv" % self.esquema.nombre)
        if not destino:
            return
        tema = self._tema_elegido()
        try:
            ruta, n = exportador.exportar(settings, self.esquema,
                                          destino=Path(destino), tema=tema)
        except Exception as exc:
            messagebox.showerror("No se pudo exportar", str(exc), parent=self)
            return

        if not n:
            # Un CSV con solo la cabecera es el peor resultado posible: parece
            # que todo fue bien y no hay nada dentro. Se dice en voz alta y se
            # apunta a la causa habitual, que es el filtro de tema.
            self._escribir("El CSV salió vacío: ninguna fila encajó con el "
                           "filtro%s." % (" (tema «%s»)" % tema if tema else ""),
                           "err")
            messagebox.showwarning(
                "El CSV salió vacío",
                "Se escribió el archivo, pero sin ninguna fila.\n\n"
                + ("Está filtrado por el tema «%s» y no hay vídeos "
                   "descargados con ese tema. Pon el desplegable en «%s» y "
                   "vuelve a exportar." % (tema, TODOS_LOS_TEMAS) if tema else
                   "No hay vídeos descargados en esta carpeta."),
                parent=self)
            return
        self._escribir("CSV escrito: %s (%d filas)" % (ruta, n), "ok")

    # -- consumo de eventos del hilo --------------------------------------
    def _evento(self, tipo, datos):
        if tipo == "log":
            self._escribir(datos.get("mensaje", ""))

        elif tipo == "seleccion":
            self.var_estado.set("Analizando 0/%d" % self.objetivo)

        elif tipo == "video":
            hechos = min(datos.get("hechos", 0), self.objetivo)
            self.barra.configure(value=hechos)
            self.var_estado.set("Analizando %d/%d" % (hechos, self.objetivo))
            # "sin_voz" no es un fallo: se clasificó por el título. Va en otro
            # color para que se vea de un vistazo cuánto del lote se etiquetó
            # sin oír nada.
            marca, tag = {"ok": ("ok ", "ok"), "sin_voz": ("tit", "warn")}.get(
                datos.get("estado"), ("err", "err"))
            self._escribir("%s %s  %s  [%s]"
                           % (marca, datos.get("video_id", ""),
                              (datos.get("titulo") or "")[:60],
                              datos.get("detalle", "")), tag)

        elif tipo == "error":
            self._escribir("Fallo inesperado: %s" % datos.get("mensaje", ""), "err")
            self._escribir(datos.get("traza", ""), "err")

        elif tipo == "fin":
            r = datos["resumen"]
            self._escribir(
                "Resumen: %d transcritos (%d ya estaban), %d clasificados "
                "(%d de ellos sin voz, por el título), %d errores; %.0f s%s"
                % (r.transcritos, r.ya_estaban, r.clasificados, r.sin_habla,
                   r.errores, r.segundos, " (cancelado)" if r.cancelado else ""),
                "warn" if r.cancelado else "ok")

        elif tipo == "terminado":
            self.btn_iniciar.configure(state="normal")
            self.btn_cancelar.configure(state="disabled")
            self.var_estado.set("Listo.")
            self._refrescar_desde_indice()
