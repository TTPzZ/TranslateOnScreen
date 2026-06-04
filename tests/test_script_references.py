from __future__ import annotations

from pathlib import Path


def test_windows_smoke_scripts_exist_and_use_python_launcher() -> None:
    scripts = [
        "setup_dev.ps1",
        "run_server.ps1",
        "run_control_panel.ps1",
        "run_tests.ps1",
        "clean.ps1",
        "diagnose.ps1",
    ]

    for script in scripts:
        path = Path("scripts") / script
        assert path.exists(), f"missing {path}"
        content = path.read_text(encoding="utf-8")
        if script == "run_control_panel.ps1":
            assert "$env:VIRTUAL_ENV" in content
            assert ".venv311" in content
            assert ".venv" in content
            assert "Using Python" in content
            assert "Exit code" in content
        else:
            assert "py " in content or "py.exe" in content


def test_control_app_module_invokes_main_and_reports_event_loop() -> None:
    content = Path("src/screen_translator/control_app.py").read_text(encoding="utf-8")

    assert 'if __name__ == "__main__":' in content
    assert "raise SystemExit(main())" in content
    assert "Python executable:" in content
    assert "PyQt6 loaded:" in content
    assert "Entering Qt event loop" in content
    assert "Qt event loop exit code:" in content
    assert "traceback.print_exc()" in content


def test_diagnostics_module_invokes_main() -> None:
    content = Path("src/screen_translator/diagnostics.py").read_text(encoding="utf-8")

    assert 'if __name__ == "__main__":' in content
    assert "main()" in content


def test_manual_docs_reference_required_scripts() -> None:
    manual = Path("MANUAL_TEST_WINDOWS.md").read_text(encoding="utf-8")
    troubleshooting = Path("TROUBLESHOOTING.md").read_text(encoding="utf-8")

    for script in [
        "scripts/setup_dev.ps1",
        "scripts/run_server.ps1",
        "scripts/run_control_panel.ps1",
        "scripts/diagnose.ps1",
    ]:
        assert script in manual
    assert "PyQt6 missing" in troubleshooting
    assert "Google credentials missing" in troubleshooting


def test_mock_provider_smoke_test_is_documented() -> None:
    for path in [
        Path("README.md"),
        Path("VALIDATION.md"),
        Path("MANUAL_TEST_WINDOWS.md"),
        Path("TROUBLESHOOTING.md"),
    ]:
        content = path.read_text(encoding="utf-8")
        assert 'TRANSLATION_PROVIDERS = "mock"' in content
        assert 'TRANSLATION_PROVIDER = "mock"' in content
        assert "Xin chào thế giới" in content
