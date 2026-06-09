from __future__ import annotations

from dataclasses import replace
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from screen_translator.controller.state import ModeState
from screen_translator.domain.models import (
    OcrEngineMode,
    OcrPreprocessMode,
    OverlayStyleMode,
    ScreenRegion,
    TranslationZone,
    TranslationZoneMode,
)
from screen_translator.instrumentation import RuntimeMetrics
from screen_translator.overlay.zones import ZoneOverlayCallbacks
from screen_translator.ui.server_process import LocalServerController
from screen_translator.ui.settings import ControlPanelSettings, SettingsStore

logger = logging.getLogger(__name__)


class RegionSelector(Protocol):
    def select_region(self) -> ScreenRegion | None:
        """Return a selected region or None when cancelled."""


class ReadingRunner(Protocol):
    def start(self, region: ScreenRegion) -> None:
        """Start Reading Mode for a region."""

    def start_zones(self, zones: object) -> None:
        """Start Reading Mode for persistent zones."""

    def stop(self) -> None:
        """Stop Reading Mode."""

    def clear_overlay(self) -> None:
        """Clear Reading Mode overlay items."""


class ZoneOverlay(Protocol):
    def set_callbacks(self, callbacks: ZoneOverlayCallbacks) -> None:
        """Set callbacks for toolbar actions."""

    def show_zones(
        self,
        zones: tuple[TranslationZone, ...],
        *,
        edit_mode: bool = False,
        show_borders: bool = True,
    ) -> None:
        """Show zone borders."""

    def clear(self) -> None:
        """Clear zone borders."""


class GamingPipeline(Protocol):
    def run_once(self, region: ScreenRegion | None = None) -> bool:
        """Run one Gaming Mode translation for a selected region."""

    def run_zones(self, zones: tuple[TranslationZone, ...]) -> bool:
        """Run one Gaming Mode translation pass for zones."""

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
        zone_id_factory: Callable[[], str] | None = None,
        timestamp_factory: Callable[[], str] | None = None,
        zone_overlay: ZoneOverlay | None = None,
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
        self._zone_id_factory = zone_id_factory or (lambda: uuid4().hex)
        self._timestamp_factory = timestamp_factory or _utc_timestamp
        self._zone_overlay = zone_overlay
        self.gaming_hotkey_status = gaming_hotkey_status
        self.gaming_dismiss_hotkey_status = gaming_dismiss_hotkey_status
        self.gaming_dismiss_hotkey_label = gaming_dismiss_hotkey_label or self._settings.gaming_dismiss_hotkey
        self.debug_mode = debug_mode
        self.edit_zones_enabled = False
        self.state = ModeState.IDLE
        self.current_region: ScreenRegion | None = None
        self.gaming_enabled = True
        self.last_hotkey_event_time = "never"
        self.last_error: str | None = None
        self.status_message = "Ready"
        self._install_zone_overlay_callbacks()

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

    def zones(self) -> tuple[TranslationZone, ...]:
        return self._settings.zones

    def add_zone(self) -> bool:
        try:
            region = self._selector.select_region()
        except Exception as exc:
            self._set_error(exc)
            return False
        if region is None:
            return False

        now = self._timestamp_factory()
        zone = TranslationZone(
            id=self._zone_id_factory(),
            name=f"Zone {len(self._settings.zones) + 1}",
            region=region,
            mode=TranslationZoneMode.READING,
            overlay_style=OverlayStyleMode.FLOATING_PANEL,
            created_at=now,
            updated_at=now,
        )
        return self._replace_settings(
            zones=(*self._settings.zones, zone),
            status="Zone added",
        )

    def delete_zone(self, zone_id: str) -> bool:
        zones = tuple(zone for zone in self._settings.zones if zone.id != zone_id)
        if len(zones) == len(self._settings.zones):
            self._set_error(f"Zone not found: {zone_id}")
            return False
        if not self._replace_settings(zones=zones, status="Zone deleted"):
            return False
        return self._clear_reading_overlay()

    def rename_zone(self, zone_id: str, name: str) -> bool:
        name = name.strip()
        if not name:
            self._set_error("Zone name must not be empty")
            return False
        return self._update_zone(
            zone_id,
            lambda zone: replace(zone, name=name, updated_at=self._timestamp_factory()),
            "Zone renamed",
        )

    def toggle_zone_visible(self, zone_id: str) -> bool:
        return self._update_zone(
            zone_id,
            lambda zone: replace(zone, visible=not zone.visible, updated_at=self._timestamp_factory()),
            "Zone visibility updated",
        )

    def toggle_zone_enabled(self, zone_id: str) -> bool:
        return self._update_zone(
            zone_id,
            lambda zone: replace(zone, enabled=not zone.enabled, updated_at=self._timestamp_factory()),
            "Zone translation updated",
        )

    def set_zone_overlay_style(self, zone_id: str, style: str) -> bool:
        try:
            overlay_style = OverlayStyleMode(style)
        except ValueError as exc:
            self._set_error(exc)
            return False
        return self._update_zone(
            zone_id,
            lambda zone: replace(
                zone,
                overlay_style=overlay_style,
                updated_at=self._timestamp_factory(),
            ),
            "Zone style updated",
        )

    def set_zone_mode(self, zone_id: str, mode: str) -> bool:
        try:
            zone_mode = TranslationZoneMode(mode)
        except ValueError as exc:
            self._set_error(exc)
            return False
        return self._update_zone(
            zone_id,
            lambda zone: replace(
                zone,
                mode=zone_mode,
                updated_at=self._timestamp_factory(),
            ),
            "Zone mode updated",
        )

    def set_zone_ocr_engine(self, zone_id: str, engine: str) -> bool:
        try:
            ocr_engine = OcrEngineMode(engine)
        except ValueError as exc:
            self._set_error(exc)
            return False
        return self._update_zone(
            zone_id,
            lambda zone: replace(
                zone,
                ocr_engine=ocr_engine,
                updated_at=self._timestamp_factory(),
            ),
            "Zone OCR engine updated",
        )

    def set_zone_ocr_preprocess(self, zone_id: str, preprocess: str) -> bool:
        try:
            ocr_preprocess = OcrPreprocessMode(preprocess)
        except ValueError as exc:
            self._set_error(exc)
            return False
        return self._update_zone(
            zone_id,
            lambda zone: replace(
                zone,
                ocr_preprocess=ocr_preprocess,
                updated_at=self._timestamp_factory(),
            ),
            "Zone OCR preprocess updated",
        )

    def set_zone_speed_profile(self, zone_id: str, profile: str) -> bool:
        normalized = profile.strip().lower()
        if normalized not in {"fast", "balanced", "accurate"}:
            self._set_error(f"Unsupported speed profile: {profile}")
            return False
        return self._update_zone(
            zone_id,
            lambda zone: replace(
                zone,
                speed_profile=normalized,
                updated_at=self._timestamp_factory(),
            ),
            "Zone speed profile updated",
        )

    def edit_zone_position(self, zone_id: str) -> bool:
        try:
            region = self._selector.select_region()
        except Exception as exc:
            self._set_error(exc)
            return False
        if region is None:
            return False
        return self._update_zone(
            zone_id,
            lambda zone: replace(
                zone,
                region=region,
                updated_at=self._timestamp_factory(),
            ),
            "Zone position updated",
        )

    def show_all_zones(self) -> bool:
        now = self._timestamp_factory()
        zones = tuple(replace(zone, visible=True, updated_at=now) for zone in self._settings.zones)
        return self._replace_settings(zones=zones, status="All zones shown")

    def hide_all_zones(self) -> bool:
        now = self._timestamp_factory()
        zones = tuple(replace(zone, visible=False, updated_at=now) for zone in self._settings.zones)
        return self._replace_settings(zones=zones, status="All zones hidden")

    def toggle_zone_borders(self) -> bool:
        if self._settings.show_zone_borders:
            return self._replace_settings(
                show_zone_borders=False,
                status="Zones hidden",
            )
        return self._replace_settings(
            show_zone_borders=True,
            status="Zones shown",
        )

    def delete_all_zones(self) -> bool:
        if not self._replace_settings(zones=(), status="All zones deleted"):
            return False
        return self._clear_reading_overlay()

    def clear_zone_borders(self) -> bool:
        if self._zone_overlay is not None:
            try:
                self._zone_overlay.clear()
            except Exception as exc:
                self._set_error(exc)
                return False
        self.status_message = "Zone borders cleared"
        self.last_error = None
        return True

    def set_edit_zones_enabled(self, enabled: bool) -> bool:
        self.edit_zones_enabled = enabled
        if not self._refresh_zone_overlay():
            return False
        self.status_message = f"Edit Zones {'enabled' if enabled else 'disabled'}"
        self.last_error = None
        return True

    def clear_all_translations(self) -> bool:
        if not self._clear_reading_overlay():
            return False
        self.status_message = "Translations cleared"
        self.last_error = None
        return True

    def start_reading_mode(self) -> bool:
        if self._reading_runner is None:
            self._set_error("Reading Mode runner is unavailable")
            return False

        reading_zones = self._reading_zones()
        if self._settings.zones:
            try:
                self._reading_runner.start_zones(reading_zones)
            except Exception as exc:
                self._set_error(exc)
                return False
            self.state = ModeState.READING_RUNNING
            self.last_error = None
            self.status_message = "Running Reading Mode"
            return True

        if self.current_region is None and not self.select_region():
            return False
        if self.current_region is None:
            self._set_error("Invalid selected region")
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
        gaming_zones = self._gaming_zones()
        if not gaming_zones and self.current_region is None:
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
            if gaming_zones:
                result = self._gaming_pipeline.run_zones(gaming_zones)
            else:
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

        if not self._refresh_zone_overlay():
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
        lines = [] if self._runtime_metrics is None else self._runtime_metrics.diagnostic_lines()
        lines.extend(
            [
                f"Reading Zones: {len(self._zones_for_mode(TranslationZoneMode.READING))}",
                f"Gaming Zones: {len(self._zones_for_mode(TranslationZoneMode.GAMING))}",
                f"Both Zones: {len(self._zones_for_mode(TranslationZoneMode.BOTH))}",
            ]
        )
        return lines

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

    def _replace_settings(self, *, status: str, **updates: object) -> bool:
        try:
            self._settings = self._settings.with_updates(**updates)
            if self._settings_store is not None:
                self._settings_store.save(self._settings)
            if self._runtime_settings_applier is not None:
                self._runtime_settings_applier(self._settings)
        except Exception as exc:
            self._set_error(exc)
            return False
        if not self._refresh_zone_overlay():
            return False
        self.status_message = status
        self.last_error = None
        return True

    def _update_zone(
        self,
        zone_id: str,
        update: Callable[[TranslationZone], TranslationZone],
        status: str,
    ) -> bool:
        changed = False
        zones: list[TranslationZone] = []
        for zone in self._settings.zones:
            if zone.id == zone_id:
                zones.append(update(zone))
                changed = True
            else:
                zones.append(zone)
        if not changed:
            self._set_error(f"Zone not found: {zone_id}")
            return False
        return self._replace_settings(zones=tuple(zones), status=status)

    def _refresh_zone_overlay(self) -> bool:
        if self._zone_overlay is None:
            return True
        try:
            if not self._settings.show_zone_borders:
                self._zone_overlay.clear()
                return True
            self._zone_overlay.show_zones(
                self._settings.zones,
                edit_mode=self.edit_zones_enabled,
                show_borders=self._settings.show_zone_borders,
            )
        except Exception as exc:
            self._set_error(exc)
            return False
        return True

    def _install_zone_overlay_callbacks(self) -> None:
        if self._zone_overlay is None:
            return
        set_callbacks = getattr(self._zone_overlay, "set_callbacks", None)
        if not callable(set_callbacks):
            return
        set_callbacks(
            ZoneOverlayCallbacks(
                on_delete=self.delete_zone,
                on_move=self.edit_zone_position,
                on_style_change=self.set_zone_overlay_style,
                on_mode_change=self.set_zone_mode,
                on_ocr_engine_change=self.set_zone_ocr_engine,
                on_ocr_preprocess_change=self.set_zone_ocr_preprocess,
                on_speed_profile_change=self.set_zone_speed_profile,
            )
        )

    def _reading_zones(self) -> tuple[TranslationZone, ...]:
        return tuple(
            zone
            for zone in self._settings.zones
            if zone.enabled and zone.mode in {TranslationZoneMode.READING, TranslationZoneMode.BOTH}
        )

    def _gaming_zones(self) -> tuple[TranslationZone, ...]:
        gaming = self._zones_for_mode(TranslationZoneMode.GAMING)
        both = self._zones_for_mode(TranslationZoneMode.BOTH)
        return (*gaming, *both)

    def _zones_for_mode(self, mode: TranslationZoneMode) -> tuple[TranslationZone, ...]:
        return tuple(
            zone
            for zone in self._settings.zones
            if zone.enabled and zone.mode == mode
        )

    def _clear_reading_overlay(self) -> bool:
        if self._reading_runner is None:
            return True
        try:
            self._reading_runner.clear_overlay()
        except Exception as exc:
            self._set_error(exc)
            return False
        return True

    def _set_error(self, error: Exception | str) -> None:
        self.last_error = str(error)
        self.state = ModeState.ERROR
        self.status_message = "Error"
        logger.error("%s", self.last_error)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
