from __future__ import annotations

import logging
import sys
import traceback

from screen_translator.cache.sqlite_cache import SQLiteTranslationCache
from screen_translator.capture.overlay_guard import OverlayCaptureGuard
from screen_translator.capture.qt_capture import QtScreenCapture
from screen_translator.config import AppConfig
from screen_translator.controller.mode_controller import ModeController
from screen_translator.diagnostics import paddle_runtime_version_statuses
from screen_translator.app import GamingModePipeline
from screen_translator.hotkeys.windows import (
    HotkeyRegistrationError,
    WindowsGlobalHotkey,
    hotkey_spec_from_text,
)
from screen_translator.instrumentation import RuntimeMetrics
from screen_translator.logging_config import configure_logging
from screen_translator.ocr.paddle_provider import PaddleOcrProvider
from screen_translator.overlay.layout import OverlayStyle
from screen_translator.overlay.window import BlurOverlayWindow
from screen_translator.overlay.zones import ZoneOverlayWindow
from screen_translator.reading.async_pipeline import AsyncReadingModeRunner
from screen_translator.reading.pipeline import ReadingModePipeline
from screen_translator.region.selector import QtRegionSelector
from screen_translator.translation.client import HttpTranslationClient
from screen_translator.ui.control_panel import ControlPanelWindow
from screen_translator.ui.server_process import LocalServerController
from screen_translator.ui.settings import ControlPanelSettings, SettingsStore
from screen_translator.worker.pyqt import PyQtWorker
from screen_translator.worker.qt_dispatcher import QtUiThreadDispatcher
from screen_translator.worker.pyqt_timer import PyQtTimer

logger = logging.getLogger(__name__)


def build_control_panel(config: AppConfig | None = None) -> ControlPanelWindow:
    base_config = config or AppConfig()
    settings_store = SettingsStore()
    settings = settings_store.load(fallback=ControlPanelSettings.from_config(base_config))
    runtime_config = settings.to_config(base_config)
    selector = QtRegionSelector()
    capture = QtScreenCapture()
    metrics = RuntimeMetrics()
    ocr = PaddleOcrProvider(min_confidence=runtime_config.reading_min_confidence)
    ocr.warm_up()
    cache = SQLiteTranslationCache(runtime_config.cache_path)
    translation_client = HttpTranslationClient(runtime_config.translation_server_url)
    reading_overlay = BlurOverlayWindow(style=_overlay_style_from_config(runtime_config))
    gaming_overlay = BlurOverlayWindow(style=_overlay_style_from_config(runtime_config))
    zone_overlay = ZoneOverlayWindow()
    capture_guard = OverlayCaptureGuard(
        [reading_overlay, gaming_overlay, zone_overlay],
        ui_dispatcher=QtUiThreadDispatcher(),
        timeout_ms=1000,
    )
    pipeline = ReadingModePipeline(
        selector=selector,
        capture=capture,
        ocr=ocr,
        cache=cache,
        translation_client=translation_client,
        overlay=reading_overlay,
        config=runtime_config,
        runtime_metrics=metrics,
        capture_guard=capture_guard,
    )
    pipeline.set_zones(settings.zones)
    gaming_pipeline = GamingModePipeline(
        selector=selector,
        capture=capture,
        ocr=ocr,
        cache=cache,
        translation_client=translation_client,
        overlay=gaming_overlay,
        config=runtime_config,
        runtime_metrics=metrics,
        capture_guard=capture_guard,
    )
    runner_holder: dict[str, AsyncReadingModeRunner] = {}
    timer = PyQtTimer(lambda: runner_holder["runner"].on_interval())
    runner = AsyncReadingModeRunner(
        pipeline=pipeline,
        worker=PyQtWorker(),
        timer=timer,
        metrics=metrics,
        interval_ms=runtime_config.reading_interval_ms,
    )
    runner_holder["runner"] = runner
    config_holder = {"config": runtime_config}

    def apply_runtime_settings(new_settings: ControlPanelSettings) -> list[str]:
        next_config = new_settings.to_config(config_holder["config"])
        next_client = HttpTranslationClient(next_config.translation_server_url)
        pipeline.update_config(next_config, translation_client=next_client)
        pipeline.set_zones(new_settings.zones)
        gaming_pipeline.update_config(next_config, translation_client=next_client)
        runner.set_interval_ms(next_config.reading_interval_ms)
        style = _overlay_style_from_config(next_config)
        reading_overlay.set_style(style)
        gaming_overlay.set_style(style)
        config_holder["config"] = next_config
        return ["Settings saved"]

    controller = ModeController(
        selector=selector,
        reading_runner=runner,
        gaming_hotkey_status="unregistered",
        debug_mode=runtime_config.debug_mode,
        gaming_pipeline=gaming_pipeline,
        runtime_metrics=metrics,
        gaming_dismiss_hotkey_label=runtime_config.gaming_dismiss_hotkey,
        settings=settings,
        settings_store=settings_store,
        server_controller=LocalServerController(),
        runtime_settings_applier=apply_runtime_settings,
        zone_overlay=zone_overlay,
    )
    try:
        hotkey_spec = hotkey_spec_from_text(runtime_config.gaming_hotkey, identifier=1)
        hotkey = WindowsGlobalHotkey(callback=controller.handle_hotkey_pressed, spec=hotkey_spec)
    except HotkeyRegistrationError as exc:
        controller.report_hotkey_failed(exc)
        hotkey = None
    try:
        dismiss_spec = hotkey_spec_from_text(
            runtime_config.gaming_dismiss_hotkey,
            identifier=2,
        )
        controller.gaming_dismiss_hotkey_label = dismiss_spec.label
        dismiss_hotkey = WindowsGlobalHotkey(
            callback=controller.handle_gaming_dismiss_hotkey_pressed,
            spec=dismiss_spec,
        )
    except HotkeyRegistrationError as exc:
        controller.report_gaming_dismiss_hotkey_failed(exc)
        dismiss_hotkey = None
    return ControlPanelWindow(controller, hotkey=hotkey, dismiss_hotkey=dismiss_hotkey)


def _overlay_style_from_config(config: AppConfig) -> OverlayStyle:
    return OverlayStyle(
        background_rgba=(0, 0, 0, config.overlay_panel_opacity),
        font_size=config.overlay_font_size,
    )


def main() -> int:
    configure_logging()
    try:
        _print_and_log(f"Python executable: {sys.executable}")
        _print_and_log(f"Python version: {sys.version.split()[0]}")
        _print_and_log(f"PyQt6 loaded: {_pyqt6_status()}")
        for status in paddle_runtime_version_statuses():
            _print_and_log(f"{status.name}: {status.message}")
        panel = build_control_panel()
        _print_and_log("Entering Qt event loop")
        exit_code = panel.run()
        _print_and_log(f"Qt event loop exit code: {exit_code}")
        return exit_code
    except Exception:
        logger.exception("Control panel failed")
        traceback.print_exc()
        return 1


def _print_and_log(message: str) -> None:
    print(f"[control_app] {message}", flush=True)
    logger.info(message)


def _pyqt6_status() -> str:
    try:
        from PyQt6 import QtCore, QtWidgets  # noqa: F401
    except Exception as exc:
        return f"failed: {exc}"
    return "yes"


if __name__ == "__main__":
    raise SystemExit(main())
