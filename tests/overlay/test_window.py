from __future__ import annotations

import sys
import types

import pytest

from screen_translator.overlay.layout import OverlayItem
from screen_translator.domain.models import ScreenRegion
from screen_translator.overlay import window as overlay_window_module
from screen_translator.overlay.window import (
    BlurOverlayWindow,
    OverlayError,
    _clamp_items_to_window,
)


def test_blur_overlay_window_reports_missing_pyqt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "PyQt6", None)

    with pytest.raises(OverlayError, match="PyQt6 is required"):
        BlurOverlayWindow().show_items(
            [OverlayItem(text="Xin chao", region=ScreenRegion(10, 20, 100, 30))]
        )


def test_blur_overlay_window_limits_visible_background_to_translation_panels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels: list[object] = []
    _install_fake_qt(monkeypatch, labels)
    blur_calls: list[int] = []
    monkeypatch.setattr(
        overlay_window_module,
        "_try_enable_windows_blur",
        lambda window_id: blur_calls.append(window_id),
    )

    BlurOverlayWindow().show_items(
        [OverlayItem(text="Xin chao", region=ScreenRegion(10, 20, 140, 36))]
    )

    assert blur_calls == []
    assert len(labels) == 1
    assert labels[0].geometry == (10, 20, 140, 36)
    assert labels[0].geometry != (0, 0, 1920, 1080)


def test_blur_overlay_window_parent_is_transparent_and_click_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels: list[object] = []
    windows: list[object] = []
    _install_fake_qt(monkeypatch, labels, windows=windows)

    BlurOverlayWindow().show_items(
        [OverlayItem(text="Xin chao", region=ScreenRegion(10, 20, 140, 36))]
    )

    window = windows[0]
    assert window.flags & 8
    assert window.attributes == {1, 2, 4, 8}
    assert window.auto_fill_background is False

    event = types.SimpleNamespace(ignored=False, ignore=lambda: setattr(event, "ignored", True))
    window.paintEvent(event)

    assert event.ignored is True
    assert window.paint_fill_calls == []


def test_blur_overlay_window_passes_vietnamese_text_to_qt_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels: list[object] = []
    _install_fake_qt(monkeypatch, labels)

    BlurOverlayWindow().show_items(
        [
            OverlayItem(text="Xin chào thế giới", region=ScreenRegion(10, 20, 220, 48)),
            OverlayItem(text="Hoàn thành nhiệm vụ", region=ScreenRegion(10, 80, 240, 48)),
            OverlayItem(text="Mở cửa", region=ScreenRegion(10, 140, 120, 48)),
        ]
    )

    assert [label.text for label in labels] == [
        "Xin chào thế giới",
        "Hoàn thành nhiệm vụ",
        "Mở cửa",
    ]


def test_blur_overlay_window_auto_hides_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels: list[object] = []
    timer_calls: list[tuple[int, object]] = []
    windows: list[object] = []
    _install_fake_qt(monkeypatch, labels, timer_calls=timer_calls, windows=windows)
    overlay = BlurOverlayWindow()

    overlay.show_items(
        [OverlayItem(text="Xin chao", region=ScreenRegion(10, 20, 140, 36))]
    )
    overlay.clear_after(5000)

    assert len(timer_calls) == 1
    assert timer_calls[0][0] == 5000
    assert not getattr(windows[0], "closed", False)

    timer_calls[0][1]()

    assert windows[0].closed is True


def test_blur_overlay_window_hides_and_restores_for_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels: list[object] = []
    windows: list[object] = []
    _install_fake_qt(monkeypatch, labels, windows=windows)
    overlay = BlurOverlayWindow()
    overlay.show_items(
        [OverlayItem(text="Xin chao", region=ScreenRegion(10, 20, 140, 36))]
    )

    overlay.hide_for_capture()
    overlay.restore_after_capture()

    assert windows[0].hide_calls == 1
    assert windows[0].fullscreen_calls == 2


def test_blur_overlay_window_hides_only_items_intersecting_capture_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels: list[object] = []
    windows: list[object] = []
    _install_fake_qt(monkeypatch, labels, windows=windows)
    overlay = BlurOverlayWindow()
    overlay.show_items(
        [
            OverlayItem(text="Overlap", region=ScreenRegion(10, 20, 140, 36)),
            OverlayItem(text="Outside", region=ScreenRegion(400, 20, 140, 36)),
        ]
    )

    result = overlay.hide_for_capture_regions((ScreenRegion(0, 0, 200, 100),))

    assert result == (1, 1)
    assert labels[0].visible is False
    assert labels[1].visible is True
    assert windows[0].hide_calls == 0

    overlay.restore_after_capture()

    assert labels[0].visible is True
    assert labels[1].visible is True
    assert windows[0].fullscreen_calls == 1


def test_blur_overlay_window_skips_non_overlapping_items_without_hiding_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels: list[object] = []
    windows: list[object] = []
    _install_fake_qt(monkeypatch, labels, windows=windows)
    overlay = BlurOverlayWindow()
    overlay.show_items(
        [OverlayItem(text="Outside", region=ScreenRegion(400, 20, 140, 36))]
    )

    result = overlay.hide_for_capture_regions((ScreenRegion(0, 0, 200, 100),))
    overlay.restore_after_capture()

    assert result == (0, 1)
    assert labels[0].visible is True
    assert windows[0].hide_calls == 0
    assert windows[0].fullscreen_calls == 1


def test_blur_overlay_window_renders_inline_item_style(monkeypatch: pytest.MonkeyPatch) -> None:
    labels: list[object] = []
    _install_fake_qt(monkeypatch, labels)

    BlurOverlayWindow().show_items(
        [
            OverlayItem(
                text="Xin chao",
                region=ScreenRegion(10, 20, 140, 36),
                style="inline_replace",
                font_size=12,
                padding=6,
                overflow=True,
            )
        ]
    )

    assert labels[0].text == "Xin chao..."
    assert labels[0].word_wrap is True
    assert "font-size: 12px;" in labels[0].stylesheet
    assert "padding: 6px;" in labels[0].stylesheet
    assert "border-radius: 2px;" in labels[0].stylesheet


def test_clamp_items_to_window_keeps_panels_non_overlapping_near_bottom() -> None:
    class Window:
        def width(self) -> int:
            return 240

        def height(self) -> int:
            return 140

    items = [
        OverlayItem("Một", ScreenRegion(10, 100, 120, 50)),
        OverlayItem("Hai", ScreenRegion(20, 110, 120, 50)),
    ]

    clamped = _clamp_items_to_window(items, Window())

    assert clamped[0].region.bottom + 6 <= clamped[1].region.y
    assert clamped[1].region.bottom <= 140


def _install_fake_qt(
    monkeypatch: pytest.MonkeyPatch,
    labels: list[object],
    *,
    timer_calls: list[tuple[int, object]] | None = None,
    windows: list[object] | None = None,
) -> None:
    class WindowType:
        FramelessWindowHint = 1
        WindowStaysOnTopHint = 2
        Tool = 4
        WindowTransparentForInput = 8

    class WidgetAttribute:
        WA_TranslucentBackground = 1
        WA_ShowWithoutActivating = 2
        WA_TransparentForMouseEvents = 4
        WA_NoSystemBackground = 8

    class AlignmentFlag:
        AlignLeft = 1
        AlignVCenter = 2

    class QTimer:
        @staticmethod
        def singleShot(interval_ms: int, callback: object) -> None:
            if timer_calls is not None:
                timer_calls.append((interval_ms, callback))

    Qt = types.SimpleNamespace(
        WindowType=WindowType,
        WidgetAttribute=WidgetAttribute,
        AlignmentFlag=AlignmentFlag,
    )

    class QApplication:
        _instance = None

        def __init__(self, args: list[str]) -> None:
            del args
            QApplication._instance = self

        @classmethod
        def instance(cls) -> object | None:
            return cls._instance

        def processEvents(self) -> None:
            return None

    class QWidget:
        def __init__(self) -> None:
            self.fullscreen = False
            self.fullscreen_calls = 0
            self.hide_calls = 0
            self.attributes = set()
            self.auto_fill_background = None
            self.paint_fill_calls = []
            if windows is not None:
                windows.append(self)

        def setWindowFlags(self, flags: int) -> None:
            self.flags = flags

        def setAttribute(self, attribute: int) -> None:
            self.attributes.add(attribute)

        def setAutoFillBackground(self, enabled: bool) -> None:
            self.auto_fill_background = enabled

        def showFullScreen(self) -> None:
            self.fullscreen = True
            self.fullscreen_calls += 1

        def hide(self) -> None:
            self.fullscreen = False
            self.hide_calls += 1

        def winId(self) -> int:
            return 99

        def close(self) -> None:
            self.closed = True

    class QLabel:
        def __init__(self, text: str, parent: QWidget) -> None:
            self.text = text
            self.parent = parent
            labels.append(self)

        def deleteLater(self) -> None:
            self.deleted = True

        def setWordWrap(self, enabled: bool) -> None:
            self.word_wrap = enabled

        def setAlignment(self, alignment: int) -> None:
            self.alignment = alignment

        def setStyleSheet(self, stylesheet: str) -> None:
            self.stylesheet = stylesheet

        def setGeometry(self, x: int, y: int, width: int, height: int) -> None:
            self.geometry = (x, y, width, height)

        def show(self) -> None:
            self.visible = True

        def hide(self) -> None:
            self.visible = False
            self.hide_calls = getattr(self, "hide_calls", 0) + 1

    qt_core = types.ModuleType("PyQt6.QtCore")
    qt_core.Qt = Qt
    qt_core.QTimer = QTimer
    qt_widgets = types.ModuleType("PyQt6.QtWidgets")
    qt_widgets.QApplication = QApplication
    qt_widgets.QWidget = QWidget
    qt_widgets.QLabel = QLabel
    pyqt = types.ModuleType("PyQt6")
    pyqt.QtCore = qt_core
    pyqt.QtWidgets = qt_widgets

    monkeypatch.setitem(sys.modules, "PyQt6", pyqt)
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", qt_core)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", qt_widgets)
