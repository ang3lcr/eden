from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Union

from core.app_state import AppState
from ui.start_screen import StartScreen


@dataclass
class NavigationRequest:
    """Solicitud de navegación entre pantallas."""

    target: str


class App(tk.Frame):
    """
    Contenedor principal de la aplicación.

    Maneja:
    - estado compartido (AppState)
    - navegación entre pantallas (Frames)
    """

    def __init__(self, master: tk.Misc):
        super().__init__(master)
        self.state = AppState()

        self._current: Optional[tk.Frame] = None
        self._screens: dict[str, "ScreenFactory"] = {"start": lambda parent, state, nav: StartScreen(parent, state, nav)}

        self.show("start")

    def register_screen(self, key: str, screen: "ScreenFactory") -> None:
        self._screens[key] = screen

    def show(self, key: str) -> None:
        if key not in self._screens:
            raise KeyError(f"Pantalla no registrada: {key}")

        if self._current is not None:
            self._current.destroy()

        factory = self._screens[key]
        self._current = factory(self, self.state, self.show)
        self._current.pack(fill="both", expand=True)


class ScreenFactory(Protocol):
    def __call__(self, parent: tk.Misc, state: AppState, on_navigate: Callable[[str], None]) -> tk.Frame: ...

