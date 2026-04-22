from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from core.app_state import CropMargins


@dataclass(frozen=True)
class CropConfig:
    """Config de recorte."""
    clamp_to_bounds: bool = True
    min_size_px: int = 2


class Cropper:
    """
    Aplica recortes a una imagen o a una página PDF.
    """

    def __init__(self, config: Optional[CropConfig] = None):
        self.config = config or CropConfig()

    def apply_crop_to_image(self, image: "object", margins: CropMargins) -> "object":
        from PIL import Image
        if not isinstance(image, Image.Image):
            raise TypeError("apply_crop_to_image espera una instancia de PIL.Image.Image")

        l, t, r, b = (int(margins[0]), int(margins[1]), int(margins[2]), int(margins[3]))
        w, h = image.size

        x0, y0, x1, y1 = l, t, w - r, h - b

        if self.config.clamp_to_bounds:
            x0 = max(0, min(x0, w))
            y0 = max(0, min(y0, h))
            x1 = max(0, min(x1, w))
            y1 = max(0, min(y1, h))

        return image.crop((x0, y0, x1, y1))

    def margins_to_rect_px(self, image_size: Tuple[int, int], margins: CropMargins) -> Tuple[int, int, int, int]:
        w, h = int(image_size[0]), int(image_size[1])
        l, t, r, b = (int(margins[0]), int(margins[1]), int(margins[2]), int(margins[3]))
        x0, y0, x1, y1 = l, t, w - r, h - b
        return (x0, y0, x1, y1)

    def apply_crop_to_pdf_page(self, page: "object", margins: CropMargins) -> None:
        """
        Aplica recorte a una página PDF usando matrices de transformación.
        Esto resuelve problemas de rotación de 90, 180 o 270 grados.
        """
        import fitz  # PyMuPDF

        if not hasattr(page, "rect") or not hasattr(page, "set_cropbox"):
            raise TypeError("apply_crop_to_pdf_page espera un fitz.Page")

        # 1. Obtener dimensiones visuales actuales (ya consideran la rotación)
        # page.rect nos da el rectángulo tal como se ve en pantalla
        v_rect = page.rect
        l, t, r, b = (float(margins[0]), float(margins[1]), float(margins[2]), float(margins[3]))

        # Debug
        print(f"DEBUG APPLY_CROP: page.rect={v_rect}, margins (pt)=({l:.1f},{t:.1f},{r:.1f},{b:.1f})")

        # 2. Definir el nuevo área de visualización (Crop) en espacio VISUAL
        # y0 es arriba, y1 es abajo. Sumamos 't' para bajar el borde superior,
        # restamos 'b' para subir el borde inferior.
        vx0 = v_rect.x0 + l
        vy0 = v_rect.y0 + t
        vx1 = v_rect.x1 - r
        vy1 = v_rect.y1 - b

        print(f"DEBUG APPLY_CROP: visual_crop_rect=({vx0:.1f},{vy0:.1f},{vx1:.1f},{vy1:.1f})")

        # Asegurar que el recorte no invierta la página o sea demasiado pequeño
        if vx1 <= vx0 + 1 or vy1 <= vy0 + 1:
            print(f"DEBUG APPLY_CROP: Recorte demasiado pequeño o invertido, ignorando")
            return

        visual_crop_rect = fitz.Rect(vx0, vy0, vx1, vy1)

        # 3. Transformar el rectángulo visual al espacio de coordenadas INTERNO
        # La matriz de rotación de la página mapea Interno -> Visual.
        # La matriz inversa (~matriz) mapea Visual -> Interno.
        try:
            # ~ es el operador para la matriz inversa en PyMuPDF
            internal_crop_rect = visual_crop_rect * ~page.rotation_matrix
            
            print(f"DEBUG APPLY_CROP: internal_crop_rect={internal_crop_rect}")
            
            # 4. Aplicar el recorte al CropBox interno del PDF
            page.set_cropbox(internal_crop_rect)
        except Exception as e:
            # Fallback simple en caso de que la matriz sea singular (poco común)
            print(f"DEBUG APPLY_CROP: Error con rotation_matrix: {e}, usando visual rect")
            page.set_cropbox(visual_crop_rect)