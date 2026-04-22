from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, List, Optional, Tuple

from concurrent.futures import Future, ThreadPoolExecutor

try:
    from core.app_state import AppState, PageIndex
    from core.pdf_loader import PDFLoader
except Exception:  # pragma: no cover
    AppState = Any  # type: ignore
    PageIndex = int  # type: ignore
    PDFLoader = Any  # type: ignore

from ui.crop_editor import CropEditor


class ReorderScreen(tk.Frame):
    """
    Pantalla: organización/reordenamiento de páginas.

    - Muestra todas las páginas en grid con scroll
    - Drag & drop con intercambio (swap)
    - Indicador visual del destino (highlight)
    - Click derecho abre editor de recorte

    Nota: para que sea usable sin pipeline, soporta thumbnails de demostración.
    """

    def __init__(
        self,
        master: tk.Misc,
        state: Optional[AppState] = None,
        on_navigate: Optional[Callable[[str], None]] = None,
        *,
        thumbnails: Optional[List[Tuple[int, "object"]]] = None,
        thumbnail_provider: Optional[Callable[[int, int], "object"]] = None,
        pdf_loader: Optional["PDFLoader"] = None,
        columns: int = 5,
        thumb_size: int = 200,
        on_continue: Optional[Callable[[], None]] = None,
    ):
        super().__init__(master)
        self.state = state
        self.on_navigate = on_navigate
        self.pdf_loader = pdf_loader

        self._columns = max(1, int(columns))
        self._thumb_size = max(90, int(thumb_size))
        self._on_continue = on_continue

        # thumbnails precargados o proveedor on-demand
        self._thumbnails: List[Tuple[int, "object"]] = thumbnails or []
        self._thumb_provider = thumbnail_provider
        if not self._thumbnails and self._thumb_provider is None:
            self._thumbnails = self._build_demo_thumbnails()
        self._thumb_map: Dict[int, "object"] = {int(p): img for p, img in self._thumbnails}

        # Orden actual (lista de índices de página del PDF original)
        self._order: List[int] = self._initial_order()

        # Drag state
        self._drag_source: Optional[int] = None
        self._hover_target: Optional[int] = None

        # UI refs
        self._tile_canvas: Dict[int, tk.Canvas] = {}
        self._tile_border: Dict[int, int] = {}
        self._photo_refs: Dict[int, "object"] = {}
        self._img_item_ids: Dict[int, int] = {}
        self._loaded: set[int] = set()
        self._loading: Dict[int, Future] = {}
        self._executor = ThreadPoolExecutor(max_workers=2)

        self._build()
        self.bind("<Destroy>", lambda _e: self._shutdown_executor(), add=True)

    def _build(self) -> None:
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="Organización de páginas", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(top, text="Arrastra para intercambiar páginas. Click derecho para recortar.").pack(
            anchor="w", pady=(6, 0)
        )

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

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

        self._render_pages()

        actions = ttk.Frame(self, padding=12)
        actions.pack(fill="x")
        ttk.Button(actions, text="Continuar", command=self._continue).pack(side="right")

    def _render_pages(self) -> None:
        for child in list(self._grid.children.values()):
            child.destroy()
        self._tile_canvas.clear()
        self._tile_border.clear()
        self._photo_refs.clear()
        self._img_item_ids.clear()
        self._loaded.clear()
        self._loading.clear()

        cols = self._columns
        for i, page_idx in enumerate(self._order):
            r, c = divmod(i, cols)
            cell = ttk.Frame(self._grid, padding=6)
            cell.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")

            canvas = tk.Canvas(
                cell,
                width=self._thumb_size,
                height=self._thumb_size + 34,
                highlightthickness=0,
                background="white",
            )
            canvas.pack()

            pil_img = self._thumb_map.get(int(page_idx))
            if pil_img is not None:
                photo = self._pil_to_photoimage(pil_img, max_size=self._thumb_size)
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

            canvas.create_text(
                self._thumb_size // 2,
                self._thumb_size + 14,
                text=f"#{i + 1}  Página {int(page_idx) + 1}",
                fill="#111",
                font=("Segoe UI", 10, "bold"),
            )

            border_id = canvas.create_rectangle(
                2,
                2,
                self._thumb_size - 2,
                self._thumb_size - 2,
                outline="#b0b0b0",
                width=2,
            )

            self._tile_canvas[int(page_idx)] = canvas
            self._tile_border[int(page_idx)] = int(border_id)

            # Drag & drop real (swap) + highlight destino
            canvas.bind("<ButtonPress-1>", lambda e, p=int(page_idx): self._on_drag_start(e, p))
            canvas.bind("<B1-Motion>", self._on_drag_motion)
            canvas.bind("<ButtonRelease-1>", self._on_drag_release)

            # Click derecho: abrir CropEditor
            canvas.bind("<Button-3>", lambda e, p=int(page_idx): self._open_crop_editor(p))

        for col in range(cols):
            self._grid.grid_columnconfigure(col, weight=1)

        self.after(0, self._load_visible_thumbnails)

    def _on_drag_start(self, event: tk.Event, page_idx: int) -> None:
        self._drag_source = int(page_idx)
        self._hover_target = None
        self._update_highlights()
        try:
            event.widget.grab_set()
        except Exception:
            pass

    def _on_drag_motion(self, event: tk.Event) -> None:
        if self._drag_source is None:
            return

        target = self._page_at_root_xy(int(event.x_root), int(event.y_root))
        if target != self._hover_target:
            self._hover_target = target
            self._update_highlights()
        self._load_visible_thumbnails()

    def _on_drag_release(self, event: tk.Event) -> None:
        if self._drag_source is None:
            return

        try:
            event.widget.grab_release()
        except Exception:
            pass

        src = int(self._drag_source)
        dst = int(self._hover_target) if self._hover_target is not None else None

        self._drag_source = None
        self._hover_target = None
        self._update_highlights()

        if dst is None or dst == src:
            return

        self._swap_in_order(src, dst)
        self._sync_order_to_state()
        self._render_pages()

    def _swap_in_order(self, a: int, b: int) -> None:
        try:
            i = self._order.index(int(a))
            j = self._order.index(int(b))
        except ValueError:
            return
        self._order[i], self._order[j] = self._order[j], self._order[i]

    def _page_at_root_xy(self, x_root: int, y_root: int) -> Optional[int]:
        # Recorre tiles; si luego necesitas optimización para 1000+ páginas, se indexa por celdas.
        for page_idx, canvas in self._tile_canvas.items():
            try:
                x0 = canvas.winfo_rootx()
                y0 = canvas.winfo_rooty()
                x1 = x0 + canvas.winfo_width()
                y1 = y0 + canvas.winfo_height()
            except Exception:
                continue
            if x0 <= x_root <= x1 and y0 <= y_root <= y1:
                return int(page_idx)
        return None

    def _update_highlights(self) -> None:
        src = self._drag_source
        dst = self._hover_target
        for page_idx, canvas in self._tile_canvas.items():
            border_id = self._tile_border.get(page_idx)
            if border_id is None:
                continue

            if src is not None and page_idx == int(src):
                canvas.itemconfigure(border_id, outline="#d97706", width=4)  # origen
            elif dst is not None and page_idx == int(dst):
                canvas.itemconfigure(border_id, outline="#1f6feb", width=5)  # destino
            else:
                canvas.itemconfigure(border_id, outline="#b0b0b0", width=2)

    def _open_crop_editor(self, page_idx: PageIndex) -> None:
        page_idx = int(page_idx)
        initial = None
        if self.state is not None and getattr(self.state, "edits", None) is not None:
            try:
                initial = self.state.edits.crops.get(page_idx)
            except Exception:
                initial = None

        def _on_save(p: int, margins: "object") -> None:
            if self.state is None or getattr(self.state, "edits", None) is None:
                return
            try:
                self.state.edits.crops[int(p)] = margins  # type: ignore[attr-defined]
            except Exception:
                return

        CropEditor(self, page_idx=page_idx, pdf_loader=self.pdf_loader, initial_margins=initial, on_save=_on_save)

    def _continue(self) -> None:
        self._sync_order_to_state()
        if self._on_continue is not None:
            self._on_continue()
        return

    def _sync_order_to_state(self) -> None:
        if self.state is None:
            return
        if hasattr(self.state, "page_order"):
            try:
                self.state.page_order = list(self._order)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _initial_order(self) -> List[int]:
        # 1) state.page_order
        if self.state is not None and getattr(self.state, "page_order", None):
            try:
                return [int(p) for p in self.state.page_order]
            except Exception:
                pass

        # 2) total_pages
        if self.state is not None and int(getattr(self.state, "total_pages", 0) or 0) > 0:
            return list(range(int(self.state.total_pages)))

        # 3) thumbnails
        # Si no hay thumbnails precargados, cae en 0..total_pages-1 si existe.
        if not self._thumbnails and self.state is not None and int(getattr(self.state, "total_pages", 0) or 0) > 0:
            return list(range(int(self.state.total_pages)))
        return [int(p) for p, _ in self._thumbnails]

    def _pil_to_photoimage(self, pil_image: "object", *, max_size: int) -> "object":
        from PIL import Image, ImageTk

        if not isinstance(pil_image, Image.Image):
            raise TypeError("thumbnails debe contener PIL.Image.Image")

        img = pil_image.copy()
        img.thumbnail((int(max_size), int(max_size)), resample=Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(img)

    def _build_demo_thumbnails(self) -> List[Tuple[int, "object"]]:
        try:
            from PIL import Image, ImageDraw, ImageFont

            pages: List[int] = []
            if self.state is not None and int(getattr(self.state, "total_pages", 0) or 0) > 0:
                pages = list(range(int(self.state.total_pages)))
            if not pages:
                pages = list(range(20))

            thumbs: List[Tuple[int, "object"]] = []
            for p in pages:
                img = Image.new("RGB", (900, 1200), "white")
                d = ImageDraw.Draw(img)
                d.rectangle((40, 40, 860, 1160), outline="#e5e5e5", width=6)
                for y in range(220, 1120, 80):
                    d.line((90, y, 810, y), fill="#222", width=4)
                try:
                    font = ImageFont.truetype("arial.ttf", 72)
                except Exception:
                    font = ImageFont.load_default()
                d.text((80, 90), f"Página {p + 1}", fill="#555", font=font)
                thumbs.append((p, img))
            return thumbs
        except Exception:
            return []

    def _ttk_bg(self, widget: tk.Widget) -> str:
        try:
            style = ttk.Style(widget)
            return style.lookup("TFrame", "background") or "#f0f0f0"
        except Exception:
            return "#f0f0f0"

    def _on_grid_configure(self, _event: tk.Event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._load_visible_thumbnails()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self._canvas.itemconfigure(self._grid_id, width=event.width)
        self._load_visible_thumbnails()

    def _on_mousewheel(self, event: tk.Event) -> None:
        try:
            delta = int(event.delta)
        except Exception:
            return
        if delta == 0:
            return
        self._canvas.yview_scroll(int(-1 * (delta / 120)), "units")
        self._load_visible_thumbnails()

    def _visible_page_indices(self) -> List[int]:
        if not self._order:
            return []
        try:
            y0 = self._canvas.canvasy(0)
            y1 = y0 + self._canvas.winfo_height()
        except Exception:
            return []

        tile_h = self._thumb_size + 34 + 12
        if tile_h <= 0:
            return []

        start_row = max(0, int(y0 // tile_h) - 1)
        end_row = int(y1 // tile_h) + 2
        cols = self._columns
        start_i = start_row * cols
        end_i = min(len(self._order), (end_row + 1) * cols)
        return [int(p) for p in self._order[start_i:end_i]]

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

        canvas = self._tile_canvas.get(int(page_idx))
        if canvas is None:
            return

        try:
            from PIL import Image, ImageTk

            if not isinstance(pil_img, Image.Image):
                return
            img = pil_img.copy()
            img.thumbnail((self._thumb_size, self._thumb_size), resample=Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._photo_refs[int(page_idx)] = photo

            item_id = self._img_item_ids.get(int(page_idx))
            if item_id is not None:
                canvas.delete(item_id)
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