from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from screen_translator.translation import client as client_module
from screen_translator.domain.models import TranslationRequest, TranslationResult
from screen_translator.server.main import create_app
from screen_translator.server.registry import TranslationProviderRegistry
from screen_translator.translation.client import HttpTranslationClient, TranslationClientError


def test_http_translation_client_posts_translate_request() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def transport(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((url, payload))
        return {
            "translated_text": "Xin chao",
            "source_language": "en",
            "target_language": "vi",
            "provider": "google",
            "cached": False,
        }

    client = HttpTranslationClient(
        base_url="http://127.0.0.1:8000",
        transport=transport,
    )

    result = client.translate(
        TranslationRequest(
            text="Hello",
            source_language="en",
            target_language="vi",
            provider="google",
        )
    )

    assert calls == [
        (
            "http://127.0.0.1:8000/translate",
            {
                "text": "Hello",
                "source_language": "en",
                "target_language": "vi",
                "provider": "google",
            },
        )
    ]
    assert result == TranslationResult(
        translated_text="Xin chao",
        source_language="en",
        target_language="vi",
        provider="google",
        cached=False,
    )


def test_http_translation_client_logs_startup_payload_schema(caplog) -> None:
    with caplog.at_level("INFO", logger="screen_translator.translation.client"):
        HttpTranslationClient("http://127.0.0.1:8000")

    assert "translation client initialized" in caplog.text
    assert "request_payload_keys=['provider', 'source_language', 'target_language', 'text']" in caplog.text
    assert "'source_lang'" not in caplog.text
    assert "'target_lang'" not in caplog.text
    assert "'engine'" not in caplog.text


def test_desktop_http_client_integrates_with_fastapi_translate_endpoint() -> None:
    class GoogleTransProvider:
        name = "googletrans"

        def translate(self, request: TranslationRequest) -> TranslationResult:
            assert request.provider == "googletrans"
            return TranslationResult(
                translated_text="Xin chao",
                source_language=request.source_language,
                target_language=request.target_language,
                provider=self.name,
            )

    api_client = TestClient(
        create_app(TranslationProviderRegistry({"googletrans": GoogleTransProvider()}))
    )
    posted_payloads: list[dict[str, Any]] = []

    def transport(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert url == "http://testserver/translate"
        posted_payloads.append(payload)
        response = api_client.post("/translate", json=payload)
        assert response.status_code == 200, response.text
        return response.json()

    client = HttpTranslationClient("http://testserver", transport=transport)

    result = client.translate(
        TranslationRequest(
            text="Hello",
            source_language="auto",
            target_language="vi",
            provider="googletrans",
        )
    )

    assert posted_payloads == [
        {
            "text": "Hello",
            "source_language": "auto",
            "target_language": "vi",
            "provider": "googletrans",
        }
    ]
    assert "source_lang" not in posted_payloads[0]
    assert "target_lang" not in posted_payloads[0]
    assert "engine" not in posted_payloads[0]
    assert result == TranslationResult("Xin chao", "auto", "vi", "googletrans")


def test_http_translation_client_logs_payload_keys_without_text_content(caplog) -> None:
    def transport(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        del url, payload
        return {
            "translated_text": "Xin chao",
            "source_language": "en",
            "target_language": "vi",
            "provider": "mock",
            "cached": False,
        }

    client = HttpTranslationClient("http://127.0.0.1:8000", transport=transport)

    with caplog.at_level("INFO", logger="screen_translator.translation.client"):
        client.translate(
            TranslationRequest(
                text="Sensitive text should not be logged",
                source_language="en",
                target_language="vi",
                provider="mock",
            )
        )

    assert "translation request payload_keys=" in caplog.text
    assert "provider" in caplog.text
    assert "source_language" in caplog.text
    assert "target_language" in caplog.text
    assert "text" in caplog.text
    assert "Sensitive text should not be logged" not in caplog.text


def test_http_translation_client_wraps_transport_errors() -> None:
    def transport(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        del url, payload
        raise OSError("network down")

    client = HttpTranslationClient(base_url="http://127.0.0.1:8000", transport=transport)

    with pytest.raises(TranslationClientError, match="Translation server request failed"):
        client.translate(
            TranslationRequest(
                text="Hello",
                source_language="en",
                target_language="vi",
                provider="google",
            )
        )


def test_http_translation_client_logs_http_400_response_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog,
) -> None:
    def fake_urlopen(request: object, timeout: float) -> object:
        del request, timeout
        raise HTTPError(
            url="http://127.0.0.1:8000/translate",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"detail":"Unknown translation provider: missing"}'),
        )

    monkeypatch.setattr(client_module.urllib_request, "urlopen", fake_urlopen)
    client = HttpTranslationClient("http://127.0.0.1:8000")

    with caplog.at_level("ERROR", logger="screen_translator.translation.client"):
        with pytest.raises(TranslationClientError, match="status=400"):
            client.translate(
                TranslationRequest(
                    text="Hello",
                    source_language="en",
                    target_language="vi",
                    provider="missing",
                )
            )

    assert "translation server returned HTTP error status=400" in caplog.text
    assert "Unknown translation provider: missing" in caplog.text


@pytest.mark.parametrize(
    ("source_text", "translated_text"),
    [
        ("Hello World", "Xin chào thế giới"),
        ("Quest Complete", "Hoàn thành nhiệm vụ"),
        ("Open The Door", "Mở cửa"),
    ],
)
def test_http_translation_client_default_transport_decodes_utf8_response(
    monkeypatch: pytest.MonkeyPatch,
    source_text: str,
    translated_text: str,
) -> None:
    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        def read(self) -> bytes:
            return json.dumps(
                {
                    "translated_text": translated_text,
                    "source_language": "en",
                    "target_language": "vi",
                    "provider": "mock",
                    "cached": False,
                },
                ensure_ascii=False,
            ).encode("utf-8")

    captured_requests: list[object] = []

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        del timeout
        captured_requests.append(request)
        return FakeResponse()

    monkeypatch.setattr(client_module.urllib_request, "urlopen", fake_urlopen)
    client = HttpTranslationClient("http://127.0.0.1:8000")

    result = client.translate(
        TranslationRequest(
            text=source_text,
            source_language="en",
            target_language="vi",
            provider="mock",
        )
    )

    assert result.translated_text == translated_text
    assert captured_requests
    request = captured_requests[0]
    assert request.headers["Content-type"] == "application/json; charset=utf-8"
    assert json.loads(request.data.decode("utf-8"))["text"] == source_text
