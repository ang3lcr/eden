from __future__ import annotations

from dataclasses import dataclass
from collections import OrderedDict
from pathlib import Path
from tempfile import NamedTemporaryFile
import threading
from typing import Iterator, Optional, Sequence, Tuple

from core.app_state import PageIndex


@dataclass(frozen=True)
class PdfMetadata:
    path: Path
    page_count: int


class PDFLoader:
    """
    Carga y acceso eficiente a páginas de un PDF.

    Objetivos:
    - abrir el PDF con PyMuPDF (fitz) y exponer metadata básica
    - renderizar páginas bajo demanda (sin cargar todo en memoria)
    - generar thumbnails optimizados para UI con un cache LRU pequeño
    - permitir (opcionalmente) generar subconjuntos de páginas como PDF temporal
    """

    def __init__(
        self,
        pdf_path: Path,
        *,
        thumbnail_cache_size: int = 256,
        default_thumbnail_max_size: int = 220,
    ):
        self.pdf_path = pdf_path
        self._metadata: Optional[PdfMetadata] = None

        # Documento “principal” (usado solo para metadata y operaciones simples).
        self._doc_main: Optional["fitz.Document"] = None

        # Thread-safety: un fitz.Document por hilo para renderizar.
        self._tl = threading.local()
        self._docs_lock = threading.Lock()
        self._docs_all: set["fitz.Document"] = set()

        self._thumb_cache: "OrderedDict[Tuple[int, int], object]" = OrderedDict()
        self._thumb_cache_size = int(max(0, thumbnail_cache_size))
        self._default_thumb_max = int(default_thumbnail_max_size)

    def open(self) -> None:
        """Abre/valida el PDF y carga metadata mínima."""
        if self._doc_main is not None:
            return

        if not self.pdf_path.exists():
            raise FileNotFoundError(f"No existe el PDF: {self.pdf_path}")
        if self.pdf_path.suffix.lower() != ".pdf":
            raise ValueError(f"Archivo no es PDF: {self.pdf_path}")

        import fitz  # PyMuPDF

        self._doc_main = fitz.open(str(self.pdf_path))
        with self._docs_lock:
            self._docs_all.add(self._doc_main)
        self._metadata = PdfMetadata(path=self.pdf_path, page_count=int(self._doc_main.page_count))

    def close(self) -> None:
        """Libera recursos (document handles, caches, etc.)."""
        self._thumb_cache.clear()
        with self._docs_lock:
            docs = list(self._docs_all)
            self._docs_all.clear()
        for d in docs:
            try:
                d.close()
            except Exception:
                pass

        self._doc_main = None
        self._metadata = None

    def __enter__(self) -> "PDFLoader":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def metadata(self) -> PdfMetadata:
        if self._metadata is None:
            raise RuntimeError("PDF no abierto. Llama a open() primero.")
        return self._metadata

    def iter_page_indices(self) -> Iterator[PageIndex]:
        """Itera índices de páginas sin materializar listas grandes."""
        self._ensure_open()
        # range() no materializa lista, es ideal para PDFs grandes.
        yield from range(self.metadata.page_count)

    def render_page_image(self, page_idx: PageIndex, *, dpi: int = 150) -> "object":
        """
        Renderiza una página a imagen (Pillow Image u objeto equivalente).

        Implementación:
        - usa PyMuPDF para renderizar a pixmap y lo convierte a PIL.Image
        - no cachea páginas completas para evitar uso excesivo de memoria
        """
        self._ensure_open()
        self._validate_page_index(page_idx)

        import fitz  # PyMuPDF
        from PIL import Image

        # PyMuPDF trabaja con matriz de escala respecto a 72 dpi.
        scale = float(dpi) / 72.0
        mat = fitz.Matrix(scale, scale)

        # alpha=False reduce memoria. Usamos RGB.
        doc = self._get_doc_for_thread()
        page = doc.load_page(int(page_idx))
        pix = page.get_pixmap(matrix=mat, alpha=False)

        # Conversión rápida a PIL sin copiar más de lo necesario.
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return img

    def render_thumbnail(self, page_idx: PageIndex, *, max_size: int = 220) -> "object":
        """Genera thumbnail optimizado para UI (memoria/velocidad)."""
        self._ensure_open()
        self._validate_page_index(page_idx)

        import fitz  # PyMuPDF
        from PIL import Image

        max_size = int(max_size or self._default_thumb_max)
        key = (int(page_idx), max_size)

        # Cache LRU para no regenerar thumbnails al scrollear.
        cached = self._thumb_cache.get(key)
        if cached is not None:
            self._thumb_cache.move_to_end(key)
            return cached

        # Render directo al tamaño objetivo para evitar crear una imagen grande y luego reducir.
        doc = self._get_doc_for_thread()
        page = doc.load_page(int(page_idx))
        rect = page.rect
        # Aproxima escala para que el lado mayor quede ~max_size px a 72 dpi base.
        w_pt = float(rect.width)
        h_pt = float(rect.height)
        # Evita división por cero
        if w_pt <= 1e-6 or h_pt <= 1e-6:
            base = self.render_page_image(page_idx, dpi=110)
            thumb = base.copy()
            thumb.thumbnail((max_size, max_size), resample=Image.Resampling.LANCZOS)
        else:
            scale = max_size / max(w_pt, h_pt)
            # scale aquí es px/pt (a 72 dpi base). fitz.Matrix usa escala lineal.
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            thumb = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        self._thumb_cache[key] = thumb
        self._thumb_cache.move_to_end(key)
        self._enforce_thumb_cache_limit()
        return thumb

    def extract_pages_subset(self, page_indices: Sequence[PageIndex]) -> Path:
        """
        Opcional: crea un PDF temporal con subconjunto de páginas para acelerar flujos.
        """
        self._ensure_open()
        import fitz  # PyMuPDF

        cleaned = [int(p) for p in page_indices]
        if not cleaned:
            raise ValueError("page_indices está vacío.")
        for p in cleaned:
            self._validate_page_index(p)

        out_doc = fitz.open()
        try:
            # Inserta páginas individuales sin renderizar imágenes.
            for p in cleaned:
                # Usamos doc_main como fuente estable (no thread-safe; este método se asume llamado desde UI).
                assert self._doc_main is not None
                out_doc.insert_pdf(self._doc_main, from_page=p, to_page=p)

            with NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp_path = Path(tmp.name)
                out_doc.save(str(tmp_path), garbage=4, deflate=True)
                return tmp_path
        finally:
            out_doc.close()

    def render_page_image_pdf2image(self, page_idx: PageIndex, *, dpi: int = 150) -> "object":
        """
        Alternativa opcional con pdf2image (requiere Poppler en muchos entornos Windows).

        Se deja disponible para casos donde PyMuPDF no sea suficiente.
        """
        self._ensure_open()
        self._validate_page_index(page_idx)

        from pdf2image import convert_from_path

        images = convert_from_path(
            str(self.pdf_path),
            dpi=int(dpi),
            first_page=int(page_idx) + 1,
            last_page=int(page_idx) + 1,
            fmt="png",
            thread_count=1,
        )
        if not images:
            raise RuntimeError(f"No se pudo convertir la página {page_idx} con pdf2image.")
        return images[0]

    def _ensure_open(self) -> None:
        if self._doc_main is None or self._metadata is None:
            raise RuntimeError("PDF no abierto. Llama a open() primero.")

    def _validate_page_index(self, page_idx: int) -> None:
        if page_idx < 0 or page_idx >= self.metadata.page_count:
            raise IndexError(f"page_idx fuera de rango: {page_idx} (0..{self.metadata.page_count - 1})")

    def _enforce_thumb_cache_limit(self) -> None:
        if self._thumb_cache_size <= 0:
            self._thumb_cache.clear()
            return
        while len(self._thumb_cache) > self._thumb_cache_size:
            self._thumb_cache.popitem(last=False)

    def _get_doc_for_thread(self) -> "fitz.Document":
        """
        Thread-safe: devuelve un `fitz.Document` asociado al hilo actual.
        """
        self._ensure_open()
        import fitz  # PyMuPDF

        doc = getattr(self._tl, "doc", None)
        if doc is not None:
            return doc

        # Abre un nuevo handle del documento para este hilo.
        doc = fitz.open(str(self.pdf_path))
        self._tl.doc = doc
        with self._docs_lock:
            self._docs_all.add(doc)
        return doc

