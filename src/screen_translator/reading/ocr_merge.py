from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from screen_translator.domain.models import OcrTextBlock, ScreenRegion


@dataclass(frozen=True, slots=True)
class OcrMergePolicy:
    """Rules for converting OCR text blocks into readable translation units."""

    min_confidence: float = 0.5
    line_y_tolerance: int = 12
    line_x_gap: int = 28
    paragraph_y_gap: int = 28
    tiny_area_threshold: int = 400
    tiny_high_confidence: float = 0.9
    tiny_text_length: int = 3


class OcrBlockMerger:
    """Provider-independent OCR block merger for Reading Mode."""

    def __init__(self, policy: OcrMergePolicy | None = None) -> None:
        self._policy = policy or OcrMergePolicy()

    def merge(self, blocks: list[OcrTextBlock]) -> list[OcrTextBlock]:
        filtered = [
            block
            for block in blocks
            if self._should_keep(block)
        ]
        if not filtered:
            return []

        lines = self._merge_lines(filtered)
        return self._merge_paragraphs(lines)

    def _should_keep(self, block: OcrTextBlock) -> bool:
        text = block.text.strip()
        if not text or block.confidence < self._policy.min_confidence:
            return False

        area = block.region.width * block.region.height
        if (
            area < self._policy.tiny_area_threshold
            and len(text) <= self._policy.tiny_text_length
            and block.confidence < self._policy.tiny_high_confidence
        ):
            return False
        return True

    def _merge_lines(self, blocks: list[OcrTextBlock]) -> list[OcrTextBlock]:
        ordered = sorted(blocks, key=lambda block: (_center_y(block.region), block.region.x))
        lines: list[list[OcrTextBlock]] = []

        for block in ordered:
            target = _matching_line(block, lines, self._policy.line_y_tolerance)
            if target is None:
                lines.append([block])
            else:
                target.append(block)

        return [
            _merge_block_group(sorted(line, key=lambda block: block.region.x), separator=" ")
            for line in lines
        ]

    def _merge_paragraphs(self, lines: list[OcrTextBlock]) -> list[OcrTextBlock]:
        if not lines:
            return []

        paragraphs: list[list[OcrTextBlock]] = [[lines[0]]]
        for line in lines[1:]:
            previous = paragraphs[-1][-1]
            vertical_gap = line.region.y - previous.region.bottom
            if vertical_gap <= self._policy.paragraph_y_gap and _horizontal_overlap(previous.region, line.region):
                paragraphs[-1].append(line)
            else:
                paragraphs.append([line])

        return [
            _merge_block_group(paragraph, separator="\n")
            for paragraph in paragraphs
        ]


def _matching_line(
    block: OcrTextBlock,
    lines: list[list[OcrTextBlock]],
    tolerance: int,
) -> list[OcrTextBlock] | None:
    for line in lines:
        line_center = mean(_center_y(item.region) for item in line)
        if abs(_center_y(block.region) - line_center) <= tolerance:
            return line
    return None


def _merge_block_group(blocks: list[OcrTextBlock], *, separator: str) -> OcrTextBlock:
    text = separator.join(block.text.strip() for block in blocks if block.text.strip())
    confidence = round(mean(block.confidence for block in blocks), 3)
    return OcrTextBlock(text=text, confidence=confidence, region=_union_region([block.region for block in blocks]))


def _union_region(regions: list[ScreenRegion]) -> ScreenRegion:
    left = min(region.x for region in regions)
    top = min(region.y for region in regions)
    right = max(region.right for region in regions)
    bottom = max(region.bottom for region in regions)
    return ScreenRegion(x=left, y=top, width=right - left, height=bottom - top)


def _center_y(region: ScreenRegion) -> float:
    return region.y + (region.height / 2)


def _horizontal_overlap(left: ScreenRegion, right: ScreenRegion) -> bool:
    overlap = min(left.right, right.right) - max(left.x, right.x)
    if overlap > 0:
        return True
    return abs(left.x - right.x) <= 48
