from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Optional

try:
    from core.app_state import AppState
except Exception:  # pragma: no cover
    AppState = Any  # type: ignore


class SummaryScreen(tk.Frame):
    """Pantalla final: resumen y exportación."""

    def __init__(
        self,
        master: tk.Misc,
        state: Optional[AppState] = None,
        on_navigate: Optional[Callable[[str], None]] = None,
        *,
        on_exported: Optional[Callable[[], None]] = None,
    ):
        super().__init__(master)
        self.state = state
        self.on_navigate = on_navigate
        self._on_exported = on_exported
        self._build()

    def _build(self) -> None:
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="Resumen", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(top, text="Revisa los cambios antes de exportar.").pack(anchor="w", pady=(6, 0))

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        self._stats = ttk.LabelFrame(body, text="Cambios", padding=10)
        self._stats.pack(fill="x")

        self._lbl_deleted = ttk.Label(self._stats, text="Páginas eliminadas: 0")
        self._lbl_deleted.pack(anchor="w")
        self._lbl_rotated = ttk.Label(self._stats, text="Páginas rotadas: 0")
        self._lbl_rotated.pack(anchor="w")
        self._lbl_reordered = ttk.Label(self._stats, text="Reordenamiento: no")
        self._lbl_reordered.pack(anchor="w")
        self._lbl_cropped = ttk.Label(self._stats, text="Páginas recortadas: 0")
        self._lbl_cropped.pack(anchor="w")

        self._details = ttk.LabelFrame(body, text="Detalle", padding=10)
        self._details.pack(fill="both", expand=True, pady=(12, 0))
        self._text = tk.Text(self._details, height=10, wrap="word")
        self._text.pack(side="left", fill="both", expand=True)
        self._text.configure(state="disabled")
        self._text_scroll = ttk.Scrollbar(self._details, orient="vertical", command=self._text.yview)
        self._text.configure(yscrollcommand=self._text_scroll.set)
        self._text_scroll.pack(side="right", fill="y")

        actions = ttk.Frame(self, padding=12)
        actions.pack(fill="x")
        self._status = ttk.Label(actions, text="")
        self._status.pack(side="left", anchor="w")
        ttk.Button(actions, text="Inicio", command=self._go_home).pack(side="right", padx=(0, 8))
        ttk.Button(actions, text="Actualizar", command=self.refresh).pack(side="right", padx=(0, 8))
        ttk.Button(actions, text="Exportar PDF", command=self._export).pack(side="right")

        self.refresh()

    def refresh(self) -> None:
        deleted = len(getattr(self.state, "deleted_pages", []) or []) if self.state is not None else 0
        edits = getattr(self.state, "edits", None) if self.state is not None else None
        rotated = len(getattr(edits, "rotations", {}) or {}) if edits is not None else 0
        cropped = len(getattr(edits, "crops", {}) or {}) if edits is not None else 0
        page_order = getattr(self.state, "page_order", []) if self.state is not None else []
        reordered = bool(page_order)

        self._lbl_deleted.configure(text=f"Páginas eliminadas: {deleted}")
        self._lbl_rotated.configure(text=f"Páginas rotadas: {rotated}")
        self._lbl_reordered.configure(text=f"Reordenamiento: {'sí' if reordered else 'no'}")
        self._lbl_cropped.configure(text=f"Páginas recortadas: {cropped}")

        # Detalle textual
        lines: list[str] = []
        if self.state is None:
            lines.append("Modo demo: no hay estado cargado.")
        else:
            in_pdf = getattr(getattr(self.state, "paths", None), "input_pdf", None)
            out_pdf = getattr(getattr(self.state, "paths", None), "output_pdf", None)
            if in_pdf:
                lines.append(f"Entrada: {in_pdf}")
            if out_pdf:
                lines.append(f"Salida: {out_pdf}")

            deleted_pages = sorted(int(p) for p in (getattr(self.state, "deleted_pages", []) or []))
            if deleted_pages:
                lines.append(f"Páginas eliminadas ({len(deleted_pages)}): {self._fmt_pages(deleted_pages)}")

            rotations = getattr(edits, "rotations", {}) if edits is not None else {}
            if rotations:
                sample = ", ".join(f"{int(k)+1}→{int(v)}°" for k, v in sorted(rotations.items())[:30])
                lines.append(f"Rotaciones ({len(rotations)}): {sample}{'…' if len(rotations) > 30 else ''}")

            crops = getattr(edits, "crops", {}) if edits is not None else {}
            if crops:
                sample = ", ".join(f"{int(k)+1}" for k in sorted(crops.keys())[:40])
                lines.append(f"Recortes ({len(crops)}): {sample}{'…' if len(crops) > 40 else ''}")

            if page_order:
                lines.append(f"Orden final: {len(page_order)} páginas")

        self._set_text("\n".join(lines) if lines else "Sin cambios.")

    def _export(self) -> None:
        if self.state is None:
            messagebox.showinfo("Exportar", "No hay estado para exportar (modo demo).")
            return

        input_pdf = getattr(getattr(self.state, "paths", None), "input_pdf", None)
        if not input_pdf:
            messagebox.showwarning("Exportar", "Falta seleccionar el PDF de entrada.")
            return

        output_pdf = getattr(getattr(self.state, "paths", None), "output_pdf", None)
        if not output_pdf:
            messagebox.showwarning("Exportar", "Falta seleccionar el PDF de salida.")
            return

        # Usa directamente la ruta ya seleccionada al principio
        path = str(output_pdf)

        # Ejecuta exportación usando core/exporter.py (sin rasterizar)
        try:
            from core.exporter import PDFExporter

            self._status.configure(text="Exportando…")
            self.update_idletasks()
            PDFExporter().export(self.state, Path(path))
            self._status.configure(text="Exportación completada.")
            messagebox.showinfo("Exportar", "PDF exportado correctamente.")
            if self._on_exported is not None:
                self._on_exported()
        except Exception as exc:
            self._status.configure(text="Error al exportar.")
            messagebox.showerror("Exportar", f"No se pudo exportar:\n{exc}")

    def _go_home(self) -> None:
        """Regresa a la pantalla de inicio para seleccionar otro archivo."""
        if self.on_navigate is not None:
            self.on_navigate("start")

    def _set_text(self, content: str) -> None:
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("1.0", content)
        self._text.configure(state="disabled")

    def _fmt_pages(self, pages0: list[int]) -> str:
        # Formatea páginas 0-indexadas a 1-indexadas de manera compacta (rangos)
        pages = sorted(set(int(p) for p in pages0))
        out: list[str] = []
        start = prev = None
        for p in pages:
            if start is None:
                start = prev = p
                continue
            if p == prev + 1:
                prev = p
                continue
            out.append(self._fmt_range(start, prev))
            start = prev = p
        if start is not None and prev is not None:
            out.append(self._fmt_range(start, prev))
        return ", ".join(out)

    def _fmt_range(self, a0: int, b0: int) -> str:
        a = a0 + 1
        b = b0 + 1
        return f"{a}" if a == b else f"{a}-{b}"

