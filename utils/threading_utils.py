from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, List, Optional, TypeVar

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class ParallelConfig:
    """
    Config de paralelización.

    Implementación futura:
    - elegir threading vs multiprocessing según carga (I/O vs CPU)
    - controlar max_workers
    - backpressure para no cargar memoria con 300+ páginas
    """

    enabled: bool = True
    max_workers: Optional[int] = None


def parallel_map(items: Iterable[T], fn: Callable[[T], R], config: Optional[ParallelConfig] = None) -> List[R]:
    """
    Aplica fn a items en paralelo (cuando sea conveniente).

    Implementación futura:
    - concurrent.futures.ThreadPoolExecutor / ProcessPoolExecutor
    - devolver resultados en orden
    """
    cfg = config or ParallelConfig()
    if not cfg.enabled:
        return [fn(x) for x in items]

    from concurrent.futures import ThreadPoolExecutor

    # ThreadPool por defecto: adecuado para mezcla I/O + C-extensions (fitz/opencv).
    with ThreadPoolExecutor(max_workers=cfg.max_workers) as ex:
        return list(ex.map(fn, items))


def chunked(items: Iterable[T], size: int) -> Iterator[List[T]]:
    """Divide un iterable en chunks para procesamiento por lotes."""
    size = int(size)
    if size <= 0:
        raise ValueError("size debe ser > 0")

    batch: List[T] = []
    for x in items:
        batch.append(x)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch

