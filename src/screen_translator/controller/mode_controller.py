from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from time import perf_counter
from typing import Protocol

from screen_translator.controller.state import ModeState
from screen_translator.domain.models import ScreenRegion
from screen_translator.instrumentation import RuntimeMetrics
from screen_translator.ui.server_process import LocalServerController
from screen_translator.ui.settings import ControlPanelSettings, SettingsStore

logger = logging.getLogger(__name__)


class RegionSelector(Protocol):
    def select_region(self) -> ScreenRegion | None:
        """Return a selected region or None when cancelled."""


class ReadingRunner(Protocol):
    def start(self, region: ScreenRegion) -> None:
        """Start Reading Mode for a region."""

    def stop(self) -> None:
        """Stop Reading Mode."""

    def clear_overlay(self) -> None:
        """Clear Reading Mode overlay items."""


class GamingPipeline(Protocol):
    def run_once(self, region: ScreenRegion | None = None) -> bool:
        """Run one Gaming Mode translation for a selected region."""

    def clear_overlay(self) -> None:
        """Clear Gaming Mode overlay items."""


class RuntimeSettingsApplier(Protocol):
    def __call__(self, settings: ControlPanelSettings) -> list[str]:
        """Apply safe runtime settings and return user-visible messages."""


class ModeController:
    """Owns mode state and routes UI actions to pipelines/runners."""

    def __init__(
        self,
        *,
        selector: RegionSelector,
        reading_runner: ReadingRunner | None,
        gaming_hotkey_status: str,
        debug_mode: bool,
        gaming_pipeline: GamingPipeline | None = None,
        runtime_metrics: RuntimeMetrics | None = None,
        clock: Callable[[], float] = perf_counter,
        gaming_dismiss_hotkey_status: str = "unregistered",
        gaming_dismiss_hotkey_label: str = "Esc",
        settings: ControlPanelSettings | None = None,
        settings_store: SettingsStore | None = None,
        server_controller: LocalServerController | None = None,
        runtime_settings_applier: RuntimeSettingsApplier | None = None,
    ) -> None:
        self._selector = selector
        self._reading_runner = reading_runner
        self._gaming_pipeline = gaming_pipeline
        self._runtime_metrics = runtime_metrics
        self._clock = clock
        self._settings = settings or ControlPanelSettings.defaults()
        self._settings_store = settings_store
        self._server_controller = server_controller
        self._runtime_settings_applier = runtime_settings_applier
        self.gaming_hotkey_status = gaming_hotkey_status
        self.gaming_dismiss_hotkey_status = gaming_dismiss_hotkey_status
        self.gaming_dismiss_hotkey_label = gaming_dismiss_hotkey_label or self._settings.gaming_dismiss_hotkey
        self.debug_mode = debug_mode
        self.state = ModeState.IDLE
        self.current_region: ScreenRegion | None = None
        self.gaming_enabled = True
        self.last_hotkey_event_time = "never"
        self.last_error: str | None = None
        self.status_message = "Ready"

    def select_region(self) -> bool:
        self.state = ModeState.SELECTING_REGION
        try:
            region = self._selector.select_region()
        except Exception as exc:
            self._set_error(exc)
            return False

        if region is None:
            self.state = ModeState.IDLE
            return False
        self.current_region = region
        self.state = ModeState.GAMING_READY
        self.last_error = None
        self.status_message = "Ready"
        return True

    def clear_region(self) -> bool:
        if self.state == ModeState.READING_RUNNING:
            self.stop_reading_mode()
        self.current_region = None
        self.state = ModeState.IDLE
        self.status_message = "Ready"
        return True

    def start_reading_mode(self) -> bool:
        if self.current_region is None and not self.select_region():
            return False
        if self.current_region is None:
            self._set_error("Invalid selected region")
            return False
        if self._reading_runner is None:
            self._set_error("Reading Mode runner is unavailable")
            return False

        try:
            self._reading_runner.start(self.current_region)
        except Exception as exc:
            self._set_error(exc)
            return False

        self.state = ModeState.READING_RUNNING
        self.last_error = None
        self.status_message = "Running Reading Mode"
        return True

    def stop_reading_mode(self) -> None:
        if self._reading_runner is not None:
            try:
                self._reading_runner.stop()
                self._reading_runner.clear_overlay()
                logger.info("Reading overlay cleared by Stop Reading Mode")
            except Exception as exc:
                self._set_error(exc)
                return
        self.state = ModeState.GAMING_READY if self.current_region is not None else ModeState.IDLE
        self.status_message = "Ready"

    def set_gaming_enabled(self, enabled: bool) -> None:
        self.gaming_enabled = enabled

    def run_gaming_translation_once(self) -> bool:
        if self.current_region is None:
            self._set_error("Select a region before running Gaming Mode")
            return False
        if self._gaming_pipeline is None:
            self._set_error("Gaming Mode pipeline is unavailable")
            return False

        if self.state == ModeState.READING_RUNNING:
            if self._reading_runner is not None:
                try:
                    self._reading_runner.stop()
                    logger.info("Reading Mode stopped because Gaming Mode started")
                    self._reading_runner.clear_overlay()
                    logger.info("Reading overlay cleared before Gaming Mode")
                except Exception as exc:
                    self._set_error(exc)
                    return False
            if self._runtime_metrics is not None:
                self._runtime_metrics.record_reading_auto_stopped_by_gaming()
            self.state = ModeState.GAMING_READY

        try:
            result = self._gaming_pipeline.run_once(self.current_region)
        except Exception as exc:
            self._set_error(exc)
            return False

        if result:
            self.state = ModeState.GAMING_READY
            self.last_error = None
            self.status_message = "Ready"
        return bool(result)

    def clear_gaming_overlay(self) -> bool:
        if self._gaming_pipeline is None:
            self._set_error("Gaming Mode pipeline is unavailable")
            return False
        try:
            self._gaming_pipeline.clear_overlay()
        except Exception as exc:
            self._set_error(exc)
            return False
        self.last_error = None
        return True

    def handle_hotkey_pressed(self) -> bool:
        response_start = self._clock()
        self.last_hotkey_event_time = datetime.now().isoformat(timespec="seconds")
        logger.info("hotkey pressed last_hotkey_event_time=%s", self.last_hotkey_event_time)
        result = self.run_gaming_translation_once()
        total_response_ms = (self._clock() - response_start) * 1000
        if result:
            logger.info(
                "hotkey response overlay_shown_timestamp=%s total_response_ms=%.2f",
                datetime.now().isoformat(timespec="milliseconds"),
                total_response_ms,
            )
        else:
            logger.info(
                "hotkey response completed_timestamp=%s total_response_ms=%.2f success=false",
                datetime.now().isoformat(timespec="milliseconds"),
                total_response_ms,
            )
        return result

    def settings(self) -> ControlPanelSettings:
        return self._settings

    def save_settings(self, settings: ControlPanelSettings) -> bool:
        restart_required = (
            settings.gaming_hotkey != self._settings.gaming_hotkey
            or settings.gaming_dismiss_hotkey != self._settings.gaming_dismiss_hotkey
        )
        try:
            if self._settings_store is not None:
                self._settings_store.save(settings)
            self._settings = settings
            self.debug_mode = settings.debug_mode
            self.gaming_dismiss_hotkey_label = settings.gaming_dismiss_hotkey
            if self._runtime_settings_applier is not None:
                messages = self._runtime_settings_applier(settings)
            else:
                messages = []
        except Exception as exc:
            self._set_error(exc)
            return False

        if restart_required:
            self.status_message = "Restart required for this setting."
        elif messages:
            self.status_message = " ".join(messages)
        else:
            self.status_message = "Settings saved"
        self.last_error = None
        return True

    def reset_settings(self) -> bool:
        try:
            settings = (
                self._settings_store.reset()
                if self._settings_store is not None
                else ControlPanelSettings.defaults()
            )
        except Exception as exc:
            self._set_error(exc)
            return False
        result = self.save_settings(settings)
        if result and self.status_message == "Settings saved":
            self.status_message = "Default settings restored"
        return result

    def start_local_server(self) -> bool:
        if self._server_controller is None:
            self._set_error("Local server helper is unavailable")
            return False
        try:
            self._server_controller.start(
                provider=self._settings.translation_provider,
                server_url=self._settings.translation_server_url,
            )
        except Exception as exc:
            self._set_error(exc)
            return False
        self.status_message = "Server running"
        self.last_error = None
        return True

    def stop_local_server(self) -> bool:
        if self._server_controller is None:
            self._set_error("Local server helper is unavailable")
            return False
        try:
            self._server_controller.stop()
        except Exception as exc:
            self._set_error(exc)
            return False
        self.status_message = "Server stopped"
        self.last_error = None
        return True

    def server_status(self) -> str:
        if self._server_controller is None:
            return "unavailable"
        return self._server_controller.status()

    def handle_gaming_dismiss_hotkey_pressed(self) -> bool:
        result = self.clear_gaming_overlay()
        if result:
            logger.info("gaming overlay dismissed by hotkey")
        return result

    def diagnostic_lines(self) -> list[str]:
        if self._runtime_metrics is None:
            return []
        return self._runtime_metrics.diagnostic_lines()

    def report_hotkey_registered(self) -> None:
        self.gaming_hotkey_status = "registered"
        logger.info("hotkey registration success")

    def report_hotkey_failed(self, error: Exception | str) -> None:
        self.gaming_hotkey_status = "failed"
        self._set_error(error)

    def report_gaming_dismiss_hotkey_registered(self) -> None:
        self.gaming_dismiss_hotkey_status = "registered"
        logger.info("gaming dismiss hotkey registered key=%s", self.gaming_dismiss_hotkey_label)

    def report_gaming_dismiss_hotkey_failed(self, error: Exception | str) -> None:
        self.gaming_dismiss_hotkey_status = "failed"
        self._set_error(error)

    def report_error(self, error: Exception | str) -> None:
        self._set_error(error)

    def _set_error(self, error: Exception | str) -> None:
        self.last_error = str(error)
        self.state = ModeState.ERROR
        self.status_message = "Error"
        logger.error("%s", self.last_error)
