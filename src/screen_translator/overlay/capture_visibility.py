from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from screen_translator.domain.models import ScreenRegion


CAPTURE_REGION_ATTR = "_screen_translator_capture_region"


def set_capture_region(widget: Any, region: ScreenRegion) -> None:
    setattr(widget, CAPTURE_REGION_ATTR, region)


def hide_intersecting_widgets(
    widgets: Iterable[Any],
    capture_regions: Sequence[ScreenRegion],
) -> tuple[list[Any], int, int]:
    widget_list = list(widgets)
    regions = tuple(capture_regions)
    if not regions:
        return ([], 0, len(widget_list))

    hidden: list[Any] = []
    skipped_count = 0
    for widget in widget_list:
        region = getattr(widget, CAPTURE_REGION_ATTR, None)
        intersects = region is None or any(_regions_intersect(region, capture) for capture in regions)
        if not intersects:
            skipped_count += 1
            continue
        hide = getattr(widget, "hide", None)
        if callable(hide):
            hide()
            hidden.append(widget)
            continue
        skipped_count += 1
    return (hidden, len(hidden), skipped_count)


def restore_widgets(widgets: Iterable[Any]) -> None:
    for widget in widgets:
        show = getattr(widget, "show", None)
        if callable(show):
            show()


def _regions_intersect(first: ScreenRegion, second: ScreenRegion) -> bool:
    return (
        first.x < second.right
        and first.right > second.x
        and first.y < second.bottom
        and first.bottom > second.y
    )
