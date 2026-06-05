from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import logging
from typing import Callable, Protocol, TypeVar

from screen_translator.domain.models import ScreenRegion

logger = logging.getLogger(__name__)
T = TypeVar("T")


class CaptureOverlay(Protocol):
    def hide_for_capture(self) -> None:
        """Temporarily hide this overlay before screen capture."""

    def restore_after_capture(self) -> None:
        """Restore this overlay after screen capture."""


class UiDispatcher(Protocol):
    def run_sync(
        self,
        action: Callable[[], None],
        *,
        timeout_ms: int | None = None,
    ) -> None:
        """Run action on the UI thread before returning."""


class OverlayCaptureGuard:
    """Temporarily hide app-owned overlays so OCR captures the real screen."""

    def __init__(
        self,
        overlays: Sequence[object],
        *,
        ui_dispatcher: UiDispatcher | None = None,
        timeout_ms: int | None = 1000,
    ) -> None:
        self._overlays = tuple(overlays)
        self._ui_dispatcher = ui_dispatcher
        self._timeout_ms = timeout_ms

    @contextmanager
    def hidden_for_capture(
        self,
        *,
        capture_regions: Sequence[ScreenRegion] | None = None,
    ) -> Iterator[None]:
        hidden: list[object] = []
        regions = tuple(capture_regions or ())
        hidden_count = 0
        skipped_count = 0
        logger.debug(
            "capture guard enter capture_without_overlays=true overlay_count=%d capture_regions=%d",
            len(self._overlays),
            len(regions),
        )
        try:
            for overlay in self._overlays:
                hide_regions = getattr(overlay, "hide_for_capture_regions", None)
                if regions and callable(hide_regions):
                    result = self._run_overlay_callback(lambda: hide_regions(regions))
                    overlay_hidden_count, overlay_skipped_count = _capture_hide_counts(result)
                    hidden_count += overlay_hidden_count
                    skipped_count += overlay_skipped_count
                    if overlay_hidden_count > 0:
                        hidden.append(overlay)
                    continue

                hide = getattr(overlay, "hide_for_capture", None)
                if not callable(hide):
                    skipped_count += 1
                    continue
                self._run_overlay_callback(hide)
                hidden.append(overlay)
                hidden_count += 1
            logger.debug(
                "overlays hidden before capture capture_without_overlays=true "
                "overlay_count=%d hidden_overlay_count=%d skipped_overlay_count=%d "
                "capture_regions=%d",
                len(hidden),
                hidden_count,
                skipped_count,
                len(regions),
            )
            yield
        finally:
            for overlay in reversed(hidden):
                restore = getattr(overlay, "restore_after_capture", None)
                if callable(restore):
                    try:
                        self._run_overlay_callback(restore)
                    except Exception:
                        logger.exception(
                            "overlay restore failed capture_without_overlays=true overlay=%r",
                            overlay,
                        )
            logger.debug(
                "overlays restored after capture capture_without_overlays=true "
                "overlay_count=%d hidden_overlay_count=%d skipped_overlay_count=%d "
                "capture_regions=%d",
                len(hidden),
                hidden_count,
                skipped_count,
                len(regions),
            )

    def _run_overlay_callback(self, callback: Callable[[], T]) -> T:
        if self._ui_dispatcher is None:
            return callback()
        result: dict[str, T] = {}

        def action() -> None:
            result["value"] = callback()

        try:
            self._ui_dispatcher.run_sync(action, timeout_ms=self._timeout_ms)
        except TimeoutError:
            logger.exception(
                "overlay UI dispatch timed out capture_without_overlays=true timeout_ms=%s",
                self._timeout_ms,
            )
            raise
        return result["value"]


def _capture_hide_counts(result: object) -> tuple[int, int]:
    if isinstance(result, tuple) and len(result) >= 2:
        return (int(result[0]), int(result[1]))
    if isinstance(result, int):
        return (result, 0)
    return (0, 0)


class NoopOverlayCaptureGuard:
    @contextmanager
    def hidden_for_capture(
        self,
        *,
        capture_regions: Sequence[ScreenRegion] | None = None,
    ) -> Iterator[None]:
        del capture_regions
        yield
