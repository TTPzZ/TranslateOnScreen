from __future__ import annotations

from screen_translator.controller.mode_controller import ModeController
from screen_translator.controller.state import ModeState
from screen_translator.domain.models import CapturedImage, ScreenRegion
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
        self.capture_calls = 0
        self.process_calls: list[CapturedImage] = []
        self.overlay_cleared = False

    def set_region(self, region: ScreenRegion) -> None:
        self.region = region

    def capture_frame(self) -> CapturedImage:
        self.capture_calls += 1
        return CapturedImage(region=self.region, image=[0, 255])

    def process_captured_frame(self, captured: CapturedImage) -> ReadingJobResult:
        self.process_calls.append(captured)
        return ReadingJobResult(items=[OverlayItem("Xin chao", captured.region)], metrics=None, had_text=True)

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
