from __future__ import annotations

import os
from collections.abc import Mapping

from screen_translator.server.providers.base import TranslationProvider
from screen_translator.server.providers.google import GoogleTranslateProvider
from screen_translator.server.providers.googletrans import GoogleTransProvider
from screen_translator.server.providers.mock import MockTranslateProvider


class UnknownTranslationProvider(ValueError):
    """Raised when a requested provider is not registered."""


class TranslationProviderRegistry:
    """Lookup table for configured translation providers."""

    def __init__(self, providers: Mapping[str, TranslationProvider]) -> None:
        self._providers = {name.strip().lower(): provider for name, provider in providers.items()}

    @classmethod
    def from_environment(cls) -> "TranslationProviderRegistry":
        configured = os.getenv("TRANSLATION_PROVIDERS", "google")
        requested = [name.strip().lower() for name in configured.split(",") if name.strip()]
        factories = {
            "google": GoogleTranslateProvider,
            "googletrans": GoogleTransProvider,
            "mock": MockTranslateProvider,
        }
        providers = {
            name: factories[name]()
            for name in requested
            if name in factories
        }
        return cls(providers)

    def get(self, name: str) -> TranslationProvider:
        normalized = name.strip().lower()
        try:
            return self._providers[normalized]
        except KeyError as exc:
            raise UnknownTranslationProvider(
                f"Unknown translation provider: {normalized}"
            ) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))
