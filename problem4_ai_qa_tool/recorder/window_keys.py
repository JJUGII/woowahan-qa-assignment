"""Window-local A/C scan-code handling for Windows IME; no global key hook."""
import ctypes
from ctypes import wintypes
import os
import queue


def mode_from_message(message, lparam, *, modified=False):
    if message not in (0x0100, 0x0290) or modified or (lparam & (1 << 30)):
        return None
    return {0x1E:'ASSERT', 0x2E:'CLICK'}.get((lparam >> 16) & 0xFF)


class WindowModeKeys:
    def __init__(self, title):
        self.events = queue.SimpleQueue()
        self.originals = {}
        self.callback = None
        self.active = False
        if os.name != 'nt':
            return
        try:
            self.user = ctypes.WinDLL('user32', use_last_error=True)
            self.user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            self.user.FindWindowW.restype = wintypes.HWND
            self.user.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
            self.user.FindWindowExW.restype = wintypes.HWND
            self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            self.user.GetKeyState.argtypes = [ctypes.c_int]
            self.user.GetKeyState.restype = ctypes.c_short
            self.user.IsWindow.argtypes = [wintypes.HWND]
            self.get_proc = getattr(self.user, 'GetWindowLongPtrW' if ctypes.sizeof(ctypes.c_void_p)==8 else 'GetWindowLongW')
            self.set_proc = getattr(self.user, 'SetWindowLongPtrW' if ctypes.sizeof(ctypes.c_void_p)==8 else 'SetWindowLongW')
            self.get_proc.argtypes = [wintypes.HWND, ctypes.c_int]
            self.get_proc.restype = ctypes.c_ssize_t
            self.set_proc.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            self.set_proc.restype = ctypes.c_ssize_t
            self.user.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            self.user.CallWindowProcW.restype = ctypes.c_ssize_t
            frame = self.user.FindWindowW('Main HighGUI class', title)
            if not frame:
                return
            pid = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(frame, ctypes.byref(pid))
            if pid.value != os.getpid():
                return
            child = self.user.FindWindowExW(frame, None, 'HighGUI class', None)
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                               wintypes.WPARAM, wintypes.LPARAM)
            def on_message(hwnd, message, wparam, lparam):
                try:
                    modified = bool(self.user.GetKeyState(0x11) & 0x8000 or self.user.GetKeyState(0x12) & 0x8000)
                    mode = mode_from_message(message, lparam, modified=modified)
                    if mode:
                        self.events.put(mode)
                except Exception:
                    pass  # Never allow a Python exception to cross a native window callback.
                return self.user.CallWindowProcW(self.originals[hwnd], hwnd, message, wparam, lparam)
            self.callback = callback_type(on_message)
            self.callback_address = ctypes.cast(self.callback, ctypes.c_void_p).value
            for hwnd in filter(None, (frame, child)):
                self.originals[hwnd] = self.get_proc(hwnd, -4)
                ctypes.set_last_error(0)
                if not self.set_proc(hwnd, -4, self.callback_address) and ctypes.get_last_error():
                    self.originals.pop(hwnd)
                    raise OSError('Cannot install window-local shortcut handler')
            self.active = bool(child)
        except (OSError, AttributeError):
            self.close()

    def take(self):
        latest = None
        while not self.events.empty():
            latest = self.events.get()
        return latest

    def close(self):
        for hwnd, original in list(self.originals.items()):
            if self.user.IsWindow(hwnd) and self.get_proc(hwnd, -4) == self.callback_address:
                self.set_proc(hwnd, -4, original)
        self.originals.clear()
        self.active = False
