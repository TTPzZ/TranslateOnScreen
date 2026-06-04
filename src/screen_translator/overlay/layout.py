from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from screen_translator.domain.models import OcrTextBlock, ScreenRegion
from screen_translator.instrumentation import PipelineTimings

_PANEL_VERTICAL_GAP = 6
_PANEL_HORIZONTAL_PADDING = 28
_PANEL_VERTICAL_PADDING = 18
_ESTIMATED_CHAR_WIDTH = 11
_ESTIMATED_LINE_HEIGHT = 30
_MIN_PANEL_WIDTH = 96
_MAX_PANEL_WIDTH = 500


@dataclass(frozen=True, slots=True)
class OverlayItem:
    """Translated text placed over a screen region."""

    text: str
    region: ScreenRegion


@dataclass(frozen=True, slots=True)
class OverlayStyle:
    """Visual defaults for gaming-mode overlays."""

    blur_background: bool = True
    text_color: str = "#ffffff"
    background_rgba: tuple[int, int, int, int] = (0, 0, 0, 150)
    font_size: int = 18


def build_overlay_items(
    ocr_blocks: Sequence[OcrTextBlock],
    translations: Sequence[str],
    *,
    selected_region: ScreenRegion | None = None,
    screen_bounds: ScreenRegion | None = None,
    max_panel_width: int = _MAX_PANEL_WIDTH,
) -> list[OverlayItem]:
    if len(ocr_blocks) != len(translations):
        raise ValueError("translations count must match OCR blocks")

    items: list[OverlayItem] = []
    for block, translation in zip(ocr_blocks, translations, strict=True):
        text = translation.strip()
        if not text:
            continue

        if selected_region is None:
            region = block.region
            if screen_bounds is not None:
                region = _clamp_region(region, screen_bounds)
        else:
            region = _translation_panel_region(
                text=text,
                ocr_region=block.region,
                selected_region=selected_region,
                screen_bounds=screen_bounds,
                max_panel_width=max_panel_width,
            )
        items.append(OverlayItem(text=text, region=region))
    if selected_region is not None:
        items = stack_overlay_items(items, screen_bounds)
    return items


def append_debug_overlay_item(
    items: Sequence[OverlayItem],
    timings: PipelineTimings,
) -> list[OverlayItem]:
    debug_text = (
        f"OCR: {timings.ocr_ms:.2f} ms\n"
        f"Translation: {timings.translation_request_ms:.2f} ms\n"
        f"Cache: {timings.cache_status}\n"
        f"Region: {timings.region_width}x{timings.region_height}"
    )
    warnings = timings.performance_warnings()
    if warnings:
        debug_text = f"{debug_text}\nWarnings: {', '.join(warnings)}"
    return [
        *items,
        OverlayItem(
            text=debug_text,
            region=ScreenRegion(x=10, y=10, width=320, height=96),
        ),
    ]


def _translation_panel_region(
    *,
    text: str,
    ocr_region: ScreenRegion,
    selected_region: ScreenRegion,
    screen_bounds: ScreenRegion | None,
    max_panel_width: int,
) -> ScreenRegion:
    anchor = ScreenRegion(
        x=selected_region.x + ocr_region.x,
        y=selected_region.y + ocr_region.y,
        width=ocr_region.width,
        height=ocr_region.height,
    )
    panel_width, panel_height = _estimate_panel_size(
        text,
        anchor,
        screen_bounds,
        max_panel_width=max_panel_width,
    )
    below_y = anchor.bottom + _PANEL_VERTICAL_GAP
    y = below_y

    if screen_bounds is not None:
        above_y = anchor.y - _PANEL_VERTICAL_GAP - panel_height
        if below_y + panel_height > screen_bounds.bottom and above_y >= screen_bounds.y:
            y = above_y

    panel = ScreenRegion(
        x=anchor.x,
        y=y,
        width=panel_width,
        height=panel_height,
    )
    if screen_bounds is not None:
        return _clamp_region(panel, screen_bounds)
    return panel


def _estimate_panel_size(
    text: str,
    anchor: ScreenRegion,
    screen_bounds: ScreenRegion | None,
    *,
    max_panel_width: int = _MAX_PANEL_WIDTH,
) -> tuple[int, int]:
    lines = text.splitlines() or [text]
    available_width = max(_MIN_PANEL_WIDTH, max_panel_width)
    if screen_bounds is not None:
        available_width = min(available_width, screen_bounds.width)

    estimated_text_width = max(_estimated_line_width(line) for line in lines)
    width = max(
        anchor.width,
        _MIN_PANEL_WIDTH,
        min(estimated_text_width, available_width),
    )
    wrapped_line_count = sum(_wrapped_line_count(line, width) for line in lines)
    height = max(
        anchor.height,
        wrapped_line_count * _ESTIMATED_LINE_HEIGHT + _PANEL_VERTICAL_PADDING,
    )

    if screen_bounds is not None:
        width = min(width, screen_bounds.width)
        height = min(height, screen_bounds.height)
    return width, height


def stack_overlay_items(
    items: list[OverlayItem],
    screen_bounds: ScreenRegion | None,
) -> list[OverlayItem]:
    if len(items) < 2:
        return items

    stacked: list[OverlayItem] = []
    for item in items:
        region = item.region
        if stacked:
            minimum_y = stacked[-1].region.bottom + _PANEL_VERTICAL_GAP
            if region.y < minimum_y:
                region = ScreenRegion(
                    x=region.x,
                    y=minimum_y,
                    width=region.width,
                    height=region.height,
                )
        stacked.append(OverlayItem(text=item.text, region=region))

    if screen_bounds is None:
        return stacked

    overflow = stacked[-1].region.bottom - screen_bounds.bottom
    if overflow > 0:
        available_shift = min(item.region.y for item in stacked) - screen_bounds.y
        shift = min(overflow, max(0, available_shift))
        if shift > 0:
            stacked = [
                OverlayItem(
                    text=item.text,
                    region=ScreenRegion(
                        x=item.region.x,
                        y=item.region.y - shift,
                        width=item.region.width,
                        height=item.region.height,
                    ),
                )
                for item in stacked
            ]

    return [
        OverlayItem(text=item.text, region=_clamp_region(item.region, screen_bounds))
        for item in stacked
    ]


def _estimated_line_width(line: str) -> int:
    return (len(line) * _ESTIMATED_CHAR_WIDTH) + _PANEL_HORIZONTAL_PADDING


def _wrapped_line_count(line: str, width: int) -> int:
    usable_width = max(1, width - _PANEL_HORIZONTAL_PADDING)
    max_chars_per_line = max(1, usable_width // _ESTIMATED_CHAR_WIDTH)
    return max(1, (len(line) + max_chars_per_line - 1) // max_chars_per_line)


def _clamp_region(region: ScreenRegion, bounds: ScreenRegion) -> ScreenRegion:
    width = min(region.width, bounds.width)
    height = min(region.height, bounds.height)
    x = min(max(region.x, bounds.x), bounds.right - width)
    y = min(max(region.y, bounds.y), bounds.bottom - height)
    return ScreenRegion(x=x, y=y, width=width, height=height)
