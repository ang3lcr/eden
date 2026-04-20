from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from core.app_state import PageIndex


@dataclass(frozen=True)
class BlankDetectionConfig:
    """
    Configuración del detector.

    - white_threshold_percent: si el % de pixeles blancos >= este valor, se considera “en blanco”
    - white_pixel_value_threshold: umbral (0..255) para decidir si un pixel es “blanco” en gris

    Nota: en escaneos reales suele convenir 240-250 para tolerar ruido/compresión.
    """

    white_threshold_percent: float = 95.0
    white_pixel_value_threshold: int = 245


@dataclass(frozen=True)
class BlankDetectionResult:
    blank_pages: List[PageIndex]


class BlankPageDetector:
    """
    Detector de hojas en blanco.

    Implementación futura (OpenCV/Pillow):
    - convertir página a imagen
    - escala de grises
    - calcular % pixeles blancos
    """

    def __init__(self, config: BlankDetectionConfig):
        self.config = config

    def detect(self, page_images: Iterable["object"]) -> BlankDetectionResult:
        """
        page_images: iterables de imágenes (Pillow).
        Retorna índices relativos (0..n-1) del iterable; el orquestador mapeará a PageIndex real.
        """
        self._validate_config()

        import cv2  # type: ignore
        import numpy as np  # type: ignore

        blank: List[PageIndex] = []

        for i, img in enumerate(page_images):
            gray = self._to_gray_cv(img, cv2=cv2, np=np)
            if gray is None:
                # Si una página no se puede analizar, por defecto NO se marca como blanco.
                continue

            white_ratio = self._white_ratio_percent(gray, cv2=cv2, np=np)
            if white_ratio >= float(self.config.white_threshold_percent):
                blank.append(int(i))

        return BlankDetectionResult(blank_pages=blank)

    def is_blank(self, page_image: "object") -> bool:
        """Conveniencia: evalúa una sola página."""
        return bool(self.detect([page_image]).blank_pages)

    def _validate_config(self) -> None:
        if not (0.0 <= float(self.config.white_threshold_percent) <= 100.0):
            raise ValueError("white_threshold_percent debe estar entre 0 y 100.")
        t = int(self.config.white_pixel_value_threshold)
        if t < 0 or t > 255:
            raise ValueError("white_pixel_value_threshold debe estar entre 0 y 255.")

    def _to_gray_cv(self, image: "object", *, cv2: "object", np: "object") -> Optional["object"]:
        """
        Convierte imagen a grayscale numpy array usando OpenCV.

        Acepta:
        - PIL.Image
        - numpy ndarray en RGB/BGR/GRAY
        """
        # Numpy array directo
        if hasattr(image, "shape") and hasattr(image, "dtype"):
            arr = image
        else:
            # PIL.Image u otro objeto convertible a array
            try:
                arr = np.array(image)
            except Exception:
                return None

        if arr is None:
            return None

        # Normaliza canales
        if len(getattr(arr, "shape", ())) == 2:
            # Ya es gris
            gray = arr
        elif len(arr.shape) == 3 and arr.shape[2] == 4:
            # RGBA -> Gray
            gray = cv2.cvtColor(arr, cv2.COLOR_RGBA2GRAY)
        elif len(arr.shape) == 3 and arr.shape[2] == 3:
            # Asumimos RGB (PIL entrega RGB). Si viniera BGR, la diferencia es pequeña para “blanco”.
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        else:
            return None

        # Asegura uint8
        if gray.dtype != np.uint8:
            gray = gray.astype(np.uint8, copy=False)
        return gray

    def _white_ratio_percent(self, gray: "object", *, cv2: "object", np: "object") -> float:
        """
        Calcula porcentaje de pixeles blancos:
        white = gray >= white_pixel_value_threshold
        """
        thresh_val = int(self.config.white_pixel_value_threshold)

        # mask = gray >= thresh_val (más rápido con threshold binario)
        _, mask = cv2.threshold(gray, thresh_val, 255, cv2.THRESH_BINARY)
        white_pixels = int(np.count_nonzero(mask))
        total = int(gray.size) if int(gray.size) > 0 else 1
        return (white_pixels / total) * 100.0

