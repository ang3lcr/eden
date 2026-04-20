from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ThumbnailConfig:
    max_size: int = 220
    background: str = "#2b2b2b"


def pil_to_tk_image(pil_image: "object") -> "object":
    """
    Convierte una imagen PIL a una imagen compatible con Tkinter (PhotoImage).

    Implementación futura:
    - from PIL import ImageTk
    - return ImageTk.PhotoImage(pil_image)
    """
    raise NotImplementedError


def make_thumbnail(pil_image: "object", config: Optional[ThumbnailConfig] = None) -> "object":
    """
    Genera un thumbnail optimizado.

    Implementación futura:
    - pil_image.copy()
    - thumbnail((max_size, max_size))
    """
    raise NotImplementedError


def rotate_image(pil_image: "object", degrees: int) -> "object":
    """Rota una imagen (preview/UI)."""
    raise NotImplementedError


def cv2_gray(image: "object") -> "object":
    """Convierte a escala de grises usando OpenCV (si corresponde)."""
    raise NotImplementedError


def estimate_white_pixel_ratio(gray_image: "object") -> float:
    """Calcula el porcentaje de pixeles blancos (0..100)."""
    raise NotImplementedError

