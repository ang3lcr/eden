from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, List, Optional, Tuple

from concurrent.futures import Future, ThreadPoolExecutor

try:
    from core.app_state import AppState, PageIndex, RotationDegrees
except Exception:  # pragma: no cover
    AppState = Any  # type: ignore
    PageIndex = int  # type: ignore
    RotationDegrees = int  # type: ignore


class OrientationScreen(tk.Frame):
    """
    Pantalla: detección/corrección de orientación.

    - Muestra páginas detectadas como mal orientadas
    - Permite rotar 90/180/270 por página
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
        thumb_size: int = 240,
        on_continue: Optional[Callable[[], None]] = None,
    ):
        super().__init__(master)
        self.state = state
        self.on_navigate = on_navigate
        self._thumb_size = max(100, int(thumb_size))
        self._on_continue = on_continue

        self._thumbnails: List[Tuple[int, "object"]] = thumbnails or []
        self._page_indices: List[int] = page_indices or [int(p) for p, _ in self._thumbnails]
        self._thumb_provider = thumbnail_provider
        if not self._thumbnails and not self._page_indices and self._thumb_provider is None:
            self._thumbnails = self._build_demo_thumbnails()
            self._page_indices = [int(p) for p, _ in self._thumbnails]

        # Estado local de rotación para vista previa (si hay state, se sincroniza)
        self._rotations: Dict[int, int] = {}
        if self.state is not None and getattr(self.state, "edits", None) is not None:
            try:
                self._rotations = {int(k): int(v) for k, v in self.state.edits.rotations.items()}
            except Exception:
                self._rotations = {}

        # Referencias para que Tk no GC las imágenes
        self._photo_refs: Dict[int, "object"] = {}
        self._canvas_by_page: Dict[int, tk.Canvas] = {}
        self._label_by_page: Dict[int, ttk.Label] = {}

        self._thumb_map: Dict[int, "object"] = {int(p): img for p, img in self._thumbnails}
        self._loading: Dict[int, Future] = {}
        self._loaded: set[int] = set(self._thumb_map.keys())
        self._executor = ThreadPoolExecutor(max_workers=2)

        self._build()
        self.bind("<Destroy>", lambda _e: self._shutdown_executor(), add=True)

    def _build(self) -> None:
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="Orientación detectada", font=("Segoe UI", 14, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            top,
            text="Ajusta la rotación de las páginas detectadas como mal orientadas.",
        ).pack(anchor="w", pady=(6, 0))

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        # Scrollable list
        self._canvas = tk.Canvas(body, highlightthickness=0, background=self._ttk_bg(body))
        self._scroll = ttk.Scrollbar(body, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scroll.set)
        self._scroll.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._list = ttk.Frame(self._canvas)
        self._list_id = self._canvas.create_window((0, 0), window=self._list, anchor="nw")
        self._list.bind("<Configure>", self._on_list_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel, add=True)

        self._render_rows()

        actions = ttk.Frame(self, padding=12)
        actions.pack(fill="x")
        ttk.Button(actions, text="Continuar", command=self._continue).pack(side="right")

    def _render_rows(self) -> None:
        for child in list(self._list.children.values()):
            child.destroy()
        self._photo_refs.clear()
        self._canvas_by_page.clear()
        self._label_by_page.clear()

        pages = self._page_indices

        for page_idx in pages:
            row = ttk.Frame(self._list, relief="ridge", padding=10)
            row.pack(fill="x", pady=6)

            left = ttk.Frame(row)
            left.pack(side="left")

            title = ttk.Label(left, text=f"Página {page_idx + 1}", font=("Segoe UI", 11, "bold"))
            title.pack(anchor="w")

            canvas = tk.Canvas(
                left,
                width=self._thumb_size,
                height=self._thumb_size,
                highlightthickness=1,
                highlightbackground="#c8c8c8",
                background="white",
            )
            canvas.pack(pady=(6, 0))
            self._canvas_by_page[int(page_idx)] = canvas

            right = ttk.Frame(row)
            right.pack(side="right", fill="y")

            btns = ttk.Frame(right)
            btns.pack(anchor="e")
            ttk.Button(btns, text="90°", command=lambda p=int(page_idx): self._rotate(p, 90)).pack(
                side="left", padx=4
            )
            ttk.Button(btns, text="180°", command=lambda p=int(page_idx): self._rotate(p, 180)).pack(
                side="left", padx=4
            )
            ttk.Button(btns, text="270°", command=lambda p=int(page_idx): self._rotate(p, 270)).pack(
                side="left", padx=4
            )

            current = int(self._rotations.get(int(page_idx), 0)) % 360
            lbl = ttk.Label(right, text=f"Rotación actual: {current}°")
            lbl.pack(anchor="e", pady=(10, 0))
            self._label_by_page[int(page_idx)] = lbl

            base_img = self._thumb_map.get(int(page_idx))
            if base_img is not None:
                self._render_preview(int(page_idx), base_img)
            else:
                canvas.create_text(self._thumb_size // 2, self._thumb_size // 2, text="Cargando…", fill="#666")
                self._load_thumb(int(page_idx))

    def _rotate(self, page_idx: int, degrees: int) -> None:
        """
        Actualiza la vista previa en el UI.

        Por ahora, aplica la rotación sobre la preview y guarda el valor en memoria local.
        Si existe `state`, también sincroniza en `state.edits.rotations`.
        """
        degrees = int(degrees) % 360
        if degrees not in (0, 90, 180, 270):
            return
        self._rotations[int(page_idx)] = degrees

        if self.state is not None and getattr(self.state, "edits", None) is not None:
            try:
                self.state.edits.rotations[int(page_idx)] = degrees  # type: ignore[attr-defined]
            except Exception:
                pass

        # Re-render de la preview
        base = self._thumb_map.get(int(page_idx))
        if base is not None:
            self._render_preview(int(page_idx), base)

        lbl = self._label_by_page.get(int(page_idx))
        if lbl is not None:
            lbl.configure(text=f"Rotación actual: {degrees}°")

    def _continue(self) -> None:
        if self._on_continue is not None:
            self._on_continue()
        return

    def _render_preview(self, page_idx: int, pil_image: "object") -> None:
        from PIL import Image, ImageTk

        if not isinstance(pil_image, Image.Image):
            return

        canvas = self._canvas_by_page.get(int(page_idx))
        if canvas is None:
            return

        img = pil_image.copy()
        rot = int(self._rotations.get(int(page_idx), 0)) % 360
        if rot:
            # expand=True para que no corte; BICUBIC para preview suave
            img = img.rotate(-rot, expand=True, resample=Image.Resampling.BICUBIC)

        img.thumbnail((self._thumb_size, self._thumb_size), resample=Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self._photo_refs[int(page_idx)] = photo

        canvas.delete("all")
        canvas.create_image(self._thumb_size // 2, self._thumb_size // 2, image=photo, anchor="center")

    def _load_thumb(self, page_idx: int) -> None:
        if self._thumb_provider is None:
            return
        if page_idx in self._loaded or page_idx in self._loading:
            return
        fut = self._executor.submit(self._thumb_provider, int(page_idx), int(self._thumb_size))
        self._loading[int(page_idx)] = fut
        fut.add_done_callback(lambda f, p=int(page_idx): self.after(0, self._apply_thumb, p, f))

    def _apply_thumb(self, page_idx: int, fut: Future) -> None:
        self._loading.pop(int(page_idx), None)
        if page_idx in self._loaded:
            return
        try:
            pil_img = fut.result()
        except Exception:
            return
        self._thumb_map[int(page_idx)] = pil_img
        self._loaded.add(int(page_idx))
        self._render_preview(int(page_idx), pil_img)

    def _shutdown_executor(self) -> None:
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)  # type: ignore[arg-type]
        except Exception:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass

    def _build_demo_thumbnails(self) -> List[Tuple[int, "object"]]:
        try:
            pages = []
            if self.state is not None and getattr(self.state, "detected_misoriented_pages", None):
                pages = [int(p) for p in self.state.detected_misoriented_pages]
            if not pages:
                pages = [0, 2, 5, 7]

            from PIL import Image, ImageDraw, ImageFont

            thumbs: List[Tuple[int, "object"]] = []
            for p in pages:
                img = Image.new("RGB", (1200, 900), "white")
                d = ImageDraw.Draw(img)
                d.rectangle((60, 60, 1140, 840), outline="#e5e5e5", width=6)
                # Simula “líneas de texto” para que la rotación sea visible
                for y in range(180, 820, 70):
                    d.line((120, y, 1080, y), fill="#333", width=5)
                text = f"Página {p + 1}"
                try:
                    font = ImageFont.truetype("arial.ttf", 56)
                except Exception:
                    font = ImageFont.load_default()
                d.text((140, 100), text, fill="#555", font=font)
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

    def _on_list_configure(self, _event: tk.Event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self._canvas.itemconfigure(self._list_id, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:
        try:
            delta = int(event.delta)
        except Exception:
            return
        if delta == 0:
            return
        self._canvas.yview_scroll(int(-1 * (delta / 120)), "units")

