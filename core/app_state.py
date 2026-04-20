from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


PageIndex = int
CropMargins = Tuple[int, int, int, int]  # (left, top, right, bottom) en pix/pts según implementación futura
RotationDegrees = int  # 0, 90, 180, 270


@dataclass
class AppOptions:
    """Opciones seleccionadas por el usuario (solo se ejecuta lo marcado)."""

    detect_blank_pages: bool = True
    detect_orientation: bool = True

    blank_threshold_percent: float = 95.0


@dataclass
class AppPaths:
    """Rutas de entrada/salida."""

    input_pdf: Optional[Path] = None
    output_pdf: Optional[Path] = None


@dataclass
class PageEdits:
    """Ediciones por página (aplicadas al exportar)."""

    rotations: Dict[PageIndex, RotationDegrees] = field(default_factory=dict)
    crops: Dict[PageIndex, CropMargins] = field(default_factory=dict)


@dataclass
class AppState:
    """
    Estado compartido entre pantallas y core.

    NOTA: Este esqueleto define “qué” se guardará; la lógica real se implementará después.
    """

    paths: AppPaths = field(default_factory=AppPaths)
    options: AppOptions = field(default_factory=AppOptions)

    total_pages: int = 0

    # Resultados / decisiones del usuario
    detected_blank_pages: List[PageIndex] = field(default_factory=list)
    kept_blank_pages: List[PageIndex] = field(default_factory=list)

    detected_misoriented_pages: List[PageIndex] = field(default_factory=list)

    # Orden final de páginas (índices originales)
    page_order: List[PageIndex] = field(default_factory=list)

    edits: PageEdits = field(default_factory=PageEdits)

    # Resumen para pantalla final
    deleted_pages: List[PageIndex] = field(default_factory=list)

