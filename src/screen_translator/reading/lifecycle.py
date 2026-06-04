from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Protocol

from screen_translator.overlay.layout import OverlayItem


class OverlayRenderer(Protocol):
    def show_items(self, items: list[OverlayItem]) -> None:
        """Show translated overlay items."""

    def clear(self) -> None:
        """Clear translated overlay items."""


class OverlayLifecycle:
    """Keep reading overlays visible until text has been missing long enough."""

    def __init__(
        self,
        *,
        missing_timeout_ms: int,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._missing_timeout_ms = missing_timeout_ms
        self._clock = clock
        self._last_seen_ms: float | None = None
        self._visible = False

    def text_seen(self, items: list[OverlayItem], overlay: OverlayRenderer) -> None:
        self._last_seen_ms = self._now_ms()
        self._visible = True
        overlay.show_items(items)

    def text_missing(self, overlay: OverlayRenderer) -> bool:
        if not self._visible:
            return False
        if self._last_seen_ms is None:
            overlay.clear()
            self._visible = False
            return True
        if self._now_ms() - self._last_seen_ms > self._missing_timeout_ms:
            overlay.clear()
            self._visible = False
            return True
        return False

    def _now_ms(self) -> float:
        return self._clock() * 1000
