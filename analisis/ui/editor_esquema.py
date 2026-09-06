# -*- coding: utf-8 -*-
"""Diálogo para decidir qué columnas tiene el dataset.

Es la pieza que hace que cambiar el esquema no sea tocar código: aquí se
declaran nombre, descripción y tipo de cada columna, y de eso salen tanto lo
que se le pide al modelo como las cabeceras del CSV.
"""

import tkinter as tk
from tkinter import messagebox, ttk

from ..models import (CON_OPCIONES, TIPO_NUMERO, TIPOS, Columna, EsquemaDataset)

AYUDA_TIPOS = {
    "categoria": "una sola de las opciones",
    "multietiqueta": "varias de las opciones",
    "booleano": "sí o no",
    "numero": "un número, con mínimo y máximo opcionales",
    "texto": "texto libre escrito por el modelo",
}


class EditorEsquema(tk.Toplevel):
    """Ventana modal. `resultado` queda a None si se cancela."""

    def __init__(self, master, esquema: EsquemaDataset):
        tk.Toplevel.__init__(self, master)
        self.title("Columnas del dataset")
        self.geometry("760x520")
        self.minsize(640, 420)
        self.transient(master)
        self.resultado = None

        # Copia: si el usuario cancela, el esquema de la pestaña no debe haberse
        # tocado a medias.
        self.columnas = [Columna(**c.como_dict()) for c in esquema.columnas]
        self.var_nombre = tk.StringVar(value=esquema.nombre)

        self._construir()
        self._refrescar()
        self.grab_set()
        self.wait_window(self)

    # -- construccion -----------------------------------------------------
    def _construir(self):
        marco = ttk.Frame(self, padding=10)
        marco.pack(fill="both", expand=True)
        marco.columnconfigure(0, weight=1)
        marco.rowconfigure(2, weight=1)

        cabecera = ttk.Frame(marco)
        cabecera.grid(row=0, column=0, sticky="ew")
        ttk.Label(cabecera, text="Nombre del esquema:").pack(side="left")
        ttk.Entry(cabecera, textvariable=self.var_nombre, width=28).pack(
            side="left", padx=6)
        ttk.Label(cabecera, foreground="#555",
                  text="(identifica este conjunto de columnas; puedes tener varios "
                       "sobre el mismo corpus)").pack(side="left")

        ttk.Label(marco, foreground="#555", wraplength=720, justify="left",
                  text="La descripción no es un comentario: es lo único que el "
                       "modelo lee para decidir qué poner en la columna. Sé "
                       "concreto.").grid(row=1, column=0, sticky="w", pady=(8, 4))

        tabla = ttk.Frame(marco)
        tabla.grid(row=2, column=0, sticky="nsew")
        tabla.columnconfigure(0, weight=1)
        tabla.rowconfigure(0, weight=1)

        self.arbol = ttk.Treeview(
            tabla, columns=("tipo", "descripcion", "opciones"),
            show="tree headings", selectmode="browse")
        self.arbol.heading("#0", text="Columna")
        self.arbol.heading("tipo", text="Tipo")
        self.arbol.heading("descripcion", text="Descripción")
        self.arbol.heading("opciones", text="Opciones")
        self.arbol.column("#0", width=150, stretch=False)
        self.arbol.column("tipo", width=100, stretch=False)
        self.arbol.column("descripcion", width=280)
        self.arbol.column("opciones", width=200)
        self.arbol.grid(row=0, column=0, sticky="nsew")
        self.arbol.bind("<Double-1>", lambda _e: self._editar())

        barra = ttk.Scrollbar(tabla, orient="vertical", command=self.arbol.yview)
        barra.grid(row=0, column=1, sticky="ns")
        self.arbol.configure(yscrollcommand=barra.set)

        botones = ttk.Frame(marco)
        botones.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(botones, text="Añadir...", command=self._anadir).pack(side="left")
        ttk.Button(botones, text="Editar...", command=self._editar).pack(
            side="left", padx=4)
        ttk.Button(botones, text="Quitar", command=self._quitar).pack(side="left")
        ttk.Button(botones, text="Subir", command=lambda: self._mover(-1)).pack(
            side="left", padx=(12, 2))
        ttk.Button(botones, text="Bajar", command=lambda: self._mover(1)).pack(
            side="left")
        ttk.Button(botones, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(botones, text="Guardar", command=self._guardar).pack(
            side="right", padx=6)

    # -- estado -----------------------------------------------------------
    def _refrescar(self, seleccion=None):
        self.arbol.delete(*self.arbol.get_children())
        for i, c in enumerate(self.columnas):
            self.arbol.insert("", "end", iid=str(i), text=c.nombre,
                              values=(c.tipo, c.descripcion,
                                      ", ".join(c.opciones)))
        if seleccion is not None and 0 <= seleccion < len(self.columnas):
            self.arbol.selection_set(str(seleccion))
            self.arbol.focus(str(seleccion))

    def _indice(self):
        sel = self.arbol.selection()
        return int(sel[0]) if sel else None

    # -- acciones ---------------------------------------------------------
    def _anadir(self):
        dlg = _DialogoColumna(self, None)
        if dlg.columna:
            self.columnas.append(dlg.columna)
            self._refrescar(len(self.columnas) - 1)

    def _editar(self):
        i = self._indice()
        if i is None:
            return
        dlg = _DialogoColumna(self, self.columnas[i])
        if dlg.columna:
            self.columnas[i] = dlg.columna
            self._refrescar(i)

    def _quitar(self):
        i = self._indice()
        if i is None:
            return
        del self.columnas[i]
        self._refrescar(min(i, len(self.columnas) - 1))

    def _mover(self, delta):
        i = self._indice()
        if i is None:
            return
        j = i + delta
        if not (0 <= j < len(self.columnas)):
            return
        self.columnas[i], self.columnas[j] = self.columnas[j], self.columnas[i]
        self._refrescar(j)

    def _guardar(self):
        esquema = EsquemaDataset(nombre=self.var_nombre.get().strip() or "general",
                                 columnas=self.columnas)
        fallos = esquema.problemas()
        if fallos:
            messagebox.showwarning("Esquema incompleto", "\n".join(fallos),
                                   parent=self)
            return
        self.resultado = esquema
        self.destroy()


class _DialogoColumna(tk.Toplevel):
    """Alta o edición de una columna."""

    def __init__(self, master, columna):
        tk.Toplevel.__init__(self, master)
        self.title("Columna del dataset")
        self.transient(master)
        self.resizable(False, False)
        self.columna = None

        self.var_nombre = tk.StringVar(value=columna.nombre if columna else "")
        self.var_desc = tk.StringVar(value=columna.descripcion if columna else "")
        self.var_tipo = tk.StringVar(value=columna.tipo if columna else TIPOS[0])
        self.var_ops = tk.StringVar(
            value=", ".join(columna.opciones) if columna else "")
        self.var_min = tk.StringVar(
            value="" if not columna or columna.minimo is None else str(columna.minimo))
        self.var_max = tk.StringVar(
            value="" if not columna or columna.maximo is None else str(columna.maximo))

        self._construir()
        self._al_cambiar_tipo()
        self.grab_set()
        self.wait_window(self)

    def _construir(self):
        m = ttk.Frame(self, padding=10)
        m.pack(fill="both", expand=True)
        m.columnconfigure(1, weight=1)

        ttk.Label(m, text="Nombre:").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(m, textvariable=self.var_nombre, width=44).grid(
            row=0, column=1, sticky="ew", pady=3)

        ttk.Label(m, text="Descripción:").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(m, textvariable=self.var_desc, width=44).grid(
            row=1, column=1, sticky="ew", pady=3)

        ttk.Label(m, text="Tipo:").grid(row=2, column=0, sticky="w", pady=3)
        combo = ttk.Combobox(m, textvariable=self.var_tipo, values=list(TIPOS),
                             state="readonly", width=20)
        combo.grid(row=2, column=1, sticky="w", pady=3)
        combo.bind("<<ComboboxSelected>>", lambda _e: self._al_cambiar_tipo())

        self.lbl_ayuda = ttk.Label(m, foreground="#555")
        self.lbl_ayuda.grid(row=3, column=1, sticky="w")

        self.lbl_ops = ttk.Label(m, text="Opciones:")
        self.lbl_ops.grid(row=4, column=0, sticky="w", pady=3)
        self.ent_ops = ttk.Entry(m, textvariable=self.var_ops, width=44)
        self.ent_ops.grid(row=4, column=1, sticky="ew", pady=3)
        self.lbl_ops_ayuda = ttk.Label(m, foreground="#555",
                                       text="separadas por comas")
        self.lbl_ops_ayuda.grid(row=5, column=1, sticky="w")

        self.marco_rango = ttk.Frame(m)
        self.marco_rango.grid(row=6, column=1, sticky="w", pady=3)
        ttk.Label(self.marco_rango, text="Mínimo:").pack(side="left")
        ttk.Entry(self.marco_rango, textvariable=self.var_min, width=8).pack(
            side="left", padx=(4, 12))
        ttk.Label(self.marco_rango, text="Máximo:").pack(side="left")
        ttk.Entry(self.marco_rango, textvariable=self.var_max, width=8).pack(
            side="left", padx=4)

        botones = ttk.Frame(m)
        botones.grid(row=7, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(botones, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(botones, text="Aceptar", command=self._aceptar).pack(
            side="right", padx=6)

    def _al_cambiar_tipo(self):
        tipo = self.var_tipo.get()
        self.lbl_ayuda.configure(text=AYUDA_TIPOS.get(tipo, ""))
        con_opciones = tipo in CON_OPCIONES
        for w in (self.lbl_ops, self.ent_ops, self.lbl_ops_ayuda):
            if con_opciones:
                w.grid()
            else:
                w.grid_remove()
        if tipo == TIPO_NUMERO:
            self.marco_rango.grid()
        else:
            self.marco_rango.grid_remove()

    def _numero(self, var, etiqueta):
        texto = var.get().strip().replace(",", ".")
        if not texto:
            return None
        try:
            return float(texto)
        except ValueError:
            raise ValueError("El %s debe ser un número." % etiqueta)

    def _aceptar(self):
        try:
            minimo = self._numero(self.var_min, "mínimo")
            maximo = self._numero(self.var_max, "máximo")
        except ValueError as exc:
            messagebox.showwarning("Dato inválido", str(exc), parent=self)
            return

        columna = Columna(
            nombre=self.var_nombre.get(),
            descripcion=self.var_desc.get(),
            tipo=self.var_tipo.get(),
            opciones=[o for o in self.var_ops.get().split(",")],
            minimo=minimo, maximo=maximo)

        fallos = columna.problemas()
        if fallos:
            messagebox.showwarning("Columna incompleta", "\n".join(fallos),
                                   parent=self)
            return
        self.columna = columna
        self.destroy()
