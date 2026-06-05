from __future__ import annotations

from screen_translator.controller.mode_controller import ModeController
from screen_translator.controller.state import ModeState
from screen_translator.domain.models import (
    CapturedImage,
    OverlayStyleMode,
    ScreenRegion,
    TranslationZone,
    TranslationZoneMode,
)
from screen_translator.hotkeys.windows import DEFAULT_HOTKEY, WM_HOTKEY, WindowsGlobalHotkey
from screen_translator.instrumentation import RuntimeMetrics
from screen_translator.overlay.layout import OverlayItem
from screen_translator.reading.async_pipeline import AsyncReadingModeRunner, ReadingJobResult
from screen_translator.ui.settings import ControlPanelSettings


class FakeWorker:
    def __init__(self) -> None:
        self.running = False
        self.cancel_calls = 0
        self.submitted: list[tuple[int, object]] = []
        self.last_on_success = None
        self.last_on_error = None

    def submit(self, job_id, task, on_success, on_error) -> bool:
        if self.running:
            return False
        self.running = True
        self.submitted.append((job_id, task))
        self.last_on_success = on_success
        self.last_on_error = on_error
        return True

    def cancel(self) -> None:
        self.cancel_calls += 1
        self.running = False


class FakeTimer:
    def __init__(self) -> None:
        self.started: list[int] = []
        self.stop_calls = 0

    def start(self, interval_ms: int) -> None:
        self.started.append(interval_ms)

    def stop(self) -> None:
        self.stop_calls += 1


class FakeUser32:
    def RegisterHotKey(self, hwnd: int, hotkey_id: int, modifiers: int, key_code: int) -> int:
        del hwnd, hotkey_id, modifiers, key_code
        return 1

    def UnregisterHotKey(self, hwnd: int, hotkey_id: int) -> int:
        del hwnd, hotkey_id
        return 1


class FakeReadingPipeline:
    def __init__(self) -> None:
        self.region = ScreenRegion(10, 20, 100, 40)
        self.zones = ()
        self.capture_calls = 0
        self.process_calls: list[CapturedImage] = []
        self.overlay_cleared = False

    def set_region(self, region: ScreenRegion) -> None:
        self.region = region

    def set_zones(self, zones) -> None:
        self.zones = tuple(zones)

    def capture_frame(self) -> CapturedImage:
        self.capture_calls += 1
        return CapturedImage(region=self.region, image=[0, 255])

    def process_captured_frame(self, captured: CapturedImage) -> ReadingJobResult:
        self.process_calls.append(captured)
        return ReadingJobResult(items=[OverlayItem("Xin chao", captured.region)], metrics=None, had_text=True)

    def process_next_frame(self) -> ReadingJobResult:
        return self.process_captured_frame(self.capture_frame())

    def apply_result(self, result: ReadingJobResult) -> None:
        del result

    def handle_error(self, error: Exception) -> None:
        del error

    def clear_overlay(self) -> None:
        self.overlay_cleared = True


def test_async_reading_runner_skips_tick_while_worker_is_busy() -> None:
    worker = FakeWorker()
    timer = FakeTimer()
    metrics = RuntimeMetrics()
    runner = AsyncReadingModeRunner(
        pipeline=FakeReadingPipeline(),
        worker=worker,
        timer=timer,
        metrics=metrics,
        interval_ms=500,
    )

    runner.start(ScreenRegion(10, 20, 100, 40))
    assert runner.on_interval() is True
    assert runner.on_interval() is False

    assert metrics.skipped_busy_ticks == 1
    assert len(worker.submitted) == 1


def test_async_reading_runner_defers_capture_until_worker_executes_task() -> None:
    worker = FakeWorker()
    pipeline = FakeReadingPipeline()
    runner = AsyncReadingModeRunner(
        pipeline=pipeline,
        worker=worker,
        timer=FakeTimer(),
        metrics=RuntimeMetrics(),
        interval_ms=500,
    )

    runner.start(ScreenRegion(10, 20, 100, 40))
    runner.on_interval()

    assert pipeline.capture_calls == 0
    result = worker.submitted[0][1]()
    assert pipeline.capture_calls == 1
    assert result.items[0].text == "Xin chao"


def test_async_reading_runner_can_start_with_zones() -> None:
    worker = FakeWorker()
    timer = FakeTimer()
    metrics = RuntimeMetrics()
    pipeline = FakeReadingPipeline()
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 100, 40),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    runner = AsyncReadingModeRunner(
        pipeline=pipeline,
        worker=worker,
        timer=timer,
        metrics=metrics,
        interval_ms=500,
    )

    runner.start_zones((zone,))
    runner.on_interval()
    result = worker.submitted[0][1]()

    assert pipeline.zones == (zone,)
    assert timer.started == [500]
    assert result.items[0].text == "Xin chao"


def test_async_reading_runner_ignores_stale_result_after_stop() -> None:
    worker = FakeWorker()
    timer = FakeTimer()
    metrics = RuntimeMetrics()
    pipeline = FakeReadingPipeline()
    applied: list[ReadingJobResult] = []
    pipeline.apply_result = applied.append
    runner = AsyncReadingModeRunner(
        pipeline=pipeline,
        worker=worker,
        timer=timer,
        metrics=metrics,
        interval_ms=500,
    )
    runner.start(ScreenRegion(10, 20, 100, 40))
    runner.on_interval()

    runner.stop()
    worker.last_on_success(1, ReadingJobResult(items=[], metrics=None, had_text=False))

    assert applied == []
    assert metrics.stale_results_ignored == 1
    assert timer.stop_calls == 1
    assert worker.cancel_calls == 1


def test_async_reading_runner_reports_errors_without_crashing() -> None:
    worker = FakeWorker()
    metrics = RuntimeMetrics()
    pipeline = FakeReadingPipeline()
    errors: list[Exception] = []
    pipeline.handle_error = errors.append
    runner = AsyncReadingModeRunner(
        pipeline=pipeline,
        worker=worker,
        timer=FakeTimer(),
        metrics=metrics,
        interval_ms=500,
    )
    runner.start(ScreenRegion(10, 20, 100, 40))
    runner.on_interval()

    worker.last_on_error(1, RuntimeError("OCR engine unavailable"))

    assert [str(error) for error in errors] == ["OCR engine unavailable"]
    assert metrics.last_error == "OCR engine unavailable"


def test_async_reading_runner_routes_ui_apply_errors_to_pipeline_handler() -> None:
    worker = FakeWorker()
    metrics = RuntimeMetrics()
    pipeline = FakeReadingPipeline()
    errors: list[Exception] = []

    def fail_apply(result: ReadingJobResult) -> None:
        del result
        raise RuntimeError("Overlay render failure")

    pipeline.apply_result = fail_apply
    pipeline.handle_error = errors.append
    runner = AsyncReadingModeRunner(
        pipeline=pipeline,
        worker=worker,
        timer=FakeTimer(),
        metrics=metrics,
        interval_ms=500,
    )
    runner.start(ScreenRegion(10, 20, 100, 40))
    runner.on_interval()

    worker.last_on_success(1, ReadingJobResult(items=[], metrics=None, had_text=False))

    assert [str(error) for error in errors] == ["Overlay render failure"]
    assert metrics.last_error == "Overlay render failure"


def test_async_reading_runner_can_clear_pipeline_overlay() -> None:
    pipeline = FakeReadingPipeline()
    runner = AsyncReadingModeRunner(
        pipeline=pipeline,
        worker=FakeWorker(),
        timer=FakeTimer(),
        metrics=RuntimeMetrics(),
        interval_ms=500,
    )

    runner.clear_overlay()

    assert pipeline.overlay_cleared is True


def test_mode_controller_state_transitions_for_reading_start_stop() -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            return ScreenRegion(10, 20, 100, 40)

    class Runner:
        def __init__(self) -> None:
            self.started: list[ScreenRegion] = []
            self.stop_calls = 0
            self.clear_overlay_calls = 0

        def start(self, region: ScreenRegion) -> None:
            self.started.append(region)

        def stop(self) -> None:
            self.stop_calls += 1

        def clear_overlay(self) -> None:
            self.clear_overlay_calls += 1

    runner = Runner()
    controller = ModeController(
        selector=Selector(),
        reading_runner=runner,
        gaming_hotkey_status="registered",
        debug_mode=True,
    )

    assert controller.select_region() is True
    assert controller.state == ModeState.GAMING_READY
    assert controller.start_reading_mode() is True
    assert controller.state == ModeState.READING_RUNNING
    controller.stop_reading_mode()

    assert controller.state == ModeState.GAMING_READY
    assert runner.started == [ScreenRegion(10, 20, 100, 40)]
    assert runner.stop_calls == 1
    assert runner.clear_overlay_calls == 1


def test_mode_controller_start_reading_uses_zones_before_selected_region() -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            raise AssertionError("selector should not run when zones exist")

    class Runner:
        def __init__(self) -> None:
            self.started_regions: list[ScreenRegion] = []
            self.started_zones = []
            self.stop_calls = 0
            self.clear_overlay_calls = 0

        def start(self, region: ScreenRegion) -> None:
            self.started_regions.append(region)

        def start_zones(self, zones) -> None:
            self.started_zones.append(tuple(zones))

        def stop(self) -> None:
            self.stop_calls += 1

        def clear_overlay(self) -> None:
            self.clear_overlay_calls += 1

    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 100, 40),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    runner = Runner()
    controller = ModeController(
        selector=Selector(),
        reading_runner=runner,
        gaming_hotkey_status="registered",
        debug_mode=False,
        settings=ControlPanelSettings.defaults().with_updates(zones=(zone,)),
    )

    assert controller.start_reading_mode() is True

    assert runner.started_zones == [(zone,)]
    assert runner.started_regions == []
    assert controller.state == ModeState.READING_RUNNING


def test_mode_controller_stop_reading_clears_overlay_and_logs(caplog) -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            return ScreenRegion(10, 20, 100, 40)

    class Runner:
        def __init__(self) -> None:
            self.stop_calls = 0
            self.clear_overlay_calls = 0

        def start(self, region: ScreenRegion) -> None:
            del region

        def stop(self) -> None:
            self.stop_calls += 1

        def clear_overlay(self) -> None:
            self.clear_overlay_calls += 1

    runner = Runner()
    controller = ModeController(
        selector=Selector(),
        reading_runner=runner,
        gaming_hotkey_status="registered",
        debug_mode=True,
    )
    controller.current_region = ScreenRegion(10, 20, 100, 40)
    controller.state = ModeState.READING_RUNNING

    with caplog.at_level("INFO", logger="screen_translator.controller.mode_controller"):
        controller.stop_reading_mode()

    assert runner.stop_calls == 1
    assert runner.clear_overlay_calls == 1
    assert controller.state == ModeState.GAMING_READY
    assert "Reading overlay cleared by Stop Reading Mode" in caplog.text


def test_gaming_overlay_clear_hotkey_clears_only_gaming_overlay(caplog) -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            return ScreenRegion(10, 20, 100, 40)

    class Runner:
        def __init__(self) -> None:
            self.clear_overlay_calls = 0

        def start(self, region: ScreenRegion) -> None:
            del region

        def stop(self) -> None:
            return None

        def clear_overlay(self) -> None:
            self.clear_overlay_calls += 1

    class GamingPipeline:
        def __init__(self) -> None:
            self.clear_overlay_calls = 0

        def run_once(self, region: ScreenRegion | None = None) -> bool:
            del region
            return True

        def clear_overlay(self) -> None:
            self.clear_overlay_calls += 1

    runner = Runner()
    gaming_pipeline = GamingPipeline()
    controller = ModeController(
        selector=Selector(),
        reading_runner=runner,
        gaming_pipeline=gaming_pipeline,
        gaming_hotkey_status="registered",
        debug_mode=True,
    )
    controller.current_region = ScreenRegion(10, 20, 100, 40)
    controller.state = ModeState.READING_RUNNING

    with caplog.at_level("INFO", logger="screen_translator.controller.mode_controller"):
        assert controller.handle_gaming_dismiss_hotkey_pressed() is True

    assert gaming_pipeline.clear_overlay_calls == 1
    assert runner.clear_overlay_calls == 0
    assert controller.state == ModeState.READING_RUNNING
    assert "gaming overlay dismissed by hotkey" in caplog.text


def test_mode_controller_stops_reading_and_clears_overlay_before_gaming(
    caplog,
) -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            return ScreenRegion(10, 20, 100, 40)

    class Runner:
        def __init__(self) -> None:
            self.stop_calls = 0
            self.clear_overlay_calls = 0

        def start(self, region: ScreenRegion) -> None:
            del region

        def stop(self) -> None:
            self.stop_calls += 1

        def clear_overlay(self) -> None:
            self.clear_overlay_calls += 1

    class GamingPipeline:
        def __init__(self) -> None:
            self.calls: list[ScreenRegion] = []

        def run_once(self, region: ScreenRegion | None = None) -> bool:
            assert region is not None
            self.calls.append(region)
            return True

    runner = Runner()
    gaming_pipeline = GamingPipeline()
    metrics = RuntimeMetrics()
    controller = ModeController(
        selector=Selector(),
        reading_runner=runner,
        gaming_pipeline=gaming_pipeline,
        runtime_metrics=metrics,
        gaming_hotkey_status="registered",
        debug_mode=True,
    )
    controller.current_region = ScreenRegion(10, 20, 100, 40)
    controller.state = ModeState.READING_RUNNING

    with caplog.at_level("INFO", logger="screen_translator.controller.mode_controller"):
        assert controller.run_gaming_translation_once() is True

    assert runner.stop_calls == 1
    assert runner.clear_overlay_calls == 1
    assert gaming_pipeline.calls == [ScreenRegion(10, 20, 100, 40)]
    assert controller.state == ModeState.GAMING_READY
    assert "Reading Mode stopped because Gaming Mode started" in caplog.text
    assert "Reading overlay cleared before Gaming Mode" in caplog.text
    assert "Reading Auto-Stopped By Gaming: yes" in metrics.diagnostic_lines()


def test_mode_controller_gaming_uses_gaming_and_both_zones_before_selected_region() -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            raise AssertionError("gaming zones should not require region selection")

    class GamingPipeline:
        def __init__(self) -> None:
            self.region_calls: list[ScreenRegion | None] = []
            self.zone_calls = []

        def run_once(self, region: ScreenRegion | None = None) -> bool:
            self.region_calls.append(region)
            return True

        def run_zones(self, zones) -> bool:
            self.zone_calls.append(tuple(zones))
            return True

    reading = TranslationZone(
        id="zone-reading",
        name="Reading",
        region=ScreenRegion(10, 20, 100, 40),
        mode=TranslationZoneMode.READING,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    both = TranslationZone(
        id="zone-both",
        name="Both",
        region=ScreenRegion(200, 20, 100, 40),
        mode=TranslationZoneMode.BOTH,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    gaming = TranslationZone(
        id="zone-gaming",
        name="Gaming",
        region=ScreenRegion(400, 20, 100, 40),
        mode=TranslationZoneMode.GAMING,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    pipeline = GamingPipeline()
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_pipeline=pipeline,
        gaming_hotkey_status="registered",
        debug_mode=True,
        settings=ControlPanelSettings.defaults().with_updates(zones=(reading, both, gaming)),
    )

    assert controller.run_gaming_translation_once() is True

    assert pipeline.zone_calls == [(gaming, both)]
    assert pipeline.region_calls == []
    assert controller.last_error is None


def test_mode_controller_gaming_falls_back_to_selected_region_without_gaming_zones() -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            raise AssertionError("stored selected region should be used")

    class GamingPipeline:
        def __init__(self) -> None:
            self.region_calls: list[ScreenRegion | None] = []
            self.zone_calls = []

        def run_once(self, region: ScreenRegion | None = None) -> bool:
            self.region_calls.append(region)
            return True

        def run_zones(self, zones) -> bool:
            self.zone_calls.append(tuple(zones))
            return True

    reading = TranslationZone(
        id="zone-reading",
        name="Reading",
        region=ScreenRegion(10, 20, 100, 40),
        mode=TranslationZoneMode.READING,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    region = ScreenRegion(50, 60, 200, 80)
    pipeline = GamingPipeline()
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_pipeline=pipeline,
        gaming_hotkey_status="registered",
        debug_mode=True,
        settings=ControlPanelSettings.defaults().with_updates(zones=(reading,)),
    )
    controller.current_region = region

    assert controller.run_gaming_translation_once() is True

    assert pipeline.zone_calls == []
    assert pipeline.region_calls == [region]


def test_mode_controller_routes_user_visible_errors_without_crashing() -> None:
    class FailingSelector:
        def select_region(self) -> ScreenRegion:
            raise RuntimeError("Invalid selected region")

    controller = ModeController(
        selector=FailingSelector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
    )

    assert controller.select_region() is False
    assert controller.state == ModeState.ERROR
    assert controller.last_error == "Invalid selected region"


def test_hotkey_callback_runs_gaming_pipeline_for_selected_region() -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            raise AssertionError("hotkey should use the stored selected region")

    class GamingPipeline:
        def __init__(self) -> None:
            self.calls: list[ScreenRegion] = []

        def run_once(self, region: ScreenRegion | None = None) -> bool:
            assert region is not None
            self.calls.append(region)
            return True

    region = ScreenRegion(10, 20, 100, 40)
    gaming_pipeline = GamingPipeline()
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_pipeline=gaming_pipeline,
        gaming_hotkey_status="registered",
        debug_mode=True,
    )
    controller.current_region = region
    hotkey = WindowsGlobalHotkey(callback=controller.handle_hotkey_pressed, user32=FakeUser32())

    assert hotkey.dispatch_message(WM_HOTKEY, DEFAULT_HOTKEY.identifier) is True

    assert gaming_pipeline.calls == [region]
    assert controller.last_hotkey_event_time != "never"


def test_hotkey_without_selected_region_sets_visible_error(caplog) -> None:
    class Selector:
        def select_region(self) -> None:
            return None

    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_pipeline=None,
        gaming_hotkey_status="registered",
        debug_mode=True,
    )

    with caplog.at_level("ERROR", logger="screen_translator.controller.mode_controller"):
        assert controller.handle_hotkey_pressed() is False

    assert controller.last_error == "Select a region before running Gaming Mode"
    assert "Select a region before running Gaming Mode" in caplog.text
    assert controller.last_hotkey_event_time != "never"


def test_hotkey_logs_total_response_time(caplog) -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            raise AssertionError("hotkey should use the stored selected region")

    class GamingPipeline:
        def run_once(self, region: ScreenRegion | None = None) -> bool:
            assert region == ScreenRegion(10, 20, 100, 40)
            return True

    times = iter([1.0, 1.42])
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_pipeline=GamingPipeline(),
        gaming_hotkey_status="registered",
        debug_mode=True,
        clock=lambda: next(times),
    )
    controller.current_region = ScreenRegion(10, 20, 100, 40)

    with caplog.at_level("INFO", logger="screen_translator.controller.mode_controller"):
        assert controller.handle_hotkey_pressed() is True

    assert "hotkey response overlay_shown_timestamp=" in caplog.text
    assert "total_response_ms=420.00" in caplog.text


def test_mode_controller_save_settings_persists_and_applies_runtime_settings() -> None:
    class Selector:
        def select_region(self) -> None:
            return None

    class Store:
        def __init__(self) -> None:
            self.saved: list[ControlPanelSettings] = []

        def save(self, settings: ControlPanelSettings) -> None:
            self.saved.append(settings)

    applied: list[ControlPanelSettings] = []
    store = Store()
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        settings=ControlPanelSettings.defaults(),
        settings_store=store,
        runtime_settings_applier=lambda settings: applied.append(settings) or [],
    )
    settings = ControlPanelSettings.defaults().with_updates(
        translation_provider="googletrans",
        target_language="vi",
        debug_overlay_enabled=True,
    )

    assert controller.save_settings(settings) is True

    assert controller.settings() == settings
    assert store.saved == [settings]
    assert applied == [settings]
    assert controller.status_message == "Settings saved"


def test_mode_controller_save_settings_reports_restart_required_for_hotkey_change() -> None:
    class Selector:
        def select_region(self) -> None:
            return None

    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        settings=ControlPanelSettings.defaults(),
    )
    settings = ControlPanelSettings.defaults().with_updates(gaming_dismiss_hotkey="Q")

    assert controller.save_settings(settings) is True

    assert controller.status_message == "Restart required for this setting."


def test_mode_controller_add_zone_uses_selector_and_updates_settings() -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            return ScreenRegion(10, 20, 100, 40)

    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        zone_id_factory=lambda: "zone-1",
        timestamp_factory=lambda: "2026-06-04T12:00:00+00:00",
    )

    assert controller.add_zone() is True

    zone = controller.settings().zones[0]
    assert zone.id == "zone-1"
    assert zone.name == "Zone 1"
    assert zone.region == ScreenRegion(10, 20, 100, 40)
    assert zone.mode == TranslationZoneMode.READING
    assert zone.overlay_style == OverlayStyleMode.FLOATING_PANEL
    assert zone.enabled is True
    assert zone.visible is True
    assert zone.translation_visible is True
    assert zone.created_at == "2026-06-04T12:00:00+00:00"
    assert zone.updated_at == "2026-06-04T12:00:00+00:00"


def test_mode_controller_updates_and_deletes_zones_in_settings() -> None:
    class Selector:
        def select_region(self) -> None:
            return None

    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 100, 40),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        settings=ControlPanelSettings.defaults().with_updates(zones=(zone,)),
        timestamp_factory=lambda: "2026-06-04T12:10:00+00:00",
    )

    assert controller.rename_zone("zone-1", "Menu") is True
    assert controller.toggle_zone_visible("zone-1") is True
    assert controller.toggle_zone_enabled("zone-1") is True
    assert controller.set_zone_overlay_style("zone-1", "inline_replace") is True

    updated = controller.settings().zones[0]
    assert updated.name == "Menu"
    assert updated.visible is False
    assert updated.enabled is False
    assert updated.overlay_style == OverlayStyleMode.INLINE_REPLACE
    assert updated.updated_at == "2026-06-04T12:10:00+00:00"

    assert controller.delete_zone("zone-1") is True

    assert controller.settings().zones == ()


def test_mode_controller_overlay_toolbar_actions_update_and_persist_settings() -> None:
    class Selector:
        def __init__(self) -> None:
            self.region = ScreenRegion(50, 60, 200, 80)

        def select_region(self) -> ScreenRegion:
            return self.region

    class Store:
        def __init__(self) -> None:
            self.saved: list[ControlPanelSettings] = []

        def save(self, settings: ControlPanelSettings) -> None:
            self.saved.append(settings)

    class ZoneOverlay:
        def __init__(self) -> None:
            self.callbacks = None
            self.shown = []

        def set_callbacks(self, callbacks) -> None:
            self.callbacks = callbacks

        def show_zones(self, zones, *, edit_mode: bool = False, show_borders: bool = True) -> None:
            self.shown.append((tuple(zones), edit_mode, show_borders))

        def clear(self) -> None:
            return None

    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 100, 40),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    store = Store()
    overlay = ZoneOverlay()
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        settings=ControlPanelSettings.defaults().with_updates(zones=(zone,)),
        settings_store=store,
        zone_overlay=overlay,
        timestamp_factory=lambda: "2026-06-04T12:10:00+00:00",
    )

    assert overlay.callbacks is not None
    assert overlay.callbacks.on_move("zone-1") is True
    assert overlay.callbacks.on_style_change("zone-1", "inline_replace") is True
    assert overlay.callbacks.on_mode_change("zone-1", "both") is True

    updated = controller.settings().zones[0]
    assert updated.region == ScreenRegion(50, 60, 200, 80)
    assert updated.overlay_style == OverlayStyleMode.INLINE_REPLACE
    assert updated.mode == TranslationZoneMode.BOTH
    assert len(store.saved) == 3

    assert overlay.callbacks.on_delete("zone-1") is True
    assert controller.settings().zones == ()
    assert len(store.saved) == 4


def test_mode_controller_toggle_zone_borders_and_delete_all_zones() -> None:
    class Selector:
        def select_region(self) -> None:
            return None

    class ZoneOverlay:
        def __init__(self) -> None:
            self.shown = []
            self.clear_calls = 0

        def set_callbacks(self, callbacks) -> None:
            self.callbacks = callbacks

        def show_zones(self, zones, *, edit_mode: bool = False, show_borders: bool = True) -> None:
            self.shown.append((tuple(zones), edit_mode, show_borders))

        def clear(self) -> None:
            self.clear_calls += 1

    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 100, 40),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    overlay = ZoneOverlay()
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        settings=ControlPanelSettings.defaults().with_updates(zones=(zone,)),
        zone_overlay=overlay,
    )

    assert controller.toggle_zone_borders() is True
    assert controller.settings().show_zone_borders is False
    assert controller.edit_zones_enabled is False
    assert overlay.clear_calls == 1

    controller.edit_zones_enabled = False
    assert controller.toggle_zone_borders() is True
    assert controller.settings().show_zone_borders is True
    assert controller.edit_zones_enabled is False
    assert overlay.shown[-1][1] is False

    assert controller.delete_all_zones() is True
    assert controller.settings().zones == ()
    assert overlay.shown[-1][0] == ()


def test_mode_controller_diagnostics_include_zone_mode_counts() -> None:
    class Selector:
        def select_region(self) -> None:
            return None

    zones = (
        TranslationZone(
            id="zone-reading",
            name="Reading",
            region=ScreenRegion(10, 20, 100, 40),
            mode=TranslationZoneMode.READING,
            created_at="2026-06-04T12:00:00+00:00",
            updated_at="2026-06-04T12:00:00+00:00",
        ),
        TranslationZone(
            id="zone-gaming",
            name="Gaming",
            region=ScreenRegion(200, 20, 100, 40),
            mode=TranslationZoneMode.GAMING,
            created_at="2026-06-04T12:00:00+00:00",
            updated_at="2026-06-04T12:00:00+00:00",
        ),
        TranslationZone(
            id="zone-both",
            name="Both",
            region=ScreenRegion(400, 20, 100, 40),
            mode=TranslationZoneMode.BOTH,
            created_at="2026-06-04T12:00:00+00:00",
            updated_at="2026-06-04T12:00:00+00:00",
        ),
    )
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        settings=ControlPanelSettings.defaults().with_updates(zones=zones),
    )

    assert controller.diagnostic_lines()[-3:] == [
        "Reading Zones: 1",
        "Gaming Zones: 1",
        "Both Zones: 1",
    ]


def test_mode_controller_refreshes_zone_overlay_when_zone_visibility_changes() -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            return ScreenRegion(10, 20, 100, 40)

    class ZoneOverlay:
        def __init__(self) -> None:
            self.shown = []
            self.clear_calls = 0

        def show_zones(self, zones, *, edit_mode: bool = False, show_borders: bool = True) -> None:
            self.shown.append((tuple(zones), edit_mode, show_borders))

        def clear(self) -> None:
            self.clear_calls += 1

    overlay = ZoneOverlay()
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 100, 40),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        zone_overlay=overlay,
        settings=ControlPanelSettings.defaults().with_updates(zones=(zone,)),
    )

    assert controller.toggle_zone_visible("zone-1") is True

    assert overlay.shown[-1][0][0].visible is False
    assert overlay.shown[-1][1] is False
    assert overlay.shown[-1][2] is True
    assert overlay.clear_calls == 0


def test_mode_controller_show_and_hide_all_zones_updates_border_overlay() -> None:
    class Selector:
        def select_region(self) -> None:
            return None

    class ZoneOverlay:
        def __init__(self) -> None:
            self.shown = []

        def show_zones(self, zones, *, edit_mode: bool = False, show_borders: bool = True) -> None:
            self.shown.append((tuple(zones), edit_mode, show_borders))

        def clear(self) -> None:
            raise AssertionError("show/hide all should keep the border window available")

    zones = (
        TranslationZone(
            id="zone-1",
            name="Dialog",
            region=ScreenRegion(10, 20, 100, 40),
            visible=False,
            created_at="2026-06-04T12:00:00+00:00",
            updated_at="2026-06-04T12:00:00+00:00",
        ),
        TranslationZone(
            id="zone-2",
            name="Menu",
            region=ScreenRegion(200, 20, 100, 40),
            created_at="2026-06-04T12:00:00+00:00",
            updated_at="2026-06-04T12:00:00+00:00",
        ),
    )
    overlay = ZoneOverlay()
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        zone_overlay=overlay,
        settings=ControlPanelSettings.defaults().with_updates(zones=zones),
        timestamp_factory=lambda: "2026-06-04T12:10:00+00:00",
    )

    assert controller.show_all_zones() is True
    assert all(zone.visible for zone in controller.settings().zones)
    assert all(zone.visible for zone in overlay.shown[-1][0])

    assert controller.hide_all_zones() is True
    assert not any(zone.visible for zone in controller.settings().zones)
    assert not any(zone.visible for zone in overlay.shown[-1][0])


def test_mode_controller_can_clear_zone_border_overlay() -> None:
    class Selector:
        def select_region(self) -> None:
            return None

    class ZoneOverlay:
        def __init__(self) -> None:
            self.clear_calls = 0

        def show_zones(self, zones, *, edit_mode: bool = False, show_borders: bool = True) -> None:
            del zones, edit_mode, show_borders

        def clear(self) -> None:
            self.clear_calls += 1

    overlay = ZoneOverlay()
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        zone_overlay=overlay,
    )

    assert controller.clear_zone_borders() is True

    assert overlay.clear_calls == 1


def test_mode_controller_save_settings_hides_border_overlay_when_borders_disabled() -> None:
    class Selector:
        def select_region(self) -> None:
            return None

    class ZoneOverlay:
        def __init__(self) -> None:
            self.shown = []
            self.clear_calls = 0

        def show_zones(self, zones, *, edit_mode: bool = False, show_borders: bool = True) -> None:
            self.shown.append((tuple(zones), edit_mode, show_borders))

        def clear(self) -> None:
            self.clear_calls += 1

    overlay = ZoneOverlay()
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 100, 40),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        zone_overlay=overlay,
        settings=ControlPanelSettings.defaults().with_updates(zones=(zone,)),
    )

    assert controller.save_settings(
        controller.settings().with_updates(show_zone_borders=False)
    ) is True

    assert overlay.clear_calls == 1
    assert overlay.shown == []


def test_mode_controller_edit_zones_mode_refreshes_overlay_interactive() -> None:
    class Selector:
        def select_region(self) -> None:
            return None

    class ZoneOverlay:
        def __init__(self) -> None:
            self.shown = []

        def show_zones(self, zones, *, edit_mode: bool = False, show_borders: bool = True) -> None:
            self.shown.append((tuple(zones), edit_mode, show_borders))

        def clear(self) -> None:
            raise AssertionError("edit mode should refresh, not clear")

    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 100, 40),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    overlay = ZoneOverlay()
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        zone_overlay=overlay,
        settings=ControlPanelSettings.defaults().with_updates(zones=(zone,)),
    )

    assert controller.set_edit_zones_enabled(True) is True

    assert overlay.shown[-1][1] is True
    assert controller.status_message == "Edit Zones enabled"


def test_mode_controller_edit_zone_position_uses_region_selector() -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            return ScreenRegion(50, 60, 200, 80)

    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 100, 40),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        settings=ControlPanelSettings.defaults().with_updates(zones=(zone,)),
        timestamp_factory=lambda: "2026-06-04T12:10:00+00:00",
    )

    assert controller.edit_zone_position("zone-1") is True

    updated = controller.settings().zones[0]
    assert updated.region == ScreenRegion(50, 60, 200, 80)
    assert updated.updated_at == "2026-06-04T12:10:00+00:00"


def test_mode_controller_clear_all_translations_clears_reading_overlay() -> None:
    class Selector:
        def select_region(self) -> None:
            return None

    class Runner:
        def __init__(self) -> None:
            self.clear_overlay_calls = 0

        def clear_overlay(self) -> None:
            self.clear_overlay_calls += 1

    runner = Runner()
    controller = ModeController(
        selector=Selector(),
        reading_runner=runner,
        gaming_hotkey_status="registered",
        debug_mode=False,
    )

    assert controller.clear_all_translations() is True

    assert runner.clear_overlay_calls == 1
    assert controller.status_message == "Translations cleared"


def test_mode_controller_delete_zone_clears_reading_overlay_and_removes_border() -> None:
    class Selector:
        def select_region(self) -> None:
            return None

    class Runner:
        def __init__(self) -> None:
            self.clear_overlay_calls = 0

        def clear_overlay(self) -> None:
            self.clear_overlay_calls += 1

    class ZoneOverlay:
        def __init__(self) -> None:
            self.shown = []

        def show_zones(self, zones, *, edit_mode: bool = False, show_borders: bool = True) -> None:
            self.shown.append((tuple(zones), edit_mode, show_borders))

        def clear(self) -> None:
            raise AssertionError("delete should refresh with remaining zones")

    runner = Runner()
    overlay = ZoneOverlay()
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 100, 40),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    controller = ModeController(
        selector=Selector(),
        reading_runner=runner,
        gaming_hotkey_status="registered",
        debug_mode=False,
        zone_overlay=overlay,
        settings=ControlPanelSettings.defaults().with_updates(zones=(zone,)),
    )

    assert controller.delete_zone("zone-1") is True

    assert controller.settings().zones == ()
    assert overlay.shown[-1][0] == ()
    assert runner.clear_overlay_calls == 1
