from __future__ import annotations

from screen_translator.domain.models import ScreenRegion
from screen_translator.region.selection import SelectionPolicy, region_from_drag


def test_region_from_drag_normalizes_reverse_drag() -> None:
    region = region_from_drag(
        start=(300, 220),
        end=(100, 80),
        policy=SelectionPolicy(min_width=20, min_height=20),
    )

    assert region == ScreenRegion(x=100, y=80, width=200, height=140)


def test_region_from_drag_rejects_small_drag() -> None:
    region = region_from_drag(
        start=(10, 10),
        end=(18, 25),
        policy=SelectionPolicy(min_width=20, min_height=20),
    )

    assert region is None


def test_region_from_drag_clips_to_screen_bounds() -> None:
    bounds = ScreenRegion(x=0, y=0, width=1920, height=1080)

    region = region_from_drag(
        start=(-10, 50),
        end=(120, 90),
        policy=SelectionPolicy(min_width=20, min_height=20),
        screen_bounds=bounds,
    )

    assert region == ScreenRegion(x=0, y=50, width=120, height=40)
