from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from screen_translator.domain.models import TranslationRequest, TranslationResult

Transport = Callable[[str, dict[str, Any]], dict[str, Any]]
logger = logging.getLogger(__name__)
REQUEST_PAYLOAD_KEYS = ("provider", "source_language", "target_language", "text")


class TranslationClientError(RuntimeError):
    """Raised when the desktop client cannot get a translation."""


class HttpTranslationClient:
    """Translation client that calls the FastAPI translation server."""

    def __init__(
        self,
        base_url: str,
        transport: Transport | None = None,
        *,
        timeout_seconds: float = 20,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport or self._default_transport
        self._timeout_seconds = timeout_seconds
        logger.info(
            "translation client initialized base_url=%s request_payload_keys=%s",
            self._base_url,
            list(REQUEST_PAYLOAD_KEYS),
        )

    def translate(self, request: TranslationRequest) -> TranslationResult:
        url = f"{self._base_url}/translate"
        request_payload = request.to_payload()
        logger.info(
            "translation request payload_keys=%s",
            sorted(request_payload.keys()),
        )
        try:
            payload = self._transport(url, request_payload)
        except TranslationClientError:
            raise
        except Exception as exc:
            raise TranslationClientError("Translation server request failed") from exc

        try:
            return TranslationResult(
                translated_text=str(payload["translated_text"]),
                source_language=str(payload["source_language"]),
                target_language=str(payload["target_language"]),
                provider=str(payload["provider"]),
                cached=bool(payload.get("cached", False)),
            )
        except (KeyError, ValueError) as exc:
            raise TranslationClientError("Translation server returned an invalid response") from exc

    def _default_transport(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib_request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept-Charset": "utf-8",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=self._timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            body = _http_error_body(exc)
            logger.error(
                "translation server returned HTTP error status=%s body=%s",
                exc.code,
                body,
            )
            raise TranslationClientError(
                f"Translation server request failed status={exc.code}"
            ) from exc


def _http_error_body(error: urllib_error.HTTPError) -> str:
    try:
        body = error.read()
    except Exception:
        return "<unavailable>"
    if not body:
        return ""
    return body[:4096].decode("utf-8", errors="replace")
