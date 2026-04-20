from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from tkinter import filedialog, ttk
from typing import Any, Callable, Optional

import threading


class StartScreen(tk.Frame):
    """Pantalla inicial: selección de PDF, salida y opciones de procesamiento."""

    def __init__(
        self,
        master: tk.Misc,
        state: Optional[Any] = None,
        on_navigate: Optional[Callable[[str], None]] = None,
        *,
        on_process: Optional[Callable[..., None]] = None,
    ):
        super().__init__(master)
        # Se acepta `state`/`on_navigate` para compatibilidad con el contenedor App,
        # pero esta pantalla es UI autónoma y no depende de core/.
        self._state = state
        self._on_navigate = on_navigate
        self._on_process = on_process

        self._build()

    def _build(self) -> None:
        header = ttk.Frame(self, padding=12)
        header.pack(fill="x")

        ttk.Label(header, text="Procesador de PDFs escaneados", font=("Segoe UI", 16, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            header,
            text="Selecciona un PDF, define salida y elige qué procesos ejecutar.",
        ).pack(anchor="w", pady=(6, 0))

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        # Entrada
        in_row = ttk.Frame(body)
        in_row.pack(fill="x", pady=(0, 8))
        ttk.Label(in_row, text="PDF de entrada:").pack(side="left")
        self._in_var = tk.StringVar(value="")
        ttk.Entry(in_row, textvariable=self._in_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(in_row, text="Seleccionar…", command=self._pick_input).pack(side="left")

        # Salida
        out_row = ttk.Frame(body)
        out_row.pack(fill="x", pady=(0, 12))
        ttk.Label(out_row, text="PDF de salida:").pack(side="left")
        self._out_var = tk.StringVar(value="")
        ttk.Entry(out_row, textvariable=self._out_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(out_row, text="Elegir…", command=self._pick_output).pack(side="left")

        # Opciones
        options_box = ttk.LabelFrame(body, text="Procesos", padding=10)
        options_box.pack(fill="x")

        self._blank_var = tk.BooleanVar(value=True)
        self._orient_var = tk.BooleanVar(value=True)

        ttk.Checkbutton(
            options_box,
            text="Detectar hojas en blanco",
            variable=self._blank_var,
        ).pack(anchor="w")
        ttk.Checkbutton(
            options_box,
            text="Detectar hojas mal orientadas",
            variable=self._orient_var,
        ).pack(anchor="w")

        # Umbral (stub)
        threshold_row = ttk.Frame(options_box)
        threshold_row.pack(fill="x", pady=(8, 0))
        ttk.Label(threshold_row, text="Umbral blanco (%):").pack(side="left")
        self._threshold_var = tk.DoubleVar(value=95.0)
        ttk.Entry(threshold_row, textvariable=self._threshold_var, width=8).pack(side="left", padx=8)
        ttk.Label(threshold_row, text="(ej: 95.0)").pack(side="left")

        # Acciones
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(16, 0))
        self._btn_process = ttk.Button(actions, text="Procesar", command=self._start_processing)
        self._btn_process.pack(side="right")

        self._status = ttk.Label(actions, text="")
        self._status.pack(side="left", anchor="w")

        # Barra de progreso
        self._progress = ttk.Progressbar(body, mode="determinate")
        self._progress.pack(fill="x", pady=(18, 0))

    def set_progress(self, *, current: int, total: int, message: str = "") -> None:
        """
        Actualiza progreso desde cualquier hilo (programa el update en el hilo UI).
        """
        def _apply() -> None:
            try:
                if not self.winfo_exists():
                    return
                self._progress.configure(mode="determinate", maximum=max(1, int(total)))
                self._progress.configure(value=max(0, min(int(current), int(total))))
                self._status.configure(text=message or "")
                self._progress.update_idletasks()
            except tk.TclError:
                return

        self.after(0, _apply)

    def set_busy(self, message: str = "") -> None:
        def _apply() -> None:
            try:
                if not self.winfo_exists():
                    return
                self._status.configure(text=message or "")
                self._progress.configure(mode="indeterminate")
                self._progress.start(10)
                self._btn_process.configure(state="disabled")
            except tk.TclError:
                return

        self.after(0, _apply)

    def set_idle(self) -> None:
        def _apply() -> None:
            try:
                if not self.winfo_exists():
                    return
                self._progress.stop()
                self._progress.configure(mode="determinate", value=0)
                self._status.configure(text="")
                self._btn_process.configure(state="normal")
            except tk.TclError:
                return

        self.after(0, _apply)

    def _pick_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Seleccionar PDF",
            filetypes=[("PDF", "*.pdf")],
        )
        if not path:
            return
        self._in_var.set(path)

    def _pick_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Ruta de salida",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not path:
            return
        self._out_var.set(path)

    def _start_processing(self) -> None:
        """
        Inicia el pipeline seleccionado.

        Si `on_process` está definido, delega al controlador externo.
        """
        input_pdf = self._in_var.get().strip()
        output_pdf = self._out_var.get().strip()
        detect_blank = bool(self._blank_var.get())
        detect_orient = bool(self._orient_var.get())
        try:
            threshold = float(self._threshold_var.get())
        except Exception:
            threshold = 95.0

        if self._on_process is None:
            # Fallback demo
            msg = (
                "Configuración lista (UI):\n\n"
                f"- Entrada: {input_pdf or '(sin seleccionar)'}\n"
                f"- Salida: {output_pdf or '(sin seleccionar)'}\n"
                f"- Detectar blanco: {'sí' if detect_blank else 'no'} (umbral {threshold:.1f}%)\n"
                f"- Detectar orientación: {'sí' if detect_orient else 'no'}\n"
            )
            messagebox.showinfo("Procesar (demo UI)", msg)
            return

        # Corre en background thread para no congelar la UI
        self.set_busy("Procesando…")

        def _run() -> None:
            try:
                # El controlador puede aceptar `progress_cb` como kwarg.
                self._on_process(
                    input_pdf,
                    output_pdf,
                    detect_blank,
                    detect_orient,
                    float(threshold),
                    progress_cb=self.set_progress,
                )
            except Exception:
                # El controlador ya muestra messagebox; solo regresamos a idle.
                pass
            finally:
                self.set_idle()

        threading.Thread(target=_run, daemon=True).start()

