from __future__ import annotations

import logging

from screen_translator.capture.overlay_guard import OverlayCaptureGuard
from screen_translator.domain.models import ScreenRegion


class FakeOverlay:
    def __init__(self) -> None:
        self.visible = True
        self.events: list[str] = []

    def hide_for_capture(self) -> None:
        self.events.append("hide")
        self.visible = False

    def restore_after_capture(self) -> None:
        self.events.append("restore")
        self.visible = True


class FakeUiDispatcher:
    def __init__(self) -> None:
        self.calls: list[int | None] = []

    def run_sync(self, action, *, timeout_ms: int | None = None) -> None:
        self.calls.append(timeout_ms)
        action()


class RestoreFailingOverlay(FakeOverlay):
    def restore_after_capture(self) -> None:
        self.events.append("restore")
        raise RuntimeError("restore failed")


class GeometryAwareOverlay:
    def __init__(self, *, hidden_count: int, skipped_count: int) -> None:
        self.hidden_count = hidden_count
        self.skipped_count = skipped_count
        self.events: list[object] = []
        self.restored = False

    def hide_for_capture_regions(self, capture_regions) -> tuple[int, int]:
        self.events.append(tuple(capture_regions))
        return (self.hidden_count, self.skipped_count)

    def restore_after_capture(self) -> None:
        self.events.append("restore")
        self.restored = True


def test_overlay_capture_guard_hides_and_restores_visible_overlays(
    caplog,
) -> None:
    overlay = FakeOverlay()
    guard = OverlayCaptureGuard([overlay])

    with caplog.at_level(logging.DEBUG, logger="screen_translator.capture.overlay_guard"):
        with guard.hidden_for_capture():
            assert overlay.visible is False

    assert overlay.visible is True
    assert overlay.events == ["hide", "restore"]
    assert "overlays hidden before capture" in caplog.text
    assert "overlays restored after capture" in caplog.text
    assert "capture_without_overlays=true" in caplog.text


def test_overlay_capture_guard_dispatches_overlay_calls_to_ui_thread() -> None:
    overlay = FakeOverlay()
    dispatcher = FakeUiDispatcher()
    guard = OverlayCaptureGuard([overlay], ui_dispatcher=dispatcher, timeout_ms=250)

    with guard.hidden_for_capture():
        assert overlay.visible is False

    assert overlay.visible is True
    assert overlay.events == ["hide", "restore"]
    assert dispatcher.calls == [250, 250]


def test_overlay_capture_guard_restores_after_capture_error() -> None:
    overlay = FakeOverlay()
    guard = OverlayCaptureGuard([overlay])

    try:
        with guard.hidden_for_capture():
            raise RuntimeError("capture failed")
    except RuntimeError:
        pass

    assert overlay.visible is True
    assert overlay.events == ["hide", "restore"]


def test_overlay_capture_guard_attempts_remaining_restores_after_restore_error(
    caplog,
) -> None:
    first = FakeOverlay()
    second = RestoreFailingOverlay()
    guard = OverlayCaptureGuard([first, second])

    with caplog.at_level(logging.DEBUG, logger="screen_translator.capture.overlay_guard"):
        with guard.hidden_for_capture():
            assert first.visible is False
            assert second.visible is False

    assert first.visible is True
    assert first.events == ["hide", "restore"]
    assert second.events == ["hide", "restore"]
    assert "overlay restore failed" in caplog.text


def test_overlay_capture_guard_skips_non_overlapping_geometry_aware_overlays(
    caplog,
) -> None:
    overlay = GeometryAwareOverlay(hidden_count=0, skipped_count=2)
    guard = OverlayCaptureGuard([overlay])
    capture_regions = (ScreenRegion(10, 20, 100, 40),)

    with caplog.at_level(logging.DEBUG, logger="screen_translator.capture.overlay_guard"):
        with guard.hidden_for_capture(capture_regions=capture_regions):
            assert overlay.restored is False

    assert overlay.events == [capture_regions]
    assert overlay.restored is False
    assert "hidden_overlay_count=0" in caplog.text
    assert "skipped_overlay_count=2" in caplog.text
    assert "capture_regions=1" in caplog.text


def test_overlay_capture_guard_restores_overlapping_geometry_aware_overlays() -> None:
    overlay = GeometryAwareOverlay(hidden_count=1, skipped_count=1)
    guard = OverlayCaptureGuard([overlay])

    with guard.hidden_for_capture(capture_regions=(ScreenRegion(10, 20, 100, 40),)):
        assert overlay.restored is False

    assert overlay.restored is True
    assert overlay.events[-1] == "restore"


def test_overlay_capture_guard_restores_hidden_geometry_items_after_capture_error() -> None:
    overlay = GeometryAwareOverlay(hidden_count=1, skipped_count=0)
    guard = OverlayCaptureGuard([overlay])

    try:
        with guard.hidden_for_capture(capture_regions=(ScreenRegion(10, 20, 100, 40),)):
            raise RuntimeError("capture failed")
    except RuntimeError:
        pass

    assert overlay.restored is True
