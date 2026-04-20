from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from core.app_state import PageIndex, RotationDegrees


@dataclass(frozen=True)
class OrientationDetectionConfig:
    """
    Configuración de heurísticas.

    Heurística principal:
    - evaluar 0/90/180/270 y escoger la rotación que maximice “texto horizontal”

    Parámetros:
    - min_confidence_delta: diferencia mínima entre el mejor score y el segundo para aceptar decisión
    - max_image_side: si la imagen es enorme, se reduce para acelerar análisis
    - binarization: umbrales para obtener máscara de “tinta”
    """

    enable_heuristics: bool = True
    min_confidence_delta: float = 0.08
    max_image_side: int = 1600
    adaptive_thresh_blocksize: int = 51
    adaptive_thresh_C: int = 15
    morph_kernel: int = 25


@dataclass(frozen=True)
class OrientationDetectionResult:
    """
    suggested_rotations: rotación sugerida por página (grados 0/90/180/270)
    """

    suggested_rotations: Dict[PageIndex, RotationDegrees]


class OrientationDetector:
    """
    Detector de orientación incorrecta.

    Implementación futura (OpenCV):
    - detección de líneas / contornos
    - heurística texto horizontal vs vertical
    - estimación 90/180/270
    """

    def __init__(self, config: OrientationDetectionConfig):
        self.config = config

    def detect(self, images_by_page: Dict[PageIndex, "object"]) -> OrientationDetectionResult:
        if not self.config.enable_heuristics:
            return OrientationDetectionResult(suggested_rotations={})

        suggested: Dict[PageIndex, RotationDegrees] = {}
        for page_idx, img in images_by_page.items():
            rot = self.suggest_rotation_for_image(img)
            if rot is None:
                continue
            if int(rot) % 360 != 0:
                suggested[int(page_idx)] = int(rot)
        return OrientationDetectionResult(suggested_rotations=suggested)

    def suggest_rotation_for_image(self, image: "object") -> Optional[RotationDegrees]:
        """Retorna rotación sugerida para una imagen o None si no concluyente."""
        if not self.config.enable_heuristics:
            return None

        import cv2  # type: ignore
        import numpy as np  # type: ignore

        gray = self._to_gray(image, cv2=cv2, np=np)
        if gray is None:
            return None

        gray = self._downscale_if_needed(gray, cv2=cv2)
        ink = self._ink_mask(gray, cv2=cv2)
        if ink is None:
            return None

        # Evalúa las 4 orientaciones y selecciona la mejor.
        scores: Dict[int, float] = {}
        for rot in (0, 90, 180, 270):
            rotated = self._rotate90(ink, rot, cv2=cv2)
            scores[rot] = self._score_upright(rotated, cv2=cv2, np=np)

        # Mejor y segundo mejor para medir confianza
        best_rot, best_score = max(scores.items(), key=lambda kv: kv[1])
        second_score = sorted(scores.values(), reverse=True)[1]

        if (best_score - second_score) < float(self.config.min_confidence_delta):
            return None

        # best_rot es la orientación “upright”; necesitamos sugerir cuántos grados rotar
        # la imagen original para llegar ahí.
        suggested: RotationDegrees = int(best_rot)  # rotación a aplicar a la imagen original
        return suggested

    def _to_gray(self, image: "object", *, cv2: "object", np: "object") -> Optional["object"]:
        # numpy directo
        if hasattr(image, "shape") and hasattr(image, "dtype"):
            arr = image
        else:
            try:
                arr = np.array(image)
            except Exception:
                return None

        if arr is None:
            return None

        if len(getattr(arr, "shape", ())) == 2:
            gray = arr
        elif len(arr.shape) == 3 and arr.shape[2] == 4:
            gray = cv2.cvtColor(arr, cv2.COLOR_RGBA2GRAY)
        elif len(arr.shape) == 3 and arr.shape[2] == 3:
            # PIL suele entregar RGB
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        else:
            return None

        if gray.dtype != np.uint8:
            gray = gray.astype(np.uint8, copy=False)
        return gray

    def _downscale_if_needed(self, gray: "object", *, cv2: "object") -> "object":
        h, w = gray.shape[:2]
        max_side = int(self.config.max_image_side)
        if max_side <= 0:
            return gray
        m = max(h, w)
        if m <= max_side:
            return gray
        scale = max_side / float(m)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        return cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_AREA)

    def _ink_mask(self, gray: "object", *, cv2: "object") -> Optional["object"]:
        """
        Devuelve máscara binaria donde 255 = tinta/texto (foreground).
        """
        if gray is None:
            return None

        # Suaviza un poco para mejorar thresholding en escaneos ruidosos.
        blur = cv2.GaussianBlur(gray, (3, 3), 0)

        block = int(self.config.adaptive_thresh_blocksize)
        if block % 2 == 0:
            block += 1
        block = max(3, block)
        C = float(self.config.adaptive_thresh_C)

        # Texto suele ser oscuro: invertimos para que la tinta sea blanca (255).
        ink = cv2.adaptiveThreshold(
            blur,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            block,
            C,
        )

        # Limpieza básica para estabilizar líneas.
        k = max(3, int(self.config.morph_kernel))
        k = k if k % 2 == 1 else k + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel, iterations=1)
        return ink

    def _rotate90(self, bin_img: "object", degrees: int, *, cv2: "object") -> "object":
        d = int(degrees) % 360
        if d == 0:
            return bin_img
        if d == 90:
            return cv2.rotate(bin_img, cv2.ROTATE_90_CLOCKWISE)
        if d == 180:
            return cv2.rotate(bin_img, cv2.ROTATE_180)
        if d == 270:
            return cv2.rotate(bin_img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return bin_img

    def _score_upright(self, ink: "object", *, cv2: "object", np: "object") -> float:
        """
        Score “upright” (mayor es mejor):
        - favorece que existan estructuras horizontales largas (líneas de texto)
        - penaliza estructuras verticales largas
        - usa HoughLinesP de apoyo (si detecta líneas, mejor)
        """
        # 1) Señal morfológica: “cantidad de horizontal vs vertical”
        h, w = ink.shape[:2]
        # kernels proporcionales al tamaño para evitar sensibilidad por resolución
        hk = max(15, w // 30)
        vk = max(15, h // 30)
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (hk, 1))
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vk))

        horiz = cv2.morphologyEx(ink, cv2.MORPH_OPEN, h_kernel, iterations=1)
        vert = cv2.morphologyEx(ink, cv2.MORPH_OPEN, v_kernel, iterations=1)

        horiz_score = float(np.count_nonzero(horiz)) / float(h * w)
        vert_score = float(np.count_nonzero(vert)) / float(h * w)

        # 2) Señal por líneas: edges + Hough para reforzar “dominancia horizontal”
        edges = cv2.Canny(ink, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180.0, threshold=120, minLineLength=w // 8, maxLineGap=12)

        line_bonus = 0.0
        if lines is not None and len(lines) > 0:
            # Cuenta líneas casi horizontales vs casi verticales
            horiz_lines = 0
            vert_lines = 0
            for x1, y1, x2, y2 in lines[:, 0, :]:
                dx = abs(int(x2) - int(x1))
                dy = abs(int(y2) - int(y1))
                if dx == 0 and dy == 0:
                    continue
                if dx >= 3 * dy:
                    horiz_lines += 1
                elif dy >= 3 * dx:
                    vert_lines += 1
            total = max(1, horiz_lines + vert_lines)
            line_bonus = (horiz_lines - vert_lines) / float(total)  # [-1..1]

        # Combina: horizontal fuerte, vertical débil, y bonus por líneas.
        # Los coeficientes son simples y se ajustarán con datos reales.
        score = (2.2 * horiz_score) - (1.6 * vert_score) + (0.25 * line_bonus)
        return float(score)

