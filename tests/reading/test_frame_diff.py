from __future__ import annotations

import pytest
np = pytest.importorskip("numpy")

from screen_translator.reading.frame_diff import FrameDifferenceDetector, FrameSignature


def test_frame_difference_score_is_zero_for_identical_frames() -> None:
    detector = FrameDifferenceDetector()
    previous = FrameSignature(width=2, height=1, samples=(10, 20))
    current = FrameSignature(width=2, height=1, samples=(10, 20))

    assert detector.score(previous, current) == 0.0


def test_frame_difference_score_is_normalized() -> None:
    detector = FrameDifferenceDetector()
    previous = FrameSignature(width=2, height=1, samples=(0, 0))
    current = FrameSignature(width=2, height=1, samples=(255, 255))

    assert detector.score(previous, current) == pytest.approx(1.0)


def test_frame_difference_detector_compares_threshold() -> None:
    detector = FrameDifferenceDetector()
    previous = FrameSignature(width=2, height=1, samples=(100, 100))
    current = FrameSignature(width=2, height=1, samples=(102, 100))

    assert detector.has_changed(previous, current, threshold=0.01) is False
    assert detector.has_changed(previous, current, threshold=0.001) is True


def test_frame_signature_can_be_built_from_test_values() -> None:
    detector = FrameDifferenceDetector()

    signature = detector.signature_from_image([0, 128, 255])

    assert signature == FrameSignature(width=3, height=1, samples=(0, 128, 255))


def test_frame_signature_can_be_built_from_rgb_ndarray() -> None:
    detector = FrameDifferenceDetector()
    image = np.array(
        [
            [[0, 0, 0], [255, 255, 255]],
            [[30, 60, 90], [10, 20, 30]],
        ],
        dtype=np.uint8,
    )

    signature = detector.signature_from_image(image)

    assert signature == FrameSignature(
        width=2,
        height=2,
        samples=(0, 255, 60, 20),
    )
