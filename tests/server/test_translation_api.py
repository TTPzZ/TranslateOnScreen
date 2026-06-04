from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from screen_translator.domain.models import TranslationRequest, TranslationResult
from screen_translator.server.main import create_app
from screen_translator.server.registry import TranslationProviderRegistry

VIETNAMESE_SMOKE_CASES = [
    ("Hello World", "Xin chào thế giới"),
    ("Quest Complete", "Hoàn thành nhiệm vụ"),
    ("Open The Door", "Mở cửa"),
]


class FakeProvider:
    name = "fake"

    def translate(self, request: TranslationRequest) -> TranslationResult:
        assert request.text == "Hello"
        return TranslationResult(
            translated_text="Xin chao",
            source_language=request.source_language,
            target_language=request.target_language,
            provider=self.name,
            cached=False,
        )


def test_translate_endpoint_uses_registered_provider() -> None:
    app = create_app(TranslationProviderRegistry({"fake": FakeProvider()}))
    client = TestClient(app)

    response = client.post(
        "/translate",
        json={
            "text": "Hello",
            "source_language": "en",
            "target_language": "vi",
            "provider": "fake",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "translated_text": "Xin chao",
        "source_language": "en",
        "target_language": "vi",
        "provider": "fake",
        "cached": False,
    }


def test_translate_endpoint_rejects_unknown_provider() -> None:
    app = create_app(TranslationProviderRegistry({}))
    client = TestClient(app)

    response = client.post(
        "/translate",
        json={
            "text": "Hello",
            "source_language": "en",
            "target_language": "vi",
            "provider": "missing",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown translation provider: missing"


def test_translate_endpoint_uses_mock_provider_from_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TRANSLATION_PROVIDERS", "mock")
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/translate",
        json={
            "text": "Hello World",
            "source_language": "auto",
            "target_language": "vi",
            "provider": "mock",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "translated_text": "Xin chào thế giới",
        "source_language": "auto",
        "target_language": "vi",
        "provider": "mock",
        "cached": False,
    }


def test_translate_endpoint_uses_googletrans_provider_from_environment(
    monkeypatch,
) -> None:
    class FakeGoogleTranslator:
        def __init__(self, *, source: str, target: str) -> None:
            self.source = source
            self.target = target

        def translate(self, text: str) -> str:
            assert self.source == "auto"
            assert self.target == "vi"
            assert text == "Hello World"
            return "Xin chào thế giới"

    from screen_translator.server.providers import googletrans

    monkeypatch.setenv("TRANSLATION_PROVIDERS", "googletrans")
    monkeypatch.setattr(
        googletrans,
        "_load_google_translator_class",
        lambda: FakeGoogleTranslator,
    )
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/translate",
        json={
            "text": "Hello World",
            "source_language": "auto",
            "target_language": "vi",
            "provider": "googletrans",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "translated_text": "Xin chào thế giới",
        "source_language": "auto",
        "target_language": "vi",
        "provider": "googletrans",
        "cached": False,
    }


def test_translate_endpoint_mock_provider_normalizes_ocr_whitespace(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TRANSLATION_PROVIDERS", "mock")
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/translate",
        json={
            "text": "Hello\n  World",
            "source_language": "auto",
            "target_language": "vi",
            "provider": "mock",
        },
    )

    assert response.status_code == 200
    assert response.json()["translated_text"] == "Xin chào thế giới"


@pytest.mark.parametrize(("source_text", "translated_text"), VIETNAMESE_SMOKE_CASES)
def test_translate_endpoint_returns_utf8_vietnamese(
    monkeypatch,
    source_text: str,
    translated_text: str,
) -> None:
    monkeypatch.setenv("TRANSLATION_PROVIDERS", "mock")
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/translate",
        json={
            "text": source_text,
            "source_language": "auto",
            "target_language": "vi",
            "provider": "mock",
        },
    )

    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    response_text = response.content.decode("utf-8")
    assert "Ã" not in response_text
    assert "á»" not in response_text
    assert response.json()["translated_text"] == translated_text
