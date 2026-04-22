from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Set

from core.app_state import AppState
from core.cropper import Cropper


@dataclass(frozen=True)
class ExportConfig:
    """
    Configuración de exportación.

    Implementación futura:
    - mantener calidad original
    - opciones de compresión / subset fonts, etc.
    """

    keep_quality: bool = True


class PDFExporter:
    """
    Exporta un nuevo PDF aplicando:
    - eliminación de páginas
    - rotaciones
    - orden
    - recortes

    Implementación futura: usar PyMuPDF (fitz) para rearmar el documento.
    """

    def __init__(self, config: Optional[ExportConfig] = None):
        self.config = config or ExportConfig()

    def export(self, state: AppState, output_path: Path) -> None:
        """
        Crea un nuevo PDF aplicando transformaciones sin rasterizar (mantiene calidad).

        Estrategia:
        - abre PDF fuente con PyMuPDF
        - construye lista final de páginas (orden + eliminadas)
        - inserta páginas 1 por 1 en el documento destino (insert_pdf)
        - aplica cropbox y rotación sobre las páginas ya copiadas
        - guarda el nuevo PDF
        """
        import fitz  # PyMuPDF

        input_path = state.paths.input_pdf
        if input_path is None:
            raise ValueError("state.paths.input_pdf no está definido.")
        if not input_path.exists():
            raise FileNotFoundError(f"No existe el PDF de entrada: {input_path}")

        output_path = Path(output_path)
        if output_path.suffix.lower() != ".pdf":
            output_path = output_path.with_suffix(".pdf")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        deleted: Set[int] = set(int(p) for p in (state.deleted_pages or []))

        with fitz.open(str(input_path)) as src:
            src_count = int(src.page_count)

            # Orden final: si no hay, por defecto 0..N-1
            if state.page_order:
                order = [int(p) for p in state.page_order]
            else:
                order = list(range(src_count))

            # Filtra eliminadas y valida rangos
            final_pages: list[int] = []
            for p in order:
                if p in deleted:
                    continue
                if p < 0 or p >= src_count:
                    raise IndexError(f"Índice de página fuera de rango en page_order: {p}")
                final_pages.append(p)

            if not final_pages:
                raise ValueError("No hay páginas para exportar (todas eliminadas o lista vacía).")

            out = fitz.open()
            cropper = Cropper()
            try:
                # Copia páginas (sin rasterizar) en el orden final
                for p in final_pages:
                    out.insert_pdf(src, from_page=p, to_page=p)

                # Aplica transformaciones en páginas destino (índices 0..len-1)
                for out_idx, src_page_idx in enumerate(final_pages):
                    page = out.load_page(out_idx)

                    # Recorte:
                    # En la UI guardamos márgenes en "pixeles de preview". Para mantener calidad (sin rasterizar),
                    # convertimos esos pixeles a puntos (pt) usando una renderización mínima solo para obtener escala.
                    margins = state.edits.crops.get(src_page_idx)
                    if margins is not None:
                        try:
                            pt_margins = self._crop_margins_px_to_pt(src, int(src_page_idx), margins)
                            cropper.apply_crop_to_pdf_page(page, pt_margins)
                        except Exception:
                            # Si la conversión falla, evitamos romper exportación completa.
                            pass

                    # Rotación (grados)
                    rot = int(state.edits.rotations.get(src_page_idx, 0)) % 360
                    if rot in (0, 90, 180, 270) and rot != 0:
                        page.set_rotation(rot)

                # Guardado: garbage/deflate para limpiar sin degradar contenido vectorial
                out.save(
                    str(output_path),
                    garbage=4,
                    deflate=True,
                    clean=True,
                )
            finally:
                out.close()

    def _crop_margins_px_to_pt(self, src: "fitz.Document", src_page_idx: int, margins_px: "object") -> "object":
        """
        Convierte márgenes guardados desde la UI (px a 150 DPI) a puntos PDF (pt).

        IMPORTANTE: Los márgenes se guardan desde CropEditor que renderiza a 150 DPI.
        Para consistencia, renderizamos también a 150 DPI aquí.

        Estrategia:
        - obtiene MediaBox (pt) de la página fuente
        - renderiza a 150 dpi (misma que CropEditor) para obtener tamaño en píxeles
        - convierte px->pt proporcionalmente por eje

        Esto mantiene calidad porque el recorte final se aplica como cropbox, no rasteriza.
        """
        import fitz  # PyMuPDF
        from PIL import Image

        lpx, tpx, rpx, bpx = (float(margins_px[0]), float(margins_px[1]), float(margins_px[2]), float(margins_px[3]))

        src_page = src.load_page(int(src_page_idx))
        media = getattr(src_page, "rect", None) or src_page.mediabox  # Usar rect para considerar rotación
        w_pt = float(media.width)
        h_pt = float(media.height)

        # Renderizar a 150 DPI (mismo que en CropEditor) para que los márgenes sean consistentes
        # 150 DPI = escala de 150/72 ≈ 2.083 en relación a 72 DPI
        scale_150dpi = 150.0 / 72.0
        pix = src_page.get_pixmap(matrix=fitz.Matrix(scale_150dpi, scale_150dpi), alpha=False)
        w_px = float(pix.width) if pix.width else 1.0
        h_px = float(pix.height) if pix.height else 1.0

        # Debug: mostrar conversión
        print(f"DEBUG CROP: PDF size={w_pt:.1f}pt x {h_pt:.1f}pt, Render size={w_px:.0f}px x {h_px:.0f}px")
        print(f"DEBUG CROP: Margins (px, 150 DPI)={lpx:.0f},{tpx:.0f},{rpx:.0f},{bpx:.0f}")

        lpt = (lpx / w_px) * w_pt
        rpt = (rpx / w_px) * w_pt
        tpt = (tpx / h_px) * h_pt
        bpt = (bpx / h_px) * h_pt

        # Clamp a no negativos
        lpt = max(0.0, lpt)
        rpt = max(0.0, rpt)
        tpt = max(0.0, tpt)
        bpt = max(0.0, bpt)

        print(f"DEBUG CROP: Margins (pt)={lpt:.1f},{tpt:.1f},{rpt:.1f},{bpt:.1f}")

        return (lpt, tpt, rpt, bpt)

