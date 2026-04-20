from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from concurrent.futures import Future, ThreadPoolExecutor

try:
    # Compatibilidad con el contenedor App existente
    from core.app_state import AppState, PageIndex
except Exception:  # pragma: no cover
    AppState = Any  # type: ignore
    PageIndex = int  # type: ignore


class BlankPagesScreen(tk.Frame):
    """
    Pantalla: detección de hojas en blanco.

    - Muestra miniaturas en una cuadrícula (scrollable)
    - Permite seleccionar cuáles conservar
    - Las no seleccionadas se eliminan
    """

    def __init__(
        self,
        master: tk.Misc,
        state: Optional[AppState] = None,
        on_navigate: Optional[Callable[[str], None]] = None,
        *,
        thumbnails: Optional[List[Tuple[int, "object"]]] = None,
        page_indices: Optional[List[int]] = None,
        thumbnail_provider: Optional[Callable[[int, int], "object"]] = None,
        columns: int = 4,
        thumb_size: int = 220,
        on_continue: Optional[Callable[[], None]] = None,
    ):
        super().__init__(master)
        self.state = state
        self.on_navigate = on_navigate
        self._columns = max(1, int(columns))
        self._thumb_size = max(80, int(thumb_size))
        self._on_continue = on_continue

        # Entrada: o thumbnails ya construidos o proveedor on-demand.
        self._thumbnails: List[Tuple[int, "object"]] = thumbnails or []
        self._page_indices: List[int] = page_indices or [int(p) for p, _ in self._thumbnails]
        self._thumb_provider = thumbnail_provider
        if not self._thumbnails and not self._page_indices:
            self._thumbnails = self._build_demo_thumbnails()
            self._page_indices = [int(p) for p, _ in self._thumbnails]

        initial_selected: Set[int] = set()
        if self.state is not None and getattr(self.state, "kept_blank_pages", None):
            initial_selected = set(int(p) for p in self.state.kept_blank_pages)
        self._selected: Set[int] = set(initial_selected)

        # Por página: widget canvas + referencias a PhotoImage y rect de borde
        self._cells: Dict[int, tk.Canvas] = {}
        self._photo_refs: Dict[int, "object"] = {}
        self._border_ids: Dict[int, int] = {}
        self._img_item_ids: Dict[int, int] = {}
        self._loading: Dict[int, Future] = {}
        self._loaded: Set[int] = set()
        self._executor = ThreadPoolExecutor(max_workers=2)

        self._build()

        self.bind("<Destroy>", lambda _e: self._shutdown_executor(), add=True)

    def _build(self) -> None:
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="Hojas en blanco detectadas", font=("Segoe UI", 14, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            top,
            text="Selecciona las páginas en blanco que deseas conservar. Las no seleccionadas serán eliminadas.",
        ).pack(anchor="w", pady=(6, 0))

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        # Scroll + grid (real)
        self._canvas = tk.Canvas(body, highlightthickness=0, background=self._ttk_bg(body))
        self._scroll = ttk.Scrollbar(body, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scroll.set)
        self._scroll.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._grid = ttk.Frame(self._canvas)
        self._grid_id = self._canvas.create_window((0, 0), window=self._grid, anchor="nw")

        self._grid.bind("<Configure>", self._on_grid_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel, add=True)

        self._render_thumbnails()

        actions = ttk.Frame(self, padding=12)
        actions.pack(fill="x")
        ttk.Button(actions, text="Continuar", command=self._continue).pack(side="right")

    def _render_thumbnails(self) -> None:
        for child in list(self._grid.children.values()):
            child.destroy()
        self._cells.clear()
        self._photo_refs.clear()
        self._border_ids.clear()

        cols = self._columns

        # Construye tiles; si hay thumbnails precargados, se usan, si no, placeholders.
        thumb_map: Dict[int, "object"] = {int(p): img for p, img in self._thumbnails}

        for i, page_idx in enumerate(self._page_indices):
            r, c = divmod(i, cols)
            cell = ttk.Frame(self._grid, padding=6)
            cell.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")

            canvas = tk.Canvas(
                cell,
                width=self._thumb_size,
                height=self._thumb_size + 26,
                highlightthickness=0,
                background="white",
            )
            canvas.pack()

            # Placeholder / imagen
            if int(page_idx) in thumb_map:
                photo = self._pil_to_photoimage(thumb_map[int(page_idx)], max_size=self._thumb_size)
                self._photo_refs[int(page_idx)] = photo
                img_id = canvas.create_image(self._thumb_size // 2, self._thumb_size // 2, image=photo, anchor="center")
                self._loaded.add(int(page_idx))
            else:
                img_id = canvas.create_text(
                    self._thumb_size // 2,
                    self._thumb_size // 2,
                    text="Cargando…",
                    fill="#666",
                    font=("Segoe UI", 10),
                )
            self._img_item_ids[int(page_idx)] = int(img_id)

            # Etiqueta
            canvas.create_text(
                self._thumb_size // 2,
                self._thumb_size + 13,
                text=f"Página {int(page_idx) + 1}",
                fill="#111",
                font=("Segoe UI", 10),
            )

            # Borde para feedback visual (se actualiza al seleccionar)
            border_id = canvas.create_rectangle(
                2,
                2,
                self._thumb_size - 2,
                self._thumb_size - 2,
                outline="#b0b0b0",
                width=2,
            )

            self._cells[int(page_idx)] = canvas
            self._border_ids[int(page_idx)] = int(border_id)

            # Click selecciona/deselecciona
            canvas.bind("<Button-1>", lambda e, p=int(page_idx): self._toggle(p))

            self._apply_selected_style(int(page_idx))

        for col in range(cols):
            self._grid.grid_columnconfigure(col, weight=1)

        # Kick: carga on-demand lo visible
        self.after(0, self._load_visible_thumbnails)

    def _toggle(self, page_idx: int) -> None:
        if page_idx in self._selected:
            self._selected.remove(page_idx)
        else:
            self._selected.add(page_idx)
        self._apply_selected_style(page_idx)

    def _apply_selected_style(self, page_idx: int) -> None:
        canvas = self._cells.get(page_idx)
        border_id = self._border_ids.get(page_idx)
        if canvas is None or border_id is None:
            return
        selected = page_idx in self._selected
        if selected:
            canvas.itemconfigure(border_id, outline="#1f6feb", width=4)
        else:
            canvas.itemconfigure(border_id, outline="#b0b0b0", width=2)

    def _continue(self) -> None:
        # Guarda selección si existe state, pero no navega aún (solo UI).
        if self.state is not None and hasattr(self.state, "kept_blank_pages"):
            self.state.kept_blank_pages = sorted(int(p) for p in self._selected)  # type: ignore[attr-defined]
        if self._on_continue is not None:
            self._on_continue()
        return

    def _on_grid_configure(self, _event: tk.Event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._load_visible_thumbnails()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        # Ajusta el ancho del frame interior al canvas.
        self._canvas.itemconfigure(self._grid_id, width=event.width)
        self._load_visible_thumbnails()

    def _on_mousewheel(self, event: tk.Event) -> None:
        # En Windows el delta viene en múltiplos de 120
        try:
            delta = int(event.delta)
        except Exception:
            return
        if delta == 0:
            return
        self._canvas.yview_scroll(int(-1 * (delta / 120)), "units")
        self._load_visible_thumbnails()

    def _visible_page_indices(self) -> List[int]:
        # Estima qué filas son visibles y devuelve páginas de esas filas (+prefetch).
        if not self._page_indices:
            return []
        try:
            y0 = self._canvas.canvasy(0)
            y1 = y0 + self._canvas.winfo_height()
        except Exception:
            return []

        tile_h = self._thumb_size + 26 + 12  # canvas height + padding aprox
        if tile_h <= 0:
            return []

        start_row = max(0, int(y0 // tile_h) - 1)
        end_row = int(y1 // tile_h) + 2

        cols = self._columns
        start_i = start_row * cols
        end_i = min(len(self._page_indices), (end_row + 1) * cols)
        return [int(p) for p in self._page_indices[start_i:end_i]]

    def _load_visible_thumbnails(self) -> None:
        if self._thumb_provider is None:
            return
        for page_idx in self._visible_page_indices():
            if page_idx in self._loaded or page_idx in self._loading:
                continue
            fut = self._executor.submit(self._thumb_provider, int(page_idx), int(self._thumb_size))
            self._loading[int(page_idx)] = fut
            fut.add_done_callback(lambda f, p=int(page_idx): self.after(0, self._apply_loaded_thumb, p, f))

    def _apply_loaded_thumb(self, page_idx: int, fut: Future) -> None:
        self._loading.pop(int(page_idx), None)
        if page_idx in self._loaded:
            return
        try:
            pil_img = fut.result()
        except Exception:
            return
        try:
            canvas = self._cells.get(int(page_idx))
            if canvas is None or not self.winfo_exists() or not canvas.winfo_exists():
                return
            from PIL import ImageTk, Image

            if not isinstance(pil_img, Image.Image):
                return
            img = pil_img.copy()
            img.thumbnail((self._thumb_size, self._thumb_size), resample=Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._photo_refs[int(page_idx)] = photo

            item_id = self._img_item_ids.get(int(page_idx))
            if item_id is None:
                return
            try:
                canvas.delete(item_id)
            except tk.TclError:
                return
            new_id = canvas.create_image(self._thumb_size // 2, self._thumb_size // 2, image=photo, anchor="center")
            self._img_item_ids[int(page_idx)] = int(new_id)
            self._loaded.add(int(page_idx))
        except Exception:
            return

    def _shutdown_executor(self) -> None:
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)  # type: ignore[arg-type]
        except Exception:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass

    def _pil_to_photoimage(self, pil_image: "object", *, max_size: int) -> "object":
        """
        Convierte PIL.Image a PhotoImage escalado.
        """
        from PIL import Image, ImageTk

        if not isinstance(pil_image, Image.Image):
            raise TypeError("thumbnails debe contener PIL.Image.Image")

        img = pil_image.copy()
        img.thumbnail((max_size, max_size), resample=Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(img)

    def _build_demo_thumbnails(self) -> List[Tuple[int, "object"]]:
        """
        Miniaturas de demostración para que la pantalla sea usable sin pipeline.
        """
        try:
            pages = []
            if self.state is not None and getattr(self.state, "detected_blank_pages", None):
                pages = [int(p) for p in self.state.detected_blank_pages]
            if not pages:
                pages = list(range(12))

            from PIL import Image, ImageDraw, ImageFont

            thumbs: List[Tuple[int, "object"]] = []
            for p in pages:
                img = Image.new("RGB", (900, 1200), "white")
                d = ImageDraw.Draw(img)
                d.rectangle((40, 40, 860, 1160), outline="#e5e5e5", width=6)
                text = f"Página {p + 1}"
                try:
                    font = ImageFont.truetype("arial.ttf", 64)
                except Exception:
                    font = ImageFont.load_default()
                d.text((80, 90), text, fill="#777", font=font)
                thumbs.append((p, img))
            return thumbs
        except Exception:
            # Último recurso: lista vacía (no revienta la UI)
            return []

    def _ttk_bg(self, widget: tk.Widget) -> str:
        # Color de fondo aproximado según el tema (fallback)
        try:
            style = ttk.Style(widget)
            return style.lookup("TFrame", "background") or "#f0f0f0"
        except Exception:
            return "#f0f0f0"

