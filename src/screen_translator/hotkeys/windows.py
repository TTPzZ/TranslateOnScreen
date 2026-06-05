from __future__ import annotations

import ctypes
import logging
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
VK_ESCAPE = 0x1B
VK_T = 0x54
WM_HOTKEY = 0x0312
HOTKEY_LABEL = "Ctrl+Shift+T"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HotkeySpec:
    """Win32 hotkey definition."""

    modifiers: int
    key_code: int
    identifier: int = 1
    label: str = HOTKEY_LABEL


DEFAULT_HOTKEY = HotkeySpec(modifiers=MOD_CONTROL | MOD_SHIFT, key_code=VK_T)


class HotkeyRegistrationError(RuntimeError):
    """Raised when a global hotkey cannot be registered."""


class WindowsGlobalHotkey:
    """Global hotkey lifecycle wrapper for Windows."""

    def __init__(
        self,
        callback: Callable[[], None],
        *,
        spec: HotkeySpec = DEFAULT_HOTKEY,
        user32: Any | None = None,
    ) -> None:
        self._callback = callback
        self._spec = spec
        self._label = spec.label
        self._user32 = user32 or _default_user32()
        self._registered = False
        self._running = False

    def register(self) -> None:
        if self._registered:
            return

        result = self._user32.RegisterHotKey(
            0,
            self._spec.identifier,
            self._spec.modifiers,
            self._spec.key_code,
        )
        if not result:
            logger.error("hotkey registration failed key=%s", self._label)
            raise HotkeyRegistrationError(f"Unable to register global hotkey {self._label}")
        self._registered = True
        logger.info("hotkey registration succeeded key=%s", self._label)

    def unregister(self) -> None:
        if not self._registered:
            return

        self._user32.UnregisterHotKey(0, self._spec.identifier)
        self._registered = False

    def dispatch_message(self, message: int, w_param: int) -> bool:
        if message != WM_HOTKEY or w_param != self._spec.identifier:
            return False
        logger.info("hotkey pressed key=%s", self._label)
        self._callback()
        return True

    def run_message_loop(self) -> None:
        self.register()
        self._running = True
        logger.info("hotkey message pump started key=%s", self._label)
        msg = wintypes.MSG()

        try:
            while self._running:
                result = self._user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    logger.error("hotkey message pump failed key=%s", self._label)
                    raise HotkeyRegistrationError("Windows hotkey message loop failed")
                self.dispatch_message(int(msg.message), int(msg.wParam))
        finally:
            logger.info("hotkey message pump stopped key=%s", self._label)
            self.unregister()

    def stop(self) -> None:
        self._running = False


def _default_user32() -> Any:
    try:
        return ctypes.windll.user32
    except AttributeError as exc:
        raise HotkeyRegistrationError("Windows global hotkeys require Win32 user32") from exc


def hotkey_spec_from_text(text: str, *, identifier: int) -> HotkeySpec:
    """Parse a small Win32 hotkey string such as Esc, Q, or Ctrl+Shift+T."""

    raw = text.strip()
    if not raw:
        raise HotkeyRegistrationError("Hotkey cannot be empty")

    parts = [part.strip() for part in raw.split("+") if part.strip()]
    if not parts:
        raise HotkeyRegistrationError("Hotkey cannot be empty")

    modifiers = 0
    label_parts: list[str] = []
    for modifier in parts[:-1]:
        normalized = modifier.lower()
        if normalized in {"ctrl", "control"}:
            modifiers |= MOD_CONTROL
            label_parts.append("Ctrl")
        elif normalized == "shift":
            modifiers |= MOD_SHIFT
            label_parts.append("Shift")
        elif normalized == "alt":
            modifiers |= MOD_ALT
            label_parts.append("Alt")
        elif normalized in {"win", "windows"}:
            modifiers |= MOD_WIN
            label_parts.append("Win")
        else:
            raise HotkeyRegistrationError(f"Unsupported hotkey modifier {modifier!r}")

    key_label, key_code = _parse_key(parts[-1])
    label_parts.append(key_label)
    return HotkeySpec(
        modifiers=modifiers,
        key_code=key_code,
        identifier=identifier,
        label="+".join(label_parts),
    )


def _parse_key(token: str) -> tuple[str, int]:
    normalized = token.strip().lower()
    if normalized in {"esc", "escape"}:
        return "Esc", VK_ESCAPE
    if normalized.startswith("f") and normalized[1:].isdigit():
        index = int(normalized[1:])
        if 1 <= index <= 24:
            return f"F{index}", 0x6F + index
    if len(token) == 1 and token.isalpha():
        label = token.upper()
        return label, ord(label)
    raise HotkeyRegistrationError(f"Unsupported hotkey key {token!r}")
