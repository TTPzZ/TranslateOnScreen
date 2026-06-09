from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Protocol

from screen_translator.config import AppConfig
from screen_translator.domain.models import OcrEngineMode
from screen_translator.ocr.base import OcrProvider
from screen_translator.ocr.windows_provider import WindowsOcrProvider

logger = logging.getLogger(__name__)


class WindowsProviderFactory(Protocol):
    def __call__(self) -> OcrProvider | None:
        """Return a Windows OCR provider or None when unavailable."""


@dataclass(frozen=True, slots=True)
class SelectedOcrProvider:
    provider: OcrProvider
    engine: str
    requested_engine: str
    speed_profile: str
    fallback_reason: str | None = None


class OcrProviderRegistry:
    """Select OCR providers without coupling pipelines to provider construction."""

    def __init__(
        self,
        *,
        paddle_provider: OcrProvider,
        windows_provider_factory: WindowsProviderFactory | None = None,
    ) -> None:
        self._paddle_provider = paddle_provider
        self._windows_provider_factory = windows_provider_factory or WindowsOcrProvider.create_if_available
        self._windows_provider: OcrProvider | None | bool = False

    def select(
        self,
        *,
        requested_engine: str | OcrEngineMode | None,
        speed_profile: str,
        config: AppConfig,
    ) -> SelectedOcrProvider:
        del config
        requested = _normalize_engine(requested_engine)
        profile = _normalize_speed_profile(speed_profile)
        preferred = _preferred_engine(requested, profile)
        if preferred == OcrEngineMode.WINDOWS:
            windows_provider = self._windows()
            if windows_provider is not None:
                logger.info(
                    "ocr_engine_selected requested_engine=%s selected_ocr_engine=windows "
                    "speed_profile=%s fallback_reason=None",
                    requested.value,
                    profile,
                )
                return SelectedOcrProvider(
                    provider=windows_provider,
                    engine=OcrEngineMode.WINDOWS.value,
                    requested_engine=requested.value,
                    speed_profile=profile,
                )
            logger.info(
                "ocr_engine_selected requested_engine=%s selected_ocr_engine=paddle "
                "speed_profile=%s fallback_reason=windows_ocr_unavailable",
                requested.value,
                profile,
            )
            return SelectedOcrProvider(
                provider=self._paddle_provider,
                engine=OcrEngineMode.PADDLE.value,
                requested_engine=requested.value,
                speed_profile=profile,
                fallback_reason="windows_ocr_unavailable",
            )

        logger.info(
            "ocr_engine_selected requested_engine=%s selected_ocr_engine=paddle "
            "speed_profile=%s fallback_reason=None",
            requested.value,
            profile,
        )
        return SelectedOcrProvider(
            provider=self._paddle_provider,
            engine=OcrEngineMode.PADDLE.value,
            requested_engine=requested.value,
            speed_profile=profile,
        )

    def _windows(self) -> OcrProvider | None:
        if self._windows_provider is False:
            self._windows_provider = self._windows_provider_factory()
        return self._windows_provider or None

    def fallback_to_paddle(
        self,
        selected: SelectedOcrProvider,
        *,
        reason: str,
        disable_windows: bool = False,
    ) -> SelectedOcrProvider:
        if disable_windows:
            self._windows_provider = None
        logger.info(
            "ocr_engine_selected requested_engine=%s selected_ocr_engine=paddle "
            "speed_profile=%s fallback_reason=%s",
            selected.requested_engine,
            selected.speed_profile,
            reason,
        )
        return SelectedOcrProvider(
            provider=self._paddle_provider,
            engine=OcrEngineMode.PADDLE.value,
            requested_engine=selected.requested_engine,
            speed_profile=selected.speed_profile,
            fallback_reason=reason,
        )


def _normalize_engine(value: str | OcrEngineMode | None) -> OcrEngineMode:
    if isinstance(value, OcrEngineMode):
        return value
    if value is None:
        return OcrEngineMode.AUTO
    try:
        return OcrEngineMode(str(value).strip().lower())
    except ValueError:
        return OcrEngineMode.AUTO


def _normalize_speed_profile(value: str | None) -> str:
    profile = str(value or "balanced").strip().lower()
    if profile not in {"fast", "balanced", "accurate"}:
        return "balanced"
    return profile


def _preferred_engine(requested: OcrEngineMode, profile: str) -> OcrEngineMode:
    if requested != OcrEngineMode.AUTO:
        return requested
    if profile == "fast":
        return OcrEngineMode.WINDOWS
    return OcrEngineMode.PADDLE
