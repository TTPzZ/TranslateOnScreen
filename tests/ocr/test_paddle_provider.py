from __future__ import annotations

import logging
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
np = pytest.importorskip("numpy")

from screen_translator.domain.models import CapturedImage, OcrTextBlock, ScreenRegion
from screen_translator.ocr import paddle_provider as paddle_provider_module
from screen_translator.ocr.paddle_provider import OcrError, PaddleOcrProvider


class FakePaddleEngine:
    def __init__(self, result: list[Any]) -> None:
        self.result = result
        self.calls: list[tuple[Any, bool]] = []

    def ocr(self, image: Any, cls: bool = True) -> list[Any]:
        self.calls.append((image, cls))
        return self.result


class FakeDeprecatedOcrWrapperEngine:
    def __init__(self, result: list[Any]) -> None:
        self.result = result
        self.calls: list[tuple[str, Any]] = []

    def predict(self, image: Any) -> list[Any]:
        self.calls.append(("predict", image))
        return self.result

    def ocr(self, image: Any, **kwargs: Any) -> list[Any]:
        return self.predict(image, **kwargs)


class FakePredictEngine:
    def __init__(self, result: list[Any]) -> None:
        self.result = result
        self.calls: list[Any] = []

    def predict(self, image: Any) -> list[Any]:
        self.calls.append(image)
        return self.result


class FakeRecognizeEngine:
    def __init__(self, result: list[Any]) -> None:
        self.result = result
        self.calls: list[Any] = []

    def recognize(self, image: Any) -> list[Any]:
        self.calls.append(image)
        return self.result


class FakeCallableEngine:
    def __init__(self, result: list[Any]) -> None:
        self.result = result
        self.calls: list[Any] = []

    def __call__(self, image: Any) -> list[Any]:
        self.calls.append(image)
        return self.result


class FakePaddleOcrClass:
    instances: list["FakePaddleOcrClass"] = []

    def __init__(
        self,
        *,
        lang: str | None = None,
        use_doc_orientation_classify: bool | None = None,
        use_doc_unwarping: bool | None = None,
        use_textline_orientation: bool | None = None,
        **kwargs: Any,
    ) -> None:
        self.kwargs = {
            "lang": lang,
            "use_doc_orientation_classify": use_doc_orientation_classify,
            "use_doc_unwarping": use_doc_unwarping,
            "use_textline_orientation": use_textline_orientation,
            **kwargs,
        }
        self.result: list[Any] = []
        FakePaddleOcrClass.instances.append(self)

    def predict(self, image: Any) -> list[Any]:
        del image
        return self.result


class FakeQPixmap:
    pass


def _sample_image() -> Any:
    return np.zeros((1, 1, 3), dtype=np.uint8)


def test_paddle_provider_normalizes_text_blocks() -> None:
    raw_result = [
        [
            ([[10, 20], [110, 20], [110, 50], [10, 50]], ("Hello", 0.95)),
            ([[40, 70], [160, 70], [160, 100], [40, 100]], ("World", 0.8)),
        ]
    ]
    engine = FakePaddleEngine(raw_result)
    image = _sample_image()
    captured = CapturedImage(region=ScreenRegion(0, 0, 800, 600), image=image)

    blocks = PaddleOcrProvider(engine_factory=lambda: engine).extract_text(captured)

    assert blocks == [
        OcrTextBlock(
            text="Hello",
            confidence=0.95,
            region=ScreenRegion(10, 20, 100, 30),
        ),
        OcrTextBlock(
            text="World",
            confidence=0.8,
            region=ScreenRegion(40, 70, 120, 30),
        ),
    ]
    assert len(engine.calls) == 1
    assert engine.calls[0][0] is image
    assert engine.calls[0][1] is True


def test_paddle_provider_prefers_predict_without_legacy_cls_keyword() -> None:
    raw_result = [
        [
            ([[10, 20], [150, 20], [150, 50], [10, 50]], ("Hello World", 0.95)),
        ]
    ]
    engine = FakeDeprecatedOcrWrapperEngine(raw_result)
    image = _sample_image()
    captured = CapturedImage(region=ScreenRegion(0, 0, 800, 600), image=image)

    blocks = PaddleOcrProvider(engine_factory=lambda: engine).extract_text(captured)

    assert blocks == [
        OcrTextBlock(
            text="Hello World",
            confidence=0.95,
            region=ScreenRegion(10, 20, 140, 30),
        ),
    ]
    assert len(engine.calls) == 1
    assert engine.calls[0][0] == "predict"
    assert engine.calls[0][1] is image


def test_paddle_provider_normalizes_paddleocr_v3_predict_results() -> None:
    raw_result = [
        {
            "rec_texts": ["Hello World"],
            "rec_scores": [0.97],
            "rec_polys": [
                [[10, 20], [150, 20], [150, 50], [10, 50]],
            ],
        }
    ]
    engine = FakePredictEngine(raw_result)
    image = _sample_image()
    captured = CapturedImage(region=ScreenRegion(0, 0, 800, 600), image=image)

    blocks = PaddleOcrProvider(engine_factory=lambda: engine).extract_text(captured)

    assert blocks == [
        OcrTextBlock(
            text="Hello World",
            confidence=0.97,
            region=ScreenRegion(10, 20, 140, 30),
        ),
    ]
    assert len(engine.calls) == 1
    assert engine.calls[0] is image


def test_paddle_provider_falls_back_to_recognize_api() -> None:
    raw_result = [
        [
            ([[10, 20], [150, 20], [150, 50], [10, 50]], ("Hello World", 0.95)),
        ]
    ]
    engine = FakeRecognizeEngine(raw_result)
    image = _sample_image()
    captured = CapturedImage(region=ScreenRegion(0, 0, 800, 600), image=image)

    blocks = PaddleOcrProvider(engine_factory=lambda: engine).extract_text(captured)

    assert blocks == [
        OcrTextBlock(
            text="Hello World",
            confidence=0.95,
            region=ScreenRegion(10, 20, 140, 30),
        ),
    ]
    assert len(engine.calls) == 1
    assert engine.calls[0] is image


def test_paddle_provider_falls_back_to_callable_ocr_api() -> None:
    raw_result = [
        [
            ([[10, 20], [150, 20], [150, 50], [10, 50]], ("Hello World", 0.95)),
        ]
    ]
    engine = FakeCallableEngine(raw_result)
    image = _sample_image()
    captured = CapturedImage(region=ScreenRegion(0, 0, 800, 600), image=image)

    blocks = PaddleOcrProvider(engine_factory=lambda: engine).extract_text(captured)

    assert blocks == [
        OcrTextBlock(
            text="Hello World",
            confidence=0.95,
            region=ScreenRegion(10, 20, 140, 30),
        ),
    ]
    assert len(engine.calls) == 1
    assert engine.calls[0] is image


def test_paddle_provider_filters_empty_and_low_confidence_text() -> None:
    raw_result = [
        [
            ([[0, 0], [10, 0], [10, 10], [0, 10]], ("", 0.99)),
            ([[0, 0], [20, 0], [20, 10], [0, 10]], ("weak", 0.2)),
            ([[0, 0], [30, 0], [30, 10], [0, 10]], ("strong", 0.9)),
        ]
    ]
    engine = FakePaddleEngine(raw_result)
    captured = CapturedImage(region=ScreenRegion(0, 0, 800, 600), image=_sample_image())

    blocks = PaddleOcrProvider(
        engine_factory=lambda: engine,
        min_confidence=0.5,
    ).extract_text(captured)

    assert blocks == [
        OcrTextBlock(
            text="strong",
            confidence=0.9,
            region=ScreenRegion(0, 0, 30, 10),
        ),
    ]


def test_paddle_provider_reports_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "paddleocr", None)
    captured = CapturedImage(region=ScreenRegion(0, 0, 800, 600), image=_sample_image())

    with pytest.raises(OcrError, match="PaddleOCR is required"):
        PaddleOcrProvider().extract_text(captured)


def test_paddle_provider_rejects_unsupported_image_payload_before_invoking_engine() -> None:
    engine = FakePredictEngine([])
    captured = CapturedImage(region=ScreenRegion(0, 0, 800, 600), image=FakeQPixmap())

    with pytest.raises(OcrError, match="Unsupported OCR image payload type: FakeQPixmap"):
        PaddleOcrProvider(engine_factory=lambda: engine).extract_text(captured)

    assert engine.calls == []


def test_paddle_provider_uses_stable_windows_constructor_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakePaddleOcrClass.instances.clear()
    paddleocr_module = ModuleType("paddleocr")
    paddleocr_module.PaddleOCR = FakePaddleOcrClass
    monkeypatch.setitem(sys.modules, "paddleocr", paddleocr_module)
    captured = CapturedImage(region=ScreenRegion(0, 0, 800, 600), image=_sample_image())

    PaddleOcrProvider().extract_text(captured)

    assert FakePaddleOcrClass.instances[0].kwargs == {
        "lang": "en",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": True,
        "enable_mkldnn": False,
    }


def test_paddle_provider_logs_runtime_versions_once(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        paddle_provider_module,
        "paddle_runtime_versions",
        lambda: SimpleNamespace(paddleocr="3.6.0", paddlepaddle="3.3.1"),
    )
    engine = FakePaddleEngine([])
    captured = CapturedImage(region=ScreenRegion(0, 0, 800, 600), image=_sample_image())
    provider = PaddleOcrProvider(engine_factory=lambda: engine)

    with caplog.at_level(logging.INFO, logger="screen_translator.ocr.paddle_provider"):
        provider.extract_text(captured)
        provider.extract_text(captured)

    messages = [record.message for record in caplog.records]
    version_messages = [
        message for message in messages if message.startswith("PaddleOCR runtime")
    ]
    assert version_messages == [
        "PaddleOCR runtime paddleocr_version=3.6.0 paddlepaddle_version=3.3.1"
    ]


def test_paddle_provider_logs_ocr_failures_with_versions_and_traceback(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingEngine:
        def predict(self, image: Any) -> list[Any]:
            del image
            raise TypeError("predict failed")

    monkeypatch.setattr(
        paddle_provider_module,
        "paddle_runtime_versions",
        lambda: SimpleNamespace(paddleocr="3.6.0", paddlepaddle="3.3.1"),
    )
    captured = CapturedImage(region=ScreenRegion(0, 0, 800, 600), image=_sample_image())

    with caplog.at_level(logging.ERROR, logger="screen_translator.ocr.paddle_provider"):
        with pytest.raises(OcrError, match="TypeError: predict failed"):
            PaddleOcrProvider(engine_factory=FailingEngine).extract_text(captured)

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.exc_info is not None
    assert "exception_type=TypeError" in record.message
    assert "paddleocr_version=3.6.0" in record.message
    assert "paddlepaddle_version=3.3.1" in record.message


def test_shared_paddle_provider_reuses_one_engine_across_instances() -> None:
    raw_result = [
        [
            ([[0, 0], [10, 0], [10, 10], [0, 10]], ("Hello", 0.95)),
        ]
    ]
    engine = FakePredictEngine(raw_result)
    create_calls = 0

    def factory() -> FakePredictEngine:
        nonlocal create_calls
        create_calls += 1
        return engine

    captured = CapturedImage(region=ScreenRegion(0, 0, 10, 10), image=_sample_image())
    first = PaddleOcrProvider(engine_factory=factory, shared_engine=True)
    second = PaddleOcrProvider(engine_factory=factory, shared_engine=True)

    first.extract_text(captured)
    second.extract_text(captured)

    assert create_calls == 1
    assert engine.calls == [captured.image, captured.image]


def test_paddle_provider_warm_up_initializes_shared_engine_once() -> None:
    engine = FakePredictEngine([])
    create_calls = 0

    def factory() -> FakePredictEngine:
        nonlocal create_calls
        create_calls += 1
        return engine

    provider = PaddleOcrProvider(engine_factory=factory, shared_engine=True)
    captured = CapturedImage(region=ScreenRegion(0, 0, 10, 10), image=_sample_image())

    provider.warm_up()
    provider.extract_text(captured)

    assert create_calls == 1
    assert len(engine.calls) == 2
    assert type(engine.calls[0]).__name__ == "ndarray"
