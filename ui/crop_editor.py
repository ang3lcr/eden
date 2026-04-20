from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional, Tuple, Literal

from core.app_state import CropMargins, PageIndex


class CropEditor(tk.Toplevel):
    """
    Editor de recorte de márgenes.

    Implementación futura:
    - mostrar página en grande (Canvas)
    - arrastrar bordes para ajustar (handles)
    - guardar márgenes por página
    """

    def __init__(
        self,
        master: tk.Misc,
        page_idx: PageIndex,
        image: Optional["object"] = None,
        initial_margins: Optional[CropMargins] = None,
        on_save: Optional[Callable[[PageIndex, CropMargins], None]] = None,
    ):
        super().__init__(master)
        self.page_idx = page_idx
        self.on_save = on_save

        self.title(f"Recorte - Página {page_idx + 1}")
        self.geometry("900x700")

        self._margins: Tuple[int, int, int, int] = initial_margins or (0, 0, 0, 0)

        # Imagen base (PIL.Image). Si no viene, se crea demo para que el editor sea usable.
        self._pil_image = self._ensure_image(image)

        # Estado de render
        self._photo: Optional["object"] = None
        self._img_bbox: Optional[Tuple[int, int, int, int]] = None  # (x0,y0,x1,y1) en canvas
        self._scale: float = 1.0  # canvas_px = image_px * scale

        # Rectángulo de recorte en coordenadas de imagen (pixeles): (x0,y0,x1,y1)
        self._crop_rect_img: Tuple[float, float, float, float] = (0, 0, 1, 1)

        # Drag state
        self._active_edge: Optional[Literal["left", "right", "top", "bottom"]] = None
        self._drag_margin_px: int = 10  # tolerancia en px de canvas para “agarrar” borde

        # IDs canvas
        self._rect_id: Optional[int] = None
        self._shade_ids: Tuple[Optional[int], Optional[int], Optional[int], Optional[int]] = (None, None, None, None)
        self._handle_ids: Dict[str, Optional[int]] = {"left": None, "right": None, "top": None, "bottom": None}
        self._build()

        # Render inicial cuando el canvas ya tiene tamaño
        self.after(0, self._render_all)

    def _build(self) -> None:
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text=f"Editor de recorte (Página {self.page_idx + 1})", font=("Segoe UI", 12, "bold")).pack(
            anchor="w"
        )

        self._canvas = tk.Canvas(self, background="#1e1e1e", highlightthickness=0, cursor="tcross")
        self._canvas.pack(fill="both", expand=True, padx=12, pady=12)
        self._canvas.bind("<Configure>", lambda _e: self._render_all())
        self._canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self._canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_mouse_up)

        controls = ttk.Frame(self, padding=12)
        controls.pack(fill="x")

        self._left = tk.IntVar(value=self._margins[0])
        self._top = tk.IntVar(value=self._margins[1])
        self._right = tk.IntVar(value=self._margins[2])
        self._bottom = tk.IntVar(value=self._margins[3])

        ttk.Label(controls, text="Izq").pack(side="left")
        ttk.Entry(controls, textvariable=self._left, width=6).pack(side="left", padx=(4, 12))
        ttk.Label(controls, text="Sup").pack(side="left")
        ttk.Entry(controls, textvariable=self._top, width=6).pack(side="left", padx=(4, 12))
        ttk.Label(controls, text="Der").pack(side="left")
        ttk.Entry(controls, textvariable=self._right, width=6).pack(side="left", padx=(4, 12))
        ttk.Label(controls, text="Inf").pack(side="left")
        ttk.Entry(controls, textvariable=self._bottom, width=6).pack(side="left", padx=(4, 12))

        ttk.Button(controls, text="Aplicar valores", command=self._apply_entries_to_rect).pack(
            side="left", padx=(8, 0)
        )

        ttk.Button(controls, text="Guardar", command=self._save).pack(side="right")
        ttk.Button(controls, text="Cancelar", command=self.destroy).pack(side="right", padx=8)

    def _save(self) -> None:
        # Asegura sincronía desde el rect actual
        self._sync_entries_from_rect()
        margins: CropMargins = (int(self._left.get()), int(self._top.get()), int(self._right.get()), int(self._bottom.get()))
        if self.on_save is not None:
            self.on_save(self.page_idx, margins)
        self.destroy()

    # -----------------------------
    # Render / coordenadas
    # -----------------------------

    def _ensure_image(self, image: Optional["object"]) -> "object":
        from PIL import Image, ImageDraw, ImageFont

        if image is None:
            # Demo: hoja grande con margen visible
            img = Image.new("RGB", (1600, 2200), "white")
            d = ImageDraw.Draw(img)
            d.rectangle((80, 80, 1520, 2120), outline="#e6e6e6", width=8)
            for y in range(260, 2040, 110):
                d.line((180, y, 1420, y), fill="#222", width=6)
            try:
                font = ImageFont.truetype("arial.ttf", 72)
            except Exception:
                font = ImageFont.load_default()
            d.text((180, 140), "Vista previa (demo)", fill="#666", font=font)
            return img

        # PIL.Image
        try:
            from PIL import Image

            if isinstance(image, Image.Image):
                return image
        except Exception:
            pass

        raise TypeError("CropEditor espera una imagen PIL.Image.Image en el parámetro image.")

    def _render_all(self) -> None:
        """
        Renderiza imagen, sombreado y rectángulo de recorte.
        """
        from PIL import ImageTk

        cw = max(1, int(self._canvas.winfo_width()))
        ch = max(1, int(self._canvas.winfo_height()))

        # Espacio útil (deja padding visual)
        pad = 18
        avail_w = max(1, cw - 2 * pad)
        avail_h = max(1, ch - 2 * pad)

        img_w, img_h = self._pil_image.size
        scale = min(avail_w / img_w, avail_h / img_h)
        scale = max(0.05, float(scale))
        self._scale = scale

        disp_w = max(1, int(img_w * scale))
        disp_h = max(1, int(img_h * scale))

        x0 = (cw - disp_w) // 2
        y0 = (ch - disp_h) // 2
        x1 = x0 + disp_w
        y1 = y0 + disp_h
        self._img_bbox = (x0, y0, x1, y1)

        # Render imagen escalada
        disp = self._pil_image.resize((disp_w, disp_h))
        self._photo = ImageTk.PhotoImage(disp)

        self._canvas.delete("all")
        self._canvas.create_image(x0, y0, image=self._photo, anchor="nw")

        # Inicializa crop rect si aún no está (o si es inválido)
        self._init_crop_rect_if_needed()

        # Dibuja overlays
        self._draw_overlays()
        self._sync_entries_from_rect()

    def _init_crop_rect_if_needed(self) -> None:
        img_w, img_h = self._pil_image.size

        # Si rect no es válido, inicializa desde márgenes actuales
        x0, y0, x1, y1 = self._crop_rect_img
        if (x1 - x0) < 5 or (y1 - y0) < 5:
            l, t, r, b = self._margins
            l = max(0, min(int(l), img_w - 1))
            r = max(0, min(int(r), img_w - 1))
            t = max(0, min(int(t), img_h - 1))
            b = max(0, min(int(b), img_h - 1))
            x0 = float(l)
            y0 = float(t)
            x1 = float(img_w - r)
            y1 = float(img_h - b)
            # mínimo tamaño
            if (x1 - x0) < 10:
                x0, x1 = 0.0, float(img_w)
            if (y1 - y0) < 10:
                y0, y1 = 0.0, float(img_h)
            self._crop_rect_img = (x0, y0, x1, y1)

    def _img_to_canvas(self, x: float, y: float) -> Tuple[float, float]:
        if self._img_bbox is None:
            return (x, y)
        bx0, by0, _, _ = self._img_bbox
        return (bx0 + x * self._scale, by0 + y * self._scale)

    def _canvas_to_img(self, x: float, y: float) -> Tuple[float, float]:
        if self._img_bbox is None:
            return (x, y)
        bx0, by0, bx1, by1 = self._img_bbox
        x = max(bx0, min(x, bx1))
        y = max(by0, min(y, by1))
        return ((x - bx0) / self._scale, (y - by0) / self._scale)

    def _draw_overlays(self) -> None:
        assert self._img_bbox is not None

        bx0, by0, bx1, by1 = self._img_bbox
        x0i, y0i, x1i, y1i = self._crop_rect_img
        x0c, y0c = self._img_to_canvas(x0i, y0i)
        x1c, y1c = self._img_to_canvas(x1i, y1i)

        # Sombreado alrededor del área recortada
        shade = "#000000"
        alpha = 120  # simulado con stipple
        stipple = "gray50"

        top_id = self._canvas.create_rectangle(bx0, by0, bx1, y0c, fill=shade, outline="", stipple=stipple)
        left_id = self._canvas.create_rectangle(bx0, y0c, x0c, y1c, fill=shade, outline="", stipple=stipple)
        right_id = self._canvas.create_rectangle(x1c, y0c, bx1, y1c, fill=shade, outline="", stipple=stipple)
        bottom_id = self._canvas.create_rectangle(bx0, y1c, bx1, by1, fill=shade, outline="", stipple=stipple)
        self._shade_ids = (top_id, left_id, right_id, bottom_id)

        # Rect de recorte
        self._rect_id = self._canvas.create_rectangle(
            x0c, y0c, x1c, y1c, outline="#1f6feb", width=3
        )

        # Handles/bordes “agarrables” (líneas más gruesas)
        self._handle_ids["left"] = self._canvas.create_line(x0c, y0c, x0c, y1c, fill="#1f6feb", width=6)
        self._handle_ids["right"] = self._canvas.create_line(x1c, y0c, x1c, y1c, fill="#1f6feb", width=6)
        self._handle_ids["top"] = self._canvas.create_line(x0c, y0c, x1c, y0c, fill="#1f6feb", width=6)
        self._handle_ids["bottom"] = self._canvas.create_line(x0c, y1c, x1c, y1c, fill="#1f6feb", width=6)

        # Hint
        self._canvas.create_text(
            bx0 + 8,
            by0 + 8,
            text="Arrastra los bordes azules para recortar",
            fill="#ffffff",
            font=("Segoe UI", 10, "bold"),
            anchor="nw",
        )

    # -----------------------------
    # Interacción
    # -----------------------------

    def _on_mouse_down(self, event: tk.Event) -> None:
        if self._img_bbox is None:
            return

        # Determina borde más cercano dentro de tolerancia
        edge = self._hit_test_edge(float(event.x), float(event.y))
        self._active_edge = edge
        self._update_cursor(edge)

    def _on_mouse_drag(self, event: tk.Event) -> None:
        if self._active_edge is None or self._img_bbox is None:
            return

        img_x, img_y = self._canvas_to_img(float(event.x), float(event.y))
        x0, y0, x1, y1 = self._crop_rect_img

        # Clamp + mínimo tamaño
        min_w = 20.0
        min_h = 20.0
        img_w, img_h = self._pil_image.size

        if self._active_edge == "left":
            x0 = max(0.0, min(img_x, x1 - min_w))
        elif self._active_edge == "right":
            x1 = min(float(img_w), max(img_x, x0 + min_w))
        elif self._active_edge == "top":
            y0 = max(0.0, min(img_y, y1 - min_h))
        elif self._active_edge == "bottom":
            y1 = min(float(img_h), max(img_y, y0 + min_h))

        self._crop_rect_img = (x0, y0, x1, y1)

        # Re-render overlays (sin re-render de imagen)
        self._redraw_overlays_only()
        self._sync_entries_from_rect()

    def _on_mouse_up(self, _event: tk.Event) -> None:
        self._active_edge = None
        self._update_cursor(None)

    def _hit_test_edge(self, x_canvas: float, y_canvas: float) -> Optional[Literal["left", "right", "top", "bottom"]]:
        if self._img_bbox is None:
            return None
        x0i, y0i, x1i, y1i = self._crop_rect_img
        x0c, y0c = self._img_to_canvas(x0i, y0i)
        x1c, y1c = self._img_to_canvas(x1i, y1i)

        tol = float(self._drag_margin_px)
        near_left = abs(x_canvas - x0c) <= tol and (y0c - tol) <= y_canvas <= (y1c + tol)
        near_right = abs(x_canvas - x1c) <= tol and (y0c - tol) <= y_canvas <= (y1c + tol)
        near_top = abs(y_canvas - y0c) <= tol and (x0c - tol) <= x_canvas <= (x1c + tol)
        near_bottom = abs(y_canvas - y1c) <= tol and (x0c - tol) <= x_canvas <= (x1c + tol)

        # Prioridad: el más cercano
        candidates: List[Tuple[str, float]] = []
        if near_left:
            candidates.append(("left", abs(x_canvas - x0c)))
        if near_right:
            candidates.append(("right", abs(x_canvas - x1c)))
        if near_top:
            candidates.append(("top", abs(y_canvas - y0c)))
        if near_bottom:
            candidates.append(("bottom", abs(y_canvas - y1c)))

        if not candidates:
            return None
        candidates.sort(key=lambda t: t[1])
        return candidates[0][0]  # type: ignore[return-value]

    def _update_cursor(self, edge: Optional[str]) -> None:
        if edge in ("left", "right"):
            self._canvas.configure(cursor="sb_h_double_arrow")
        elif edge in ("top", "bottom"):
            self._canvas.configure(cursor="sb_v_double_arrow")
        else:
            self._canvas.configure(cursor="tcross")

    def _redraw_overlays_only(self) -> None:
        # Limpia y vuelve a dibujar overlays encima de la imagen (sin borrar la imagen)
        # Para simplicidad, re-render completo si aún no tenemos bbox.
        if self._img_bbox is None:
            self._render_all()
            return

        # Borrado parcial: recreamos todo encima de la imagen eliminando todo excepto el primer item (imagen)
        # (Como estamos dibujando todo desde cero en _render_all, aquí simplificamos: re-render completo rápido.)
        self._render_all()

    # -----------------------------
    # Sincronía con entradas
    # -----------------------------

    def _sync_entries_from_rect(self) -> None:
        img_w, img_h = self._pil_image.size
        x0, y0, x1, y1 = self._crop_rect_img

        left = int(round(max(0.0, x0)))
        top = int(round(max(0.0, y0)))
        right = int(round(max(0.0, float(img_w) - x1)))
        bottom = int(round(max(0.0, float(img_h) - y1)))

        self._left.set(left)
        self._top.set(top)
        self._right.set(right)
        self._bottom.set(bottom)

    def _apply_entries_to_rect(self) -> None:
        img_w, img_h = self._pil_image.size
        l = max(0, int(self._left.get()))
        t = max(0, int(self._top.get()))
        r = max(0, int(self._right.get()))
        b = max(0, int(self._bottom.get()))

        x0 = float(min(l, img_w - 1))
        y0 = float(min(t, img_h - 1))
        x1 = float(max(x0 + 20.0, img_w - r))
        y1 = float(max(y0 + 20.0, img_h - b))

        x1 = min(float(img_w), x1)
        y1 = min(float(img_h), y1)

        self._crop_rect_img = (x0, y0, x1, y1)
        self._render_all()


