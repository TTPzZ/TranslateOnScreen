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
    zone_id: str | None = None
    style: str = "floating_panel"
    font_size: int | None = None
    padding: int | None = None
    overflow: bool = False


@dataclass(frozen=True, slots=True)
class InlineTextLayout:
    """Deterministic inline text placement and fitting result."""

    region: ScreenRegion
    font_size: int
    overflow: bool = False


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
    overlay_style: str = "floating_panel",
    zone_id: str | None = None,
    inline_min_font_size: int = 8,
    inline_max_font_size: int = 22,
    inline_padding: int = 6,
    inline_allow_expand_ratio: float = 1.5,
) -> list[OverlayItem]:
    if len(ocr_blocks) != len(translations):
        raise ValueError("translations count must match OCR blocks")
    if overlay_style not in {"floating_panel", "inline_replace"}:
        raise ValueError(f"Unsupported overlay style: {overlay_style}")

    items: list[OverlayItem] = []
    for block, translation in zip(ocr_blocks, translations, strict=True):
        text = translation.strip()
        if not text:
            continue

        if overlay_style == "inline_replace":
            if selected_region is None:
                raise ValueError("selected_region is required for inline_replace")
            inline_layout = fit_inline_text(
                text,
                block.region,
                zone_region=selected_region,
                screen_bounds=screen_bounds,
                min_font_size=inline_min_font_size,
                max_font_size=inline_max_font_size,
                padding=inline_padding,
                allow_expand_ratio=inline_allow_expand_ratio,
            )
            items.append(
                OverlayItem(
                    text=text,
                    region=inline_layout.region,
                    zone_id=zone_id,
                    style="inline_replace",
                    font_size=inline_layout.font_size,
                    padding=inline_padding,
                    overflow=inline_layout.overflow,
                )
            )
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
        items.append(
            OverlayItem(
                text=text,
                region=region,
                zone_id=zone_id,
                style="floating_panel",
            )
        )
    if selected_region is not None and overlay_style == "floating_panel":
        items = stack_overlay_items(items, screen_bounds)
    return items


def fit_inline_text(
    text: str,
    ocr_region: ScreenRegion,
    *,
    zone_region: ScreenRegion,
    screen_bounds: ScreenRegion | None,
    min_font_size: int,
    max_font_size: int,
    padding: int,
    allow_expand_ratio: float,
) -> InlineTextLayout:
    if min_font_size <= 0:
        raise ValueError("min_font_size must be positive")
    if max_font_size < min_font_size:
        raise ValueError("max_font_size must be >= min_font_size")
    if padding < 0:
        raise ValueError("padding must not be negative")
    if allow_expand_ratio < 1.0:
        raise ValueError("allow_expand_ratio must be at least 1.0")

    anchor = ScreenRegion(
        x=zone_region.x + ocr_region.x,
        y=zone_region.y + ocr_region.y,
        width=ocr_region.width,
        height=ocr_region.height,
    )
    bounds = _inline_bounds(zone_region, screen_bounds)
    region = _clamp_region(anchor, bounds)

    for font_size in range(max_font_size, min_font_size - 1, -1):
        if _inline_text_fits(text, region.width, region.height, font_size, padding):
            return InlineTextLayout(region=region, font_size=font_size, overflow=False)

    expanded_height = min(
        bounds.height,
        max(region.height, int(round(ocr_region.height * allow_expand_ratio))),
    )
    expanded = _clamp_region(
        ScreenRegion(region.x, region.y, region.width, expanded_height),
        bounds,
    )
    if _inline_text_fits(text, expanded.width, expanded.height, min_font_size, padding):
        return InlineTextLayout(region=expanded, font_size=min_font_size, overflow=False)
    return InlineTextLayout(region=expanded, font_size=min_font_size, overflow=True)


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
        stacked.append(_copy_overlay_item(item, region=region))

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
                    zone_id=item.zone_id,
                    style=item.style,
                    font_size=item.font_size,
                    padding=item.padding,
                    overflow=item.overflow,
                )
                for item in stacked
            ]

    return [
        _copy_overlay_item(item, region=_clamp_region(item.region, screen_bounds))
        for item in stacked
    ]


def _inline_bounds(
    zone_region: ScreenRegion,
    screen_bounds: ScreenRegion | None,
) -> ScreenRegion:
    if screen_bounds is None:
        return zone_region
    try:
        return zone_region.clip_to(screen_bounds)
    except ValueError:
        return screen_bounds


def _inline_text_fits(
    text: str,
    width: int,
    height: int,
    font_size: int,
    padding: int,
) -> bool:
    usable_width = max(1, width - (padding * 2))
    estimated_char_width = max(1, round(font_size * 0.55))
    max_chars_per_line = max(1, usable_width // estimated_char_width)
    line_count = 0
    for paragraph in text.splitlines() or [text]:
        line_count += _wrapped_word_line_count(paragraph, max_chars_per_line)
    return line_count * font_size <= height


def _wrapped_word_line_count(text: str, max_chars_per_line: int) -> int:
    words = text.split()
    if not words:
        return 1
    line_count = 1
    current_length = 0
    for word in words:
        word_length = len(word)
        if current_length == 0:
            current_length = word_length
            continue
        if current_length + 1 + word_length <= max_chars_per_line:
            current_length += 1 + word_length
            continue
        line_count += max(1, (current_length + max_chars_per_line - 1) // max_chars_per_line)
        current_length = word_length
    if current_length > max_chars_per_line:
        line_count += (current_length + max_chars_per_line - 1) // max_chars_per_line - 1
    return line_count


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


def _copy_overlay_item(item: OverlayItem, *, region: ScreenRegion) -> OverlayItem:
    return OverlayItem(
        text=item.text,
        region=region,
        zone_id=item.zone_id,
        style=item.style,
        font_size=item.font_size,
        padding=item.padding,
        overflow=item.overflow,
    )
