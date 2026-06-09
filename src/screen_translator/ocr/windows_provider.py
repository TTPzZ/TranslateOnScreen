from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
import logging
import platform
import sys
from typing import Any

from screen_translator.domain.models import CapturedImage, OcrTextBlock, ScreenRegion
from screen_translator.ocr.paddle_provider import OcrError

logger = logging.getLogger(__name__)

WINDOWS_OCR_MODULE = "winrt.windows.media.ocr"
WINDOWS_OCR_PACKAGE = "winrt-Windows.Media.Ocr"
WINDOWS_OCR_INSTALL_COMMAND = f'python -m pip install "{WINDOWS_OCR_PACKAGE}>=3.2.1"'


class WindowsOcrProvider:
    """Optional Windows Runtime OCR provider.

    The provider is intentionally lazy and dependency-light: if Windows OCR bindings
    are not importable, callers should use `create_if_available()` and fall back.
    Tests can inject an `engine_factory` with a compatible `recognize` method.
    """

    def __init__(
        self,
        *,
        engine_factory: Callable[[], Any] | None = None,
        language: str = "en",
    ) -> None:
        self._engine_factory = engine_factory
        self._language = language
        self._engine: Any | None = None

    @classmethod
    def create_if_available(cls) -> WindowsOcrProvider | None:
        available, reason = windows_ocr_availability()
        if not available:
            logger.info("Windows OCR unavailable fallback_reason=%s", reason)
            return None
        return cls()

    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        engine = self._engine_instance()
        if hasattr(engine, "recognize"):
            raw_result = engine.recognize(captured.image)
        else:
            raise OcrError(
                "Windows OCR extraction is unavailable: no supported recognize API"
            )
        return _blocks_from_windows_result(raw_result)

    def _engine_instance(self) -> Any:
        if self._engine is not None:
            return self._engine
        if self._engine_factory is None:
            raise OcrError(
                "Windows OCR extraction is unavailable: install Windows OCR bindings"
            )
        self._engine = self._engine_factory()
        return self._engine


def windows_ocr_availability() -> tuple[bool, str | None]:
    if platform.system() != "Windows":
        return False, "not_windows"
    try:
        __import__(WINDOWS_OCR_MODULE)
    except Exception as exc:
        return False, f"windows_ocr_binding_unavailable:{type(exc).__name__}"
    return True, None


@dataclass(frozen=True, slots=True)
class WindowsOcrDiagnostic:
    available: bool
    reason: str | None
    module: str
    package: str
    package_version: str | None
    install_command: str
    platform_name: str
    python_version: str


def diagnose_windows_ocr() -> WindowsOcrDiagnostic:
    available, reason = windows_ocr_availability()
    return WindowsOcrDiagnostic(
        available=available,
        reason=reason,
        module=WINDOWS_OCR_MODULE,
        package=WINDOWS_OCR_PACKAGE,
        package_version=_installed_package_version(WINDOWS_OCR_PACKAGE),
        install_command=WINDOWS_OCR_INSTALL_COMMAND,
        platform_name=platform.platform(),
        python_version=sys.version.split()[0],
    )


def format_windows_ocr_diagnostic() -> str:
    diagnostic = diagnose_windows_ocr()
    status = "available" if diagnostic.available else "unavailable"
    lines = [
        "Windows OCR diagnostic",
        f"status={status}",
        f"reason={diagnostic.reason or 'none'}",
        f"module={diagnostic.module}",
        f"package={diagnostic.package}",
        f"package_version={diagnostic.package_version or 'not_installed'}",
        f"install_command={diagnostic.install_command}",
        f"platform={diagnostic.platform_name}",
        f"python={diagnostic.python_version}",
    ]
    return "\n".join(lines)


def _installed_package_version(package_name: str) -> str | None:
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose optional Windows OCR support.")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Print Windows OCR availability and dependency information.",
    )
    args = parser.parse_args(argv)
    if args.diagnose:
        print(format_windows_ocr_diagnostic())
        return 0
    parser.print_help()
    return 0


def _blocks_from_windows_result(raw_result: Any) -> list[OcrTextBlock]:
    lines = getattr(raw_result, "lines", raw_result)
    blocks: list[OcrTextBlock] = []
    for line in lines or []:
        text = _line_text(line)
        if not text:
            continue
        region = _line_region(line)
        blocks.append(OcrTextBlock(text, 0.90, region))
    return blocks


def _line_text(line: Any) -> str:
    text = getattr(line, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    words = getattr(line, "words", None)
    if words:
        return " ".join(str(getattr(word, "text", "")).strip() for word in words).strip()
    return str(line).strip()


def _line_region(line: Any) -> ScreenRegion:
    rect = getattr(line, "bounding_rect", None) or getattr(line, "boundingRect", None)
    if rect is not None:
        x = round(float(getattr(rect, "x", 0)))
        y = round(float(getattr(rect, "y", 0)))
        width = max(1, round(float(getattr(rect, "width", 1))))
        height = max(1, round(float(getattr(rect, "height", 1))))
        return ScreenRegion(x, y, width, height)
    words = getattr(line, "words", None)
    word_regions = [_line_region(word) for word in words or [] if hasattr(word, "bounding_rect")]
    if word_regions:
        left = min(region.x for region in word_regions)
        top = min(region.y for region in word_regions)
        right = max(region.right for region in word_regions)
        bottom = max(region.bottom for region in word_regions)
        return ScreenRegion(left, top, right - left, bottom - top)
    return ScreenRegion(0, 0, 1, 1)


if __name__ == "__main__":
    raise SystemExit(main())
