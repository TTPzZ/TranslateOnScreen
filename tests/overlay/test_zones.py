from __future__ import annotations

import sys
import types

import pytest

from screen_translator.domain.models import ScreenRegion, TranslationZone, TranslationZoneMode
from screen_translator.overlay.zones import ZoneOverlayError, ZoneOverlayWindow


def test_zone_overlay_reports_missing_pyqt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "PyQt6", None)

    with pytest.raises(ZoneOverlayError, match="PyQt6 is required"):
        ZoneOverlayWindow().show_zones(
            [
                TranslationZone(
                    id="zone-1",
                    name="Dialog",
                    region=ScreenRegion(10, 20, 100, 40),
                    created_at="2026-06-04T12:00:00+00:00",
                    updated_at="2026-06-04T12:00:00+00:00",
                )
            ]
        )


def test_zone_overlay_normal_mode_is_click_through_and_draws_visible_zone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels: list[object] = []
    windows: list[object] = []
    _install_fake_qt(monkeypatch, labels, windows)

    ZoneOverlayWindow().show_zones(
        [
            TranslationZone(
                id="zone-1",
                name="Dialog",
                region=ScreenRegion(10, 20, 100, 40),
                created_at="2026-06-04T12:00:00+00:00",
                updated_at="2026-06-04T12:00:00+00:00",
            ),
            TranslationZone(
                id="zone-2",
                name="Hidden",
                region=ScreenRegion(200, 20, 100, 40),
                visible=False,
                created_at="2026-06-04T12:00:00+00:00",
                updated_at="2026-06-04T12:00:00+00:00",
            ),
        ],
        edit_mode=False,
        show_borders=True,
    )

    assert len(labels) == 1
    assert labels[0].text == ""
    assert labels[0].geometry == (10, 20, 100, 40)
    assert labels[0].word_wrap is False
    assert "0, 200, 255" in labels[0].stylesheet
    assert windows[0].flags & 8
    assert 4 in windows[0].attributes


def test_zone_overlay_hides_all_borders_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    labels: list[object] = []
    windows: list[object] = []
    _install_fake_qt(monkeypatch, labels, windows)

    ZoneOverlayWindow().show_zones(
        [
            TranslationZone(
                id="zone-1",
                name="Dialog",
                region=ScreenRegion(10, 20, 100, 40),
                created_at="2026-06-04T12:00:00+00:00",
                updated_at="2026-06-04T12:00:00+00:00",
            )
        ],
        show_borders=False,
    )

    assert labels == []
    assert windows[0].fullscreen is True


def test_zone_overlay_edit_mode_keeps_toolbar_clickable(monkeypatch: pytest.MonkeyPatch) -> None:
    labels: list[object] = []
    windows: list[object] = []
    buttons: list[object] = []
    combos: list[object] = []
    _install_fake_qt(monkeypatch, labels, windows, buttons=buttons, combos=combos)
    actions: list[tuple[str, str, str | None]] = []
    overlay = ZoneOverlayWindow()
    overlay.set_callbacks(
        on_delete=lambda zone_id: actions.append(("delete", zone_id, None)) or True,
        on_move=lambda zone_id: actions.append(("move", zone_id, None)) or True,
        on_style_change=lambda zone_id, style: actions.append(("style", zone_id, style)) or True,
        on_mode_change=lambda zone_id, mode: actions.append(("mode", zone_id, mode)) or True,
    )

    overlay.show_zones(
        [
            TranslationZone(
                id="zone-1",
                name="Dialog",
                region=ScreenRegion(10, 20, 100, 40),
                created_at="2026-06-04T12:00:00+00:00",
                updated_at="2026-06-04T12:00:00+00:00",
            )
        ],
        edit_mode=True,
        show_borders=True,
    )

    assert not (windows[0].flags & 8)
    assert 4 not in windows[0].attributes
    assert labels[0].text == ""
    assert [button.text for button in buttons] == ["X", "Move"]
    assert [combo.items for combo in combos] == [
        ["floating_panel", "inline_replace"],
        ["reading", "gaming", "both", "disabled"],
    ]
    assert [combo.current_text for combo in combos] == ["floating_panel", "reading"]
    assert all("QComboBox QAbstractItemView" in combo.stylesheet for combo in combos)
    assert all("background-color: #ffffff" in combo.stylesheet for combo in combos)
    assert all("color: #111111" in combo.stylesheet for combo in combos)
    assert all("selection-background-color" in combo.stylesheet for combo in combos)

    buttons[0].click()
    buttons[1].click()
    combos[0].setCurrentText("inline_replace")
    combos[1].setCurrentText("both")

    assert actions == [
        ("delete", "zone-1", None),
        ("move", "zone-1", None),
        ("style", "zone-1", "inline_replace"),
        ("mode", "zone-1", "both"),
    ]


def test_zone_overlay_uses_green_border_for_inline_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    labels: list[object] = []
    windows: list[object] = []
    _install_fake_qt(monkeypatch, labels, windows)

    ZoneOverlayWindow().show_zones(
        [
            TranslationZone(
                id="zone-1",
                name="Inline",
                region=ScreenRegion(10, 20, 100, 40),
                overlay_style="inline_replace",
                mode=TranslationZoneMode.BOTH,
                created_at="2026-06-04T12:00:00+00:00",
                updated_at="2026-06-04T12:00:00+00:00",
            )
        ],
        edit_mode=False,
        show_borders=True,
    )

    assert "0, 210, 120" in labels[0].stylesheet


def test_zone_overlay_clear_closes_window(monkeypatch: pytest.MonkeyPatch) -> None:
    labels: list[object] = []
    windows: list[object] = []
    _install_fake_qt(monkeypatch, labels, windows)
    overlay = ZoneOverlayWindow()
    overlay.show_zones(
        [
            TranslationZone(
                id="zone-1",
                name="Dialog",
                region=ScreenRegion(10, 20, 100, 40),
                created_at="2026-06-04T12:00:00+00:00",
                updated_at="2026-06-04T12:00:00+00:00",
            )
        ]
    )

    overlay.clear()

    assert windows[0].closed is True


def test_zone_overlay_hides_and_restores_for_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    labels: list[object] = []
    windows: list[object] = []
    _install_fake_qt(monkeypatch, labels, windows)
    overlay = ZoneOverlayWindow()
    overlay.show_zones(
        [
            TranslationZone(
                id="zone-1",
                name="Dialog",
                region=ScreenRegion(10, 20, 100, 40),
                created_at="2026-06-04T12:00:00+00:00",
                updated_at="2026-06-04T12:00:00+00:00",
            )
        ]
    )

    overlay.hide_for_capture()
    overlay.restore_after_capture()

    assert windows[0].hide_calls == 1
    assert windows[0].fullscreen_calls == 2


def test_zone_overlay_hides_only_chrome_intersecting_capture_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels: list[object] = []
    windows: list[object] = []
    buttons: list[object] = []
    combos: list[object] = []
    _install_fake_qt(monkeypatch, labels, windows, buttons=buttons, combos=combos)
    overlay = ZoneOverlayWindow()
    overlay.show_zones(
        [
            TranslationZone(
                id="zone-1",
                name="Dialog",
                region=ScreenRegion(10, 20, 100, 40),
                created_at="2026-06-04T12:00:00+00:00",
                updated_at="2026-06-04T12:00:00+00:00",
            ),
            TranslationZone(
                id="zone-2",
                name="Menu",
                region=ScreenRegion(300, 20, 100, 40),
                created_at="2026-06-04T12:00:00+00:00",
                updated_at="2026-06-04T12:00:00+00:00",
            ),
        ],
        edit_mode=True,
        show_borders=True,
    )

    result = overlay.hide_for_capture_regions((ScreenRegion(0, 0, 150, 100),))

    assert result == (2, 2)
    assert labels[0].visible is False
    assert labels[1].visible is True
    assert windows[1].visible is False
    assert windows[2].visible is True
    assert windows[0].hide_calls == 0

    overlay.restore_after_capture()

    assert labels[0].visible is True
    assert labels[1].visible is True
    assert windows[1].visible is True
    assert windows[2].visible is True
    assert windows[0].fullscreen_calls == 1


def _install_fake_qt(
    monkeypatch: pytest.MonkeyPatch,
    labels: list[object],
    windows: list[object],
    *,
    buttons: list[object] | None = None,
    combos: list[object] | None = None,
) -> None:
    buttons = buttons if buttons is not None else []
    combos = combos if combos is not None else []

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
        AlignTop = 4

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
        def __init__(self, *args) -> None:
            del args
            self.fullscreen = False
            self.fullscreen_calls = 0
            self.hide_calls = 0
            self.attributes = set()
            self.auto_fill_background = None
            self.closed = False
            windows.append(self)

        def setWindowFlags(self, flags: int) -> None:
            self.flags = flags

        def setAttribute(self, attribute: int, enabled: bool = True) -> None:
            if enabled:
                self.attributes.add(attribute)
            else:
                self.attributes.discard(attribute)

        def setAutoFillBackground(self, enabled: bool) -> None:
            self.auto_fill_background = enabled

        def setStyleSheet(self, stylesheet: str) -> None:
            self.stylesheet = stylesheet

        def setGeometry(self, x: int, y: int, width: int, height: int) -> None:
            self.geometry = (x, y, width, height)

        def show(self) -> None:
            self.visible = True

        def showFullScreen(self) -> None:
            self.fullscreen = True
            self.fullscreen_calls += 1

        def hide(self) -> None:
            self.fullscreen = False
            self.visible = False
            self.hide_calls += 1

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

    class Signal:
        def __init__(self) -> None:
            self.callback = None

        def connect(self, callback) -> None:
            self.callback = callback

        def emit(self, *args) -> None:
            if self.callback is not None:
                self.callback(*args)

    class QPushButton:
        def __init__(self, text: str, parent: object | None = None) -> None:
            self.text = text
            self.parent = parent
            self.clicked = Signal()
            buttons.append(self)

        def setFixedSize(self, width: int, height: int) -> None:
            self.fixed_size = (width, height)

        def setStyleSheet(self, stylesheet: str) -> None:
            self.stylesheet = stylesheet

        def click(self) -> None:
            self.clicked.emit()

    class QComboBox:
        def __init__(self, parent: object | None = None) -> None:
            self.parent = parent
            self.items: list[str] = []
            self.current_text = ""
            self.currentTextChanged = Signal()
            combos.append(self)

        def addItems(self, items) -> None:
            self.items.extend(list(items))

        def setCurrentText(self, text: str) -> None:
            self.current_text = text
            self.currentTextChanged.emit(text)

        def setFixedHeight(self, height: int) -> None:
            self.fixed_height = height

        def setStyleSheet(self, stylesheet: str) -> None:
            self.stylesheet = stylesheet

    class QHBoxLayout:
        def __init__(self, parent: object | None = None) -> None:
            self.parent = parent
            self.widgets = []

        def setContentsMargins(self, left: int, top: int, right: int, bottom: int) -> None:
            self.margins = (left, top, right, bottom)

        def setSpacing(self, spacing: int) -> None:
            self.spacing = spacing

        def addWidget(self, widget) -> None:
            self.widgets.append(widget)

    qt_core = types.ModuleType("PyQt6.QtCore")
    qt_core.Qt = Qt
    qt_widgets = types.ModuleType("PyQt6.QtWidgets")
    qt_widgets.QApplication = QApplication
    qt_widgets.QWidget = QWidget
    qt_widgets.QLabel = QLabel
    qt_widgets.QPushButton = QPushButton
    qt_widgets.QComboBox = QComboBox
    qt_widgets.QHBoxLayout = QHBoxLayout
    pyqt = types.ModuleType("PyQt6")
    pyqt.QtCore = qt_core
    pyqt.QtWidgets = qt_widgets

    monkeypatch.setitem(sys.modules, "PyQt6", pyqt)
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", qt_core)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", qt_widgets)
