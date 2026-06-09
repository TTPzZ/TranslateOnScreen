from __future__ import annotations

import subprocess
import sys
import tomllib
import os

from screen_translator.ocr import windows_provider


def test_windows_ocr_diagnostic_reports_missing_package(monkeypatch) -> None:
    monkeypatch.setattr(
        windows_provider,
        "windows_ocr_availability",
        lambda: (False, "windows_ocr_binding_unavailable:ModuleNotFoundError"),
    )
    monkeypatch.setattr(windows_provider, "_installed_package_version", lambda _name: None)

    report = windows_provider.format_windows_ocr_diagnostic()

    assert "status=unavailable" in report
    assert "module=winrt.windows.media.ocr" in report
    assert "package=winrt-Windows.Media.Ocr" in report
    assert "reason=windows_ocr_binding_unavailable:ModuleNotFoundError" in report
    assert 'python -m pip install "winrt-Windows.Media.Ocr>=3.2.1"' in report


def test_windows_ocr_module_diagnose_command_runs() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "screen_translator.ocr.windows_provider",
            "--diagnose",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 0
    assert "Windows OCR diagnostic" in completed.stdout
    assert "module=winrt.windows.media.ocr" in completed.stdout


def test_pyproject_exposes_windows_ocr_optional_extra() -> None:
    with open("pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)

    windows_ocr = pyproject["project"]["optional-dependencies"]["windows-ocr"]

    assert any("winrt-Windows.Media.Ocr" in dependency for dependency in windows_ocr)
