from __future__ import annotations

from dataclasses import dataclass

from screen_translator.domain.models import ScreenRegion

Point = tuple[int, int]


@dataclass(frozen=True, slots=True)
class SelectionPolicy:
    """Constraints for user-created region selections."""

    min_width: int = 20
    min_height: int = 20


def region_from_drag(
    start: Point,
    end: Point,
    policy: SelectionPolicy,
    screen_bounds: ScreenRegion | None = None,
) -> ScreenRegion | None:
    left = min(start[0], end[0])
    top = min(start[1], end[1])
    right = max(start[0], end[0])
    bottom = max(start[1], end[1])

    if right - left < policy.min_width or bottom - top < policy.min_height:
        return None

    region = ScreenRegion(x=left, y=top, width=right - left, height=bottom - top)
    if screen_bounds is None:
        return region

    try:
        clipped = region.clip_to(screen_bounds)
    except ValueError:
        return None

    if clipped.width < policy.min_width or clipped.height < policy.min_height:
        return None
    return clipped
