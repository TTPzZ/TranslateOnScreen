from __future__ import annotations

from screen_translator.server.registry import TranslationProviderRegistry


def test_registry_from_environment_supports_mock_without_removing_google(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TRANSLATION_PROVIDERS", "mock,google")

    registry = TranslationProviderRegistry.from_environment()

    assert registry.names() == ("google", "mock")


def test_registry_from_environment_supports_googletrans_without_cloud_credentials(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TRANSLATION_PROVIDERS", "googletrans")

    registry = TranslationProviderRegistry.from_environment()

    assert registry.names() == ("googletrans",)
