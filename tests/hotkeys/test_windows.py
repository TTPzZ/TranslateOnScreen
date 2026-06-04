from __future__ import annotations

import pytest

from screen_translator.hotkeys.windows import (
    DEFAULT_HOTKEY,
    MOD_CONTROL,
    MOD_SHIFT,
    VK_ESCAPE,
    VK_T,
    WM_HOTKEY,
    HotkeyRegistrationError,
    WindowsGlobalHotkey,
    hotkey_spec_from_text,
)


class FakeUser32:
    def __init__(self, register_result: int = 1) -> None:
        self.register_result = register_result
        self.register_calls: list[tuple[int, int, int, int]] = []
        self.unregister_calls: list[tuple[int, int]] = []

    def RegisterHotKey(self, hwnd: int, hotkey_id: int, modifiers: int, key_code: int) -> int:
        self.register_calls.append((hwnd, hotkey_id, modifiers, key_code))
        return self.register_result

    def UnregisterHotKey(self, hwnd: int, hotkey_id: int) -> int:
        self.unregister_calls.append((hwnd, hotkey_id))
        return 1


def test_default_hotkey_is_ctrl_shift_t() -> None:
    assert DEFAULT_HOTKEY.modifiers == MOD_CONTROL | MOD_SHIFT
    assert DEFAULT_HOTKEY.key_code == VK_T


def test_hotkey_spec_from_text_supports_escape_and_letter_keys() -> None:
    escape = hotkey_spec_from_text("Esc", identifier=2)
    letter = hotkey_spec_from_text("Q", identifier=2)

    assert escape.modifiers == 0
    assert escape.key_code == VK_ESCAPE
    assert escape.identifier == 2
    assert escape.label == "Esc"
    assert letter.modifiers == 0
    assert letter.key_code == ord("Q")
    assert letter.identifier == 2
    assert letter.label == "Q"


def test_windows_hotkey_registers_and_unregisters_default_hotkey() -> None:
    user32 = FakeUser32()
    manager = WindowsGlobalHotkey(callback=lambda: None, user32=user32)

    manager.register()
    manager.unregister()

    assert user32.register_calls == [(0, DEFAULT_HOTKEY.identifier, MOD_CONTROL | MOD_SHIFT, VK_T)]
    assert user32.unregister_calls == [(0, DEFAULT_HOTKEY.identifier)]


def test_windows_hotkey_logs_registration_success(caplog) -> None:
    user32 = FakeUser32()
    manager = WindowsGlobalHotkey(callback=lambda: None, user32=user32)

    with caplog.at_level("INFO", logger="screen_translator.hotkeys.windows"):
        manager.register()

    assert "hotkey registration succeeded key=Ctrl+Shift+T" in caplog.text


def test_windows_hotkey_raises_when_registration_fails() -> None:
    manager = WindowsGlobalHotkey(callback=lambda: None, user32=FakeUser32(register_result=0))

    with pytest.raises(HotkeyRegistrationError, match="Unable to register global hotkey"):
        manager.register()


def test_windows_hotkey_logs_registration_failure(caplog) -> None:
    manager = WindowsGlobalHotkey(callback=lambda: None, user32=FakeUser32(register_result=0))

    with caplog.at_level("ERROR", logger="screen_translator.hotkeys.windows"):
        with pytest.raises(HotkeyRegistrationError, match="Unable to register global hotkey"):
            manager.register()

    assert "hotkey registration failed key=Ctrl+Shift+T" in caplog.text


def test_windows_hotkey_dispatches_matching_message() -> None:
    calls: list[str] = []
    manager = WindowsGlobalHotkey(callback=lambda: calls.append("called"), user32=FakeUser32())

    handled = manager.dispatch_message(WM_HOTKEY, DEFAULT_HOTKEY.identifier)

    assert handled is True
    assert calls == ["called"]


def test_windows_hotkey_logs_press(caplog) -> None:
    manager = WindowsGlobalHotkey(callback=lambda: None, user32=FakeUser32())

    with caplog.at_level("INFO", logger="screen_translator.hotkeys.windows"):
        assert manager.dispatch_message(WM_HOTKEY, DEFAULT_HOTKEY.identifier) is True

    assert "hotkey pressed key=Ctrl+Shift+T" in caplog.text


def test_windows_hotkey_message_loop_unregisters_on_quit_message() -> None:
    class QuitUser32(FakeUser32):
        def GetMessageW(self, message: object, hwnd: int, min_filter: int, max_filter: int) -> int:
            del message, hwnd, min_filter, max_filter
            return 0

    user32 = QuitUser32()
    manager = WindowsGlobalHotkey(callback=lambda: None, user32=user32)

    manager.run_message_loop()

    assert user32.register_calls == [(0, DEFAULT_HOTKEY.identifier, MOD_CONTROL | MOD_SHIFT, VK_T)]
    assert user32.unregister_calls == [(0, DEFAULT_HOTKEY.identifier)]
