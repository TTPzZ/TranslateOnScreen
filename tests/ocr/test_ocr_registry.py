from __future__ import annotations

import logging

from screen_translator.config import AppConfig
from screen_translator.domain.models import CapturedImage, OcrTextBlock, ScreenRegion
from screen_translator.ocr.registry import OcrProviderRegistry


class FakeProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        self.calls += 1
        return [OcrTextBlock(self.name, 0.9, ScreenRegion(0, 0, 10, 10))]


def test_windows_ocr_unavailable_falls_back_to_paddle_safely(caplog) -> None:
    paddle = FakeProvider("paddle")
    registry = OcrProviderRegistry(
        paddle_provider=paddle,
        windows_provider_factory=lambda: None,
    )

    with caplog.at_level(logging.INFO, logger="screen_translator.ocr.registry"):
        selected = registry.select(
            requested_engine="windows",
            speed_profile="fast",
            config=AppConfig(source_language="en", target_language="vi"),
        )

    assert selected.engine == "paddle"
    assert selected.fallback_reason == "windows_ocr_unavailable"
    assert selected.provider is paddle
    assert "fallback_reason=windows_ocr_unavailable" in caplog.text


def test_auto_engine_selects_expected_provider_by_speed_profile() -> None:
    paddle = FakeProvider("paddle")
    windows = FakeProvider("windows")
    registry = OcrProviderRegistry(
        paddle_provider=paddle,
        windows_provider_factory=lambda: windows,
    )
    config = AppConfig(source_language="en", target_language="vi")

    assert registry.select(requested_engine="auto", speed_profile="fast", config=config).engine == "windows"
    assert registry.select(requested_engine="auto", speed_profile="balanced", config=config).engine == "paddle"
    assert registry.select(requested_engine="auto", speed_profile="accurate", config=config).engine == "paddle"


def test_explicit_paddle_keeps_existing_provider() -> None:
    paddle = FakeProvider("paddle")
    windows = FakeProvider("windows")
    registry = OcrProviderRegistry(
        paddle_provider=paddle,
        windows_provider_factory=lambda: windows,
    )

    selected = registry.select(
        requested_engine="paddle",
        speed_profile="fast",
        config=AppConfig(source_language="en", target_language="vi"),
    )

    assert selected.engine == "paddle"
    assert selected.provider is paddle
