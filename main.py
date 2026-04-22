"""
Aplicación de escritorio para procesar PDFs escaneados.

Este proyecto está diseñado con arquitectura modular:
- ui/: interfaz Tkinter (pantallas y widgets)
- core/: lógica de dominio y procesamiento (PDF/imagen)
- utils/: utilidades (imágenes, concurrencia, etc.)
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import messagebox

from core.app_state import AppState
from core.blank_detector import BlankDetectionConfig, BlankPageDetector
from core.orientation_detector import OrientationDetectionConfig, OrientationDetector
from core.pdf_loader import PDFLoader
from ui.blank_pages_screen import BlankPagesScreen
from ui.orientation_screen import OrientationScreen
from ui.reorder_screen import ReorderScreen
from ui.start_screen import StartScreen
from ui.summary_screen import SummaryScreen

from ui.app import App


@dataclass
class ProcessingContext:
    loader: PDFLoader


class Controller:
    """
    Orquestador (controlador) de la app.

    Mantiene:
    - estado global (AppState) en `app.state`
    - loader abierto del PDF actual
    - navegación entre pantallas
    - ejecución de procesamiento según opciones (blank/orientation)

    Importante: la lógica pesada vive en core/; aquí solo se coordina.
    """

    def __init__(self, app: App):
        self.app = app
        self.state: AppState = app.state
        self.ctx: ProcessingContext | None = None

    def dispose(self) -> None:
        if self.ctx is not None:
            try:
                self.ctx.loader.close()
            except Exception:
                pass
            self.ctx = None

    # ------------------
    # Start / pipeline
    # ------------------

    def start_processing(
        self,
        input_pdf: str,
        output_pdf: str = "",
        detect_blank: bool = True,
        detect_orient: bool = True,
        threshold: float = 95.0,
        *,
        progress_cb: "callable | None" = None,
    ) -> None:
        try:
            if not output_pdf.strip():
                # Si no hay output definido, pedir seleccionar
                from tkinter import filedialog
                output_pdf = filedialog.asksaveasfilename(
                    title="Seleccionar PDF de salida",
                    defaultextension=".pdf",
                    filetypes=[("PDF", "*.pdf")],
                )
                if not output_pdf:
                    self._ui(lambda: messagebox.showerror("Procesar", "Debes seleccionar un archivo de salida."))
                    return
            
            self._set_options_and_paths(input_pdf, output_pdf, detect_blank, detect_orient, threshold)
            self._open_pdf()
            self._run_selected_processing(progress_cb=progress_cb)
            self._ui(self._navigate_next_from_start)
        except Exception as exc:
            self._ui(lambda: messagebox.showerror("Procesar", f"No se pudo procesar:\n{exc}"))
            raise

    def _set_options_and_paths(self, input_pdf: str, output_pdf: str, detect_blank: bool, detect_orient: bool, threshold: float) -> None:
        self.state.paths.input_pdf = Path(input_pdf) if input_pdf else None
        self.state.paths.output_pdf = Path(output_pdf) if output_pdf else None
        self.state.options.detect_blank_pages = bool(detect_blank)
        self.state.options.detect_orientation = bool(detect_orient)
        self.state.options.blank_threshold_percent = float(threshold)

    def _open_pdf(self) -> None:
        self.dispose()

        if self.state.paths.input_pdf is None:
            raise ValueError("Selecciona un PDF de entrada.")
        loader = PDFLoader(self.state.paths.input_pdf, thumbnail_cache_size=256)
        loader.open()

        self.state.total_pages = loader.metadata.page_count
        if not self.state.page_order:
            self.state.page_order = list(range(self.state.total_pages))

        self.ctx = ProcessingContext(loader=loader)

    def _run_selected_processing(self, *, progress_cb: "callable | None" = None) -> None:
        if self.ctx is None:
            raise RuntimeError("Contexto no inicializado.")

        # Reset resultados previos
        self.state.detected_blank_pages = []
        self.state.kept_blank_pages = []
        self.state.deleted_pages = []
        self.state.detected_misoriented_pages = []

        total_pages = int(self.state.total_pages or self.ctx.loader.metadata.page_count)
        processed = 0

        def report(message: str) -> None:
            if progress_cb is None:
                return
            progress_cb(current=processed, total=max(1, total_pages), message=message)

        # Detectar blanco (paralelo, sin cargar todo)
        if self.state.options.detect_blank_pages:
            cfg = BlankDetectionConfig(white_threshold_percent=float(self.state.options.blank_threshold_percent))
            detector = BlankPageDetector(cfg)

            report("Detectando hojas en blanco…")

            pdf_path = self.state.paths.input_pdf
            assert pdf_path is not None

            from concurrent.futures import ThreadPoolExecutor, as_completed
            import fitz
            from PIL import Image

            tl = threading.local()

            def get_doc() -> "fitz.Document":
                doc = getattr(tl, "doc", None)
                if doc is None:
                    doc = fitz.open(str(pdf_path))
                    tl.doc = doc
                return doc

            def is_blank_page(p: int) -> tuple[int, bool]:
                doc = get_doc()
                page = doc.load_page(int(p))
                scale = 110.0 / 72.0
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                return (int(p), detector.is_blank(img))

            workers = min(8, max(2, (os.cpu_count() or 4)))
            blank_pages: list[int] = []
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(is_blank_page, int(p)) for p in range(total_pages)]
                for fut in as_completed(futures):
                    p, is_blank = fut.result()
                    if is_blank:
                        blank_pages.append(int(p))
                    processed += 1
                    if processed % 5 == 0 or processed == total_pages:
                        report("Detectando hojas en blanco…")

            doc = getattr(tl, "doc", None)
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass
            self.state.detected_blank_pages = blank_pages
            # Por defecto: eliminar todas las detectadas como blanco.
            # El usuario seleccionará en la UI cuáles conservar.
            self.state.kept_blank_pages = []
            self.state.deleted_pages = sorted(int(p) for p in blank_pages)

        # Detectar orientación (solo si se pide)
        if self.state.options.detect_orientation:
            o_detector = OrientationDetector(OrientationDetectionConfig())
            processed = 0
            report("Detectando orientación…")

            pdf_path = self.state.paths.input_pdf
            assert pdf_path is not None

            from concurrent.futures import ThreadPoolExecutor, as_completed
            import fitz
            from PIL import Image

            tl = threading.local()

            def get_doc() -> "fitz.Document":
                doc = getattr(tl, "doc", None)
                if doc is None:
                    doc = fitz.open(str(pdf_path))
                    tl.doc = doc
                return doc

            def detect_rotation(p: int) -> tuple[int, int]:
                doc = get_doc()
                page = doc.load_page(int(p))
                scale = 110.0 / 72.0
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                rot = o_detector.suggest_rotation_for_image(img)
                return (int(p), int(rot) if rot is not None else 0)

            workers = min(8, max(2, (os.cpu_count() or 4)))
            suggested: dict[int, int] = {}
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(detect_rotation, int(p)) for p in range(total_pages)]
                for fut in as_completed(futures):
                    p, rot = fut.result()
                    if rot % 360 != 0:
                        suggested[int(p)] = int(rot)
                    processed += 1
                    if processed % 5 == 0 or processed == total_pages:
                        report("Detectando orientación…")

            doc = getattr(tl, "doc", None)
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass

            self.state.detected_misoriented_pages = sorted(suggested.keys())
            # Pre-carga sugerencias en edits (el usuario puede cambiarlas)
            for p, deg in suggested.items():
                self.state.edits.rotations[p] = int(deg)

        if progress_cb is not None:
            progress_cb(current=total_pages, total=max(1, total_pages), message="Listo.")

    def _navigate_next_from_start(self) -> None:
        # Si hay blank detectadas y opción activa → pantalla blank
        if self.state.options.detect_blank_pages and self.state.detected_blank_pages:
            self.app.show("blank")
            return
        # Si hay orientaciones detectadas y opción activa → pantalla orientation
        if self.state.options.detect_orientation and self.state.detected_misoriented_pages:
            self.app.show("orientation")
            return
        # Si no, reordenamiento
        self.app.show("reorder")

    # ------------------
    # Screen helpers
    # ------------------

    def blank_page_indices(self) -> list[int]:
        return [int(p) for p in (self.state.detected_blank_pages or [])]

    def misoriented_page_indices(self) -> list[int]:
        return [int(p) for p in (self.state.detected_misoriented_pages or [])]

    def all_page_indices(self) -> list[int]:
        deleted = set(int(p) for p in (self.state.deleted_pages or []))
        order = self.state.page_order or list(range(int(self.state.total_pages or 0)))
        return [int(p) for p in order if int(p) not in deleted]

    def thumbnail_provider(self, page_idx: int, size: int) -> "object":
        if self.ctx is None:
            raise RuntimeError("PDF no cargado.")
        # size se usa como max_size
        return self.ctx.loader.render_thumbnail(int(page_idx), max_size=int(size))

    # ------------------
    # Screen transitions
    # ------------------

    def on_blank_continue(self) -> None:
        detected = set(int(p) for p in (self.state.detected_blank_pages or []))
        kept = set(int(p) for p in (self.state.kept_blank_pages or []))
        deleted = sorted(detected - kept)
        self.state.deleted_pages = deleted

        if self.state.options.detect_orientation and self.state.detected_misoriented_pages:
            self.app.show("orientation")
        else:
            self.app.show("reorder")

    def on_orientation_continue(self) -> None:
        self.app.show("reorder")

    def on_reorder_continue(self) -> None:
        self.app.show("summary")

    def _ui(self, fn: "callable") -> None:
        try:
            self.app.after(0, fn)
        except Exception:
            fn()


def main() -> None:
    root = tk.Tk()
    root.title("PDF Scanner Processor")
    root.geometry("1200x800")
    root.minsize(900, 650)

    try:
        app = App(root)
        controller = Controller(app)

        # Registro de pantallas con factories (inyección de callbacks/datos)
        app.register_screen(
            "start",
            lambda parent, state, nav: StartScreen(
                parent,
                state,
                nav,
                on_process=controller.start_processing,
            ),
        )
        app.register_screen(
            "blank",
            lambda parent, state, nav: BlankPagesScreen(
                parent,
                state,
                nav,
                page_indices=controller.blank_page_indices(),
                thumbnail_provider=controller.thumbnail_provider,
                on_continue=controller.on_blank_continue,
            ),
        )
        app.register_screen(
            "orientation",
            lambda parent, state, nav: OrientationScreen(
                parent,
                state,
                nav,
                page_indices=controller.misoriented_page_indices(),
                thumbnail_provider=controller.thumbnail_provider,
                on_continue=controller.on_orientation_continue,
            ),
        )
        app.register_screen(
            "reorder",
            lambda parent, state, nav: ReorderScreen(
                parent,
                state,
                nav,
                thumbnail_provider=controller.thumbnail_provider,
                pdf_loader=controller.ctx.loader if controller.ctx else None,
                on_continue=controller.on_reorder_continue,
            ),
        )
        app.register_screen("summary", lambda parent, state, nav: SummaryScreen(parent, state, nav))

        # Asegura que al cerrar se liberen recursos
        def _on_close() -> None:
            controller.dispose()
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", _on_close)

        # Re-muestra start (para aplicar factory con callbacks)
        app.show("start")
        app.pack(fill="both", expand=True)
        root.mainloop()
    except Exception as exc:
        # Fallback: evita cerrar “silenciosamente” ante errores inesperados.
        messagebox.showerror("Error", f"Error inesperado:\n{exc}")
        raise


if __name__ == "__main__":
    main()

