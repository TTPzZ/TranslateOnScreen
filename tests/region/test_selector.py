from __future__ import annotations

import sys

import pytest

from screen_translator.region.selector import QtRegionSelector, RegionSelectorError


def test_qt_region_selector_reports_missing_pyqt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "PyQt6", None)

    with pytest.raises(RegionSelectorError, match="PyQt6 is required"):
        QtRegionSelector().select_region()
