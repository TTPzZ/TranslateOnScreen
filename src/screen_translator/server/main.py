from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from screen_translator.domain.models import TranslationRequest
from screen_translator.logging_config import configure_logging
from screen_translator.server.providers.base import TranslationProviderError
from screen_translator.server.registry import (
    TranslationProviderRegistry,
    UnknownTranslationProvider,
)


class TranslatePayload(BaseModel):
    text: str
    source_language: str
    target_language: str
    provider: str


def create_app(provider_registry: TranslationProviderRegistry | None = None) -> FastAPI:
    configure_logging()
    registry = provider_registry or TranslationProviderRegistry.from_environment()
    app = FastAPI(title="Screen Translator API")

    @app.post("/translate")
    def translate(payload: TranslatePayload) -> dict[str, str | bool]:
        try:
            request = TranslationRequest(
                text=payload.text,
                source_language=payload.source_language,
                target_language=payload.target_language,
                provider=payload.provider,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            provider = registry.get(request.provider)
        except UnknownTranslationProvider as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            return provider.translate(request).to_payload()
        except TranslationProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return app


app = create_app()
