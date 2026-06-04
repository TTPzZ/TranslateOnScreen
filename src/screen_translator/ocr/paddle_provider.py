from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import inspect
from importlib import metadata as importlib_metadata
import logging
from threading import Lock
from typing import Any

from screen_translator.domain.models import CapturedImage, OcrTextBlock, ScreenRegion

logger = logging.getLogger(__name__)
_SHARED_ENGINE_LOCK = Lock()
_SHARED_ENGINES: dict[tuple[Any, ...], Any] = {}


class OcrError(RuntimeError):
    """Raised when OCR cannot be completed."""


@dataclass(frozen=True, slots=True)
class PaddleRuntimeVersions:
    paddleocr: str
    paddlepaddle: str


@dataclass(frozen=True, slots=True)
class _OcrInvocation:
    name: str
    method: Callable[..., Any]
    kwargs: dict[str, Any]


class PaddleOcrProvider:
    """OCR provider backed by PaddleOCR."""

    def __init__(
        self,
        engine_factory: Callable[[], Any] | None = None,
        *,
        language: str = "en",
        min_confidence: float = 0.0,
        shared_engine: bool = True,
    ) -> None:
        self._engine_factory = engine_factory
        self._language = language
        self._min_confidence = min_confidence
        self._shared_engine = shared_engine
        self._engine: Any | None = None
        self._ocr_invocation: _OcrInvocation | None = None
        self._versions_logged = False

    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        _validate_ocr_image_payload(captured.image)
        engine = self._engine_instance()
        try:
            raw_result = self._invoke_ocr(engine, captured.image)
        except OcrError:
            raise
        except Exception as exc:
            versions = paddle_runtime_versions()
            logger.exception(
                "OCR failed exception_type=%s paddleocr_version=%s paddlepaddle_version=%s",
                type(exc).__name__,
                versions.paddleocr,
                versions.paddlepaddle,
            )
            raise OcrError(
                f"PaddleOCR extraction failed: {type(exc).__name__}: {exc}"
            ) from exc

        blocks: list[OcrTextBlock] = []

        for line in _iter_ocr_lines(raw_result):
            block = _block_from_line(line)
            if block is None:
                continue
            if not block.text or block.confidence < self._min_confidence:
                continue
            blocks.append(block)

        return blocks

    def warm_up(self) -> None:
        """Initialize the OCR engine and run a tiny OCR pass."""

        image = _warm_up_image()
        if image is None:
            logger.warning("PaddleOCR warm-up skipped: numpy is unavailable")
            return

        logger.info("PaddleOCR warm-up started")
        try:
            self.extract_text(
                CapturedImage(
                    region=ScreenRegion(0, 0, 16, 16),
                    image=image,
                )
            )
        except Exception as exc:
            versions = paddle_runtime_versions()
            logger.warning(
                "PaddleOCR warm-up failed exception_type=%s paddleocr_version=%s "
                "paddlepaddle_version=%s",
                type(exc).__name__,
                versions.paddleocr,
                versions.paddlepaddle,
                exc_info=True,
            )
        else:
            logger.info("PaddleOCR warm-up completed")

    def _engine_instance(self) -> Any:
        if self._engine is not None:
            return self._engine

        if self._shared_engine:
            key, builder = self._shared_engine_spec()
            self._engine = _shared_engine_instance(key, builder)
            self._log_runtime_versions()
            return self._engine

        self._engine = self._build_engine()
        self._log_runtime_versions()
        return self._engine

    def _shared_engine_spec(self) -> tuple[tuple[Any, ...], Callable[[], Any]]:
        if self._engine_factory is not None:
            return (
                ("factory", _factory_cache_key(self._engine_factory), self._language),
                self._engine_factory,
            )

        paddle_ocr_class = _load_paddle_ocr_class()
        kwargs = _paddle_constructor_kwargs(paddle_ocr_class, self._language)
        return (
            ("default", id(paddle_ocr_class), self._language),
            lambda: paddle_ocr_class(**kwargs),
        )

    def _build_engine(self) -> Any:
        if self._engine_factory is not None:
            return self._engine_factory()

        paddle_ocr_class = _load_paddle_ocr_class()
        return paddle_ocr_class(
            **_paddle_constructor_kwargs(paddle_ocr_class, self._language)
        )

    def _invoke_ocr(self, engine: Any, image: Any) -> Any:
        if self._ocr_invocation is None:
            self._ocr_invocation = _detect_ocr_invocation(engine)
            logger.info("PaddleOCR API selected api=%s", self._ocr_invocation.name)
        return self._ocr_invocation.method(image, **self._ocr_invocation.kwargs)

    def _log_runtime_versions(self) -> None:
        if self._versions_logged:
            return
        versions = paddle_runtime_versions()
        logger.info(
            "PaddleOCR runtime paddleocr_version=%s paddlepaddle_version=%s",
            versions.paddleocr,
            versions.paddlepaddle,
        )
        self._versions_logged = True


def paddle_runtime_versions() -> PaddleRuntimeVersions:
    return PaddleRuntimeVersions(
        paddleocr=_package_version("paddleocr"),
        paddlepaddle=_package_version("paddlepaddle"),
    )


def _package_version(package_name: str) -> str:
    try:
        return importlib_metadata.version(package_name)
    except importlib_metadata.PackageNotFoundError:
        return "not installed"
    except Exception as exc:
        return f"unknown ({type(exc).__name__})"


def _load_paddle_ocr_class() -> Any:
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise OcrError("PaddleOCR is required for PaddleOcrProvider") from exc
    return PaddleOCR


def _shared_engine_instance(
    key: tuple[Any, ...],
    builder: Callable[[], Any],
) -> Any:
    with _SHARED_ENGINE_LOCK:
        engine = _SHARED_ENGINES.get(key)
        if engine is not None:
            return engine
        logger.info(
            "PaddleOCR shared engine initializing key=%s language=%s",
            key[0],
            key[-1],
        )
        engine = builder()
        _SHARED_ENGINES[key] = engine
        logger.info(
            "PaddleOCR shared engine initialized key=%s language=%s",
            key[0],
            key[-1],
        )
        return engine


def _factory_cache_key(factory: Callable[[], Any]) -> Any:
    try:
        hash(factory)
    except TypeError:
        return id(factory)
    return factory


def _warm_up_image() -> Any | None:
    try:
        import numpy as np
    except ImportError:
        return None
    return np.full((16, 16, 3), 255, dtype=np.uint8)


def _detect_ocr_invocation(engine: Any) -> _OcrInvocation:
    predict = getattr(engine, "predict", None)
    if callable(predict):
        return _OcrInvocation("predict", predict, {})

    ocr = getattr(engine, "ocr", None)
    if callable(ocr):
        kwargs = {"cls": True} if _explicitly_accepts_keyword(ocr, "cls") else {}
        return _OcrInvocation("ocr", ocr, kwargs)

    recognize = getattr(engine, "recognize", None)
    if callable(recognize):
        return _OcrInvocation("recognize", recognize, {})

    if callable(engine):
        return _OcrInvocation("__call__", engine, {})

    raise OcrError("PaddleOCR engine does not expose a supported OCR API")


def _validate_ocr_image_payload(image: Any) -> None:
    if isinstance(image, str) or _is_numpy_ndarray(image):
        return
    raise OcrError(
        "Unsupported OCR image payload type: "
        f"{type(image).__name__}. PaddleOCR requires numpy.ndarray or str path; "
        "normalize Qt QPixmap/QImage before OCR."
    )


def _is_numpy_ndarray(value: Any) -> bool:
    value_type = type(value)
    return (
        value_type.__module__.split(".", maxsplit=1)[0] == "numpy"
        and value_type.__name__ == "ndarray"
    )


def _paddle_constructor_kwargs(paddle_ocr_class: Any, language: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"lang": language}
    if _explicitly_accepts_keyword(paddle_ocr_class, "use_doc_orientation_classify"):
        kwargs["use_doc_orientation_classify"] = False
    if _explicitly_accepts_keyword(paddle_ocr_class, "use_doc_unwarping"):
        kwargs["use_doc_unwarping"] = False
    if _explicitly_accepts_keyword(paddle_ocr_class, "use_textline_orientation"):
        kwargs["use_textline_orientation"] = True
    elif _explicitly_accepts_keyword(paddle_ocr_class, "use_angle_cls"):
        kwargs["use_angle_cls"] = True
    if _accepts_keyword(paddle_ocr_class, "enable_mkldnn"):
        kwargs["enable_mkldnn"] = False
    return kwargs


def _accepts_keyword(callable_obj: Callable[..., Any], keyword: str) -> bool:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return False

    if keyword in signature.parameters:
        return True
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _explicitly_accepts_keyword(callable_obj: Callable[..., Any], keyword: str) -> bool:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return False

    parameter = signature.parameters.get(keyword)
    if parameter is None:
        return False
    return parameter.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    )


def _iter_ocr_lines(raw_result: Any) -> Iterable[Any]:
    if raw_result is None:
        return []

    structured_lines = _structured_ocr_lines(raw_result)
    if structured_lines is not None:
        return structured_lines

    if isinstance(raw_result, list) and raw_result and _looks_like_line(raw_result[0]):
        return raw_result

    if isinstance(raw_result, list) and len(raw_result) == 1 and isinstance(raw_result[0], list):
        structured_lines = _structured_ocr_lines(raw_result[0])
        if structured_lines is not None:
            return structured_lines
        return raw_result[0]

    if isinstance(raw_result, list):
        lines: list[Any] = []
        for page in raw_result:
            structured_lines = _structured_ocr_lines(page)
            if structured_lines is not None:
                lines.extend(structured_lines)
            elif isinstance(page, list):
                lines.extend(page)
        return lines

    return []


def _structured_ocr_lines(raw_result: Any) -> list[Any] | None:
    texts = _result_value(raw_result, "rec_texts")
    scores = _result_value(raw_result, "rec_scores")
    polys = _result_value(raw_result, "rec_polys")
    if polys is None:
        polys = _boxes_to_polys(_result_value(raw_result, "rec_boxes"))

    if texts is None or scores is None or polys is None:
        return None

    return [
        (points, (text, score))
        for text, score, points in zip(
            _as_list(texts),
            _as_list(scores),
            _as_list(polys),
        )
    ]


def _result_value(raw_result: Any, key: str) -> Any:
    if isinstance(raw_result, Mapping):
        return raw_result.get(key)

    get = getattr(raw_result, "get", None)
    if callable(get):
        try:
            return get(key)
        except Exception:
            pass

    try:
        return raw_result[key]
    except Exception:
        return getattr(raw_result, key, None)


def _boxes_to_polys(boxes: Any) -> list[Any] | None:
    if boxes is None:
        return None

    polys: list[Any] = []
    for box in _as_list(boxes):
        coords = _as_list(box)
        if len(coords) >= 4 and not isinstance(coords[0], (list, tuple)):
            left, top, right, bottom = coords[:4]
            polys.append(
                [
                    [left, top],
                    [right, top],
                    [right, bottom],
                    [left, bottom],
                ]
            )
        else:
            polys.append(box)
    return polys


def _looks_like_line(value: Any) -> bool:
    line = _as_sequence(value)
    if line is None or len(line) < 2:
        return False
    points = _as_sequence(line[0])
    metadata = _as_sequence(line[1])
    if points is None or metadata is None or not points:
        return False
    first_point = _as_sequence(points[0])
    return (
        first_point is not None
        and len(first_point) >= 2
        and len(metadata) >= 2
        and isinstance(metadata[0], str)
        and isinstance(metadata[1], (int, float))
    )


def _block_from_line(line: Any) -> OcrTextBlock | None:
    if not _looks_like_line(line):
        return None

    line_values = _as_sequence(line)
    if line_values is None:
        return None

    points = line_values[0]
    metadata = _as_sequence(line_values[1])
    if metadata is None:
        return None

    text = str(metadata[0]).strip()
    confidence = float(metadata[1])
    region = _region_from_points(points)
    if region is None:
        return None

    return OcrTextBlock(text=text, confidence=confidence, region=region)


def _region_from_points(points: Any) -> ScreenRegion | None:
    point_values = _as_sequence(points)
    if point_values is None or not point_values:
        return None

    xs: list[int] = []
    ys: list[int] = []
    for point in point_values:
        point_pair = _as_sequence(point)
        if point_pair is None or len(point_pair) < 2:
            return None
        xs.append(round(float(point_pair[0])))
        ys.append(round(float(point_pair[1])))

    left = min(xs)
    top = min(ys)
    width = max(xs) - left
    height = max(ys) - top
    if width <= 0 or height <= 0:
        return None

    return ScreenRegion(x=left, y=top, width=width, height=height)


def _as_list(value: Any) -> list[Any]:
    sequence = _as_sequence(value)
    if sequence is None:
        return []
    return list(sequence)


def _as_sequence(value: Any) -> Any:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return value
    return None
