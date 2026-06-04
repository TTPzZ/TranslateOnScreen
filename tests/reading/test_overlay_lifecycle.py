from __future__ import annotations

from screen_translator.domain.models import ScreenRegion
from screen_translator.overlay.layout import OverlayItem
from screen_translator.reading.lifecycle import OverlayLifecycle


class FakeOverlay:
    def __init__(self) -> None:
        self.items: list[OverlayItem] = []
        self.clear_calls = 0

    def show_items(self, items: list[OverlayItem]) -> None:
        self.items = items

    def clear(self) -> None:
        self.clear_calls += 1
        self.items = []


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_overlay_lifecycle_keeps_overlay_during_missing_timeout() -> None:
    clock = FakeClock(1.0)
    overlay = FakeOverlay()
    lifecycle = OverlayLifecycle(missing_timeout_ms=1000, clock=clock)
    lifecycle.text_seen(
        [OverlayItem("Hello", ScreenRegion(10, 20, 100, 30))],
        overlay,
    )

    clock.now = 1.5
    lifecycle.text_missing(overlay)

    assert overlay.clear_calls == 0
    assert [item.text for item in overlay.items] == ["Hello"]


def test_overlay_lifecycle_clears_after_missing_timeout() -> None:
    clock = FakeClock(1.0)
    overlay = FakeOverlay()
    lifecycle = OverlayLifecycle(missing_timeout_ms=1000, clock=clock)
    lifecycle.text_seen(
        [OverlayItem("Hello", ScreenRegion(10, 20, 100, 30))],
        overlay,
    )

    clock.now = 2.2
    lifecycle.text_missing(overlay)

    assert overlay.clear_calls == 1
    assert overlay.items == []
