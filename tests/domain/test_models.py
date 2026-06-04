from __future__ import annotations

import pytest

from screen_translator.domain.models import ScreenRegion


def test_screen_region_exposes_edges_and_tuple() -> None:
    region = ScreenRegion(x=10, y=20, width=300, height=150)

    assert region.right == 310
    assert region.bottom == 170
    assert region.as_tuple() == (10, 20, 300, 150)


def test_screen_region_rejects_non_positive_dimensions() -> None:
    with pytest.raises(ValueError, match="width and height must be positive"):
        ScreenRegion(x=0, y=0, width=0, height=10)


def test_screen_region_clips_to_bounds() -> None:
    bounds = ScreenRegion(x=0, y=0, width=1920, height=1080)
    region = ScreenRegion(x=-20, y=40, width=140, height=80)

    assert region.clip_to(bounds) == ScreenRegion(x=0, y=40, width=120, height=80)
