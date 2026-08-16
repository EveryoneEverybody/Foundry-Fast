"""Small native Windows viewer for Foundry's redirected output.

This script intentionally uses only ctypes and the Python standard library so it
can run under Blender's bundled pythonw.exe without adding another dependency.
"""

import argparse
import codecs
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re


WM_CREATE = 0x0001
WM_DESTROY = 0x0002
WM_SIZE = 0x0005
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_SETFONT = 0x0030
WM_COPY = 0x0301
EM_SETSEL = 0x00B1
EM_SCROLLCARET = 0x00B7
EM_SETLIMITTEXT = 0x00C5

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_VSCROLL = 0x00200000
WS_HSCROLL = 0x00100000
WS_TABSTOP = 0x00010000
WS_EX_CLIENTEDGE = 0x00000200
ES_MULTILINE = 0x0004
ES_AUTOVSCROLL = 0x0040
ES_AUTOHSCROLL = 0x0080
ES_READONLY = 0x0800
BS_PUSHBUTTON = 0x00000000
SW_SHOW = 5
CW_USEDEFAULT = -2147483648
COLOR_WINDOW = 5
DEFAULT_CHARSET = 1
FIXED_PITCH = 1
FF_MODERN = 48
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259

BUTTON_CLEAR = 1001
BUTTON_COPY = 1002
TIMER_ID = 1
MAX_DISPLAY_CHARACTERS = 2_000_000

ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.LoadCursorW.restype = wintypes.HANDLE
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.OpenProcess.restype = wintypes.HANDLE
gdi32.CreateFontW.restype = wintypes.HFONT


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p, wintypes.HINSTANCE, ctypes.c_void_p]
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
gdi32.CreateFontW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR]
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]


class TailSource:
    def __init__(self, path, label=""):
        self.path = Path(path)
        self.label = label
        self.position = 0
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def read_new(self):
        try:
            size = self.path.stat().st_size
            if size < self.position:
                self.position = 0
                self.decoder.reset()
            if size == self.position:
                return ""
            with open(self.path, "rb") as stream:
                stream.seek(self.position)
                data = stream.read()
                self.position = stream.tell()
        except OSError:
            return ""
        return self.decoder.decode(data, final=False)


class OutputSources:
    def __init__(self, log_path, watch_path):
        primary_path = str(Path(log_path).resolve())
        primary_source = TailSource(primary_path, "Foundry")
        self.sources = [primary_source]
        self.source_by_path = {primary_path: primary_source}
        self.watch_path = Path(watch_path)
        self.watch_position = 0
        self.watch_remainder = ""

    def _load_watched_sources(self):
        try:
            size = self.watch_path.stat().st_size
            if size < self.watch_position:
                self.watch_position = 0
                self.watch_remainder = ""
            if size == self.watch_position:
                return
            with open(self.watch_path, "r", encoding="utf-8", errors="replace") as stream:
                stream.seek(self.watch_position)
                text = self.watch_remainder + stream.read()
                self.watch_position = stream.tell()
        except OSError:
            return

        lines = text.split("\n")
        self.watch_remainder = lines.pop()
        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                path = str(Path(entry["path"]).resolve())
            except (KeyError, TypeError, ValueError, OSError):
                continue
            source = self.source_by_path.get(path)
            if source is not None:
                source.position = 0
                source.decoder.reset()
                source.label = str(entry.get("label") or Path(path).name)
                continue
            source = TailSource(path, str(entry.get("label") or Path(path).name))
            self.sources.append(source)
            self.source_by_path[path] = source

    def read_new(self):
        self._load_watched_sources()
        chunks = []
        for source in self.sources:
            text = source.read_new()
            if text:
                chunks.append((source.label, text))
        return chunks


class TerminalText:
    def __init__(self):
        self.lines = []
        self.current_line = ""
        self.pending_carriage_return = False
        self.last_source = ""

    def clear(self):
        self.lines.clear()
        self.current_line = ""
        self.pending_carriage_return = False
        self.last_source = ""

    def feed(self, text, source=""):
        text = ANSI_ESCAPE.sub("", text)
        if source and source != self.last_source:
            if self.lines or self.current_line:
                self._newline()
            self.current_line += f"[{source}]"
            self._newline()
            self.last_source = source

        index = 0
        while index < len(text):
            character = text[index]
            if self.pending_carriage_return:
                self.pending_carriage_return = False
                if character == "\n":
                    self._newline()
                    index += 1
                    continue
                self.current_line = ""

            if character == "\f":
                self.clear()
            elif character == "\r":
                self.pending_carriage_return = True
            elif character == "\n":
                self._newline()
            elif character == "\b":
                self.current_line = self.current_line[:-1]
            elif character != "\x00":
                self.current_line += character
            index += 1
        self._trim()

    def _newline(self):
        self.lines.append(self.current_line)
        self.current_line = ""

    def _trim(self):
        total = sum(len(line) + 2 for line in self.lines) + len(self.current_line)
        if total <= MAX_DISPLAY_CHARACTERS:
            return
        target = MAX_DISPLAY_CHARACTERS * 3 // 4
        while self.lines and total > target:
            total -= len(self.lines.pop(0)) + 2
        self.lines.insert(0, "[Earlier output trimmed]")

    def render(self):
        return "\r\n".join((*self.lines, self.current_line))


class FoundryOutputWindow:
    def __init__(self, arguments):
        self.arguments = arguments
        self.sources = OutputSources(arguments.log, arguments.watch)
        self.terminal = TerminalText()
        self.hwnd = None
        self.edit = None
        self.clear_button = None
        self.copy_button = None
        self.font = None
        self.window_proc = WNDPROC(self._window_proc)

    def _parent_is_alive(self):
        process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, self.arguments.parent_pid)
        if not process:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(process)

    def _create_controls(self, hwnd):
        self.edit = user32.CreateWindowExW(
            WS_EX_CLIENTEDGE,
            "EDIT",
            "",
            WS_CHILD | WS_VISIBLE | WS_VSCROLL | WS_HSCROLL | ES_MULTILINE | ES_AUTOVSCROLL | ES_AUTOHSCROLL | ES_READONLY,
            8,
            8,
            780,
            520,
            hwnd,
            None,
            None,
            None,
        )
        user32.SendMessageW(self.edit, EM_SETLIMITTEXT, MAX_DISPLAY_CHARACTERS, 0)
        self.clear_button = user32.CreateWindowExW(
            0,
            "BUTTON",
            "Clear",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
            8,
            536,
            90,
            28,
            hwnd,
            BUTTON_CLEAR,
            None,
            None,
        )
        self.copy_button = user32.CreateWindowExW(
            0,
            "BUTTON",
            "Copy All",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
            106,
            536,
            90,
            28,
            hwnd,
            BUTTON_COPY,
            None,
            None,
        )
        self.font = gdi32.CreateFontW(
            -16,
            0,
            0,
            0,
            400,
            False,
            False,
            False,
            DEFAULT_CHARSET,
            0,
            0,
            0,
            FIXED_PITCH | FF_MODERN,
            "Consolas",
        )
        user32.SendMessageW(self.edit, WM_SETFONT, self.font, True)
        user32.SendMessageW(self.clear_button, WM_SETFONT, self.font, True)
        user32.SendMessageW(self.copy_button, WM_SETFONT, self.font, True)
        user32.SetTimer(hwnd, TIMER_ID, 100, None)

    def _resize_controls(self, width, height):
        button_height = 30
        margin = 8
        edit_height = max(80, height - button_height - margin * 3)
        user32.MoveWindow(self.edit, margin, margin, max(100, width - margin * 2), edit_height, True)
        user32.MoveWindow(self.clear_button, margin, edit_height + margin * 2, 90, button_height, True)
        user32.MoveWindow(self.copy_button, margin + 98, edit_height + margin * 2, 90, button_height, True)

    def _update_output(self):
        chunks = self.sources.read_new()
        if not chunks:
            return
        for source, text in chunks:
            self.terminal.feed(text, source)
        rendered = self.terminal.render()
        user32.SetWindowTextW(self.edit, rendered)
        user32.SendMessageW(self.edit, EM_SETSEL, len(rendered), len(rendered))
        user32.SendMessageW(self.edit, EM_SCROLLCARET, 0, 0)

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == WM_CREATE:
            self.hwnd = hwnd
            self._create_controls(hwnd)
            return 0
        if message == WM_SIZE:
            self._resize_controls(lparam & 0xFFFF, (lparam >> 16) & 0xFFFF)
            return 0
        if message == WM_COMMAND:
            command = wparam & 0xFFFF
            if command == BUTTON_CLEAR:
                self.terminal.clear()
                user32.SetWindowTextW(self.edit, "")
                return 0
            if command == BUTTON_COPY:
                user32.SendMessageW(self.edit, EM_SETSEL, 0, -1)
                user32.SendMessageW(self.edit, WM_COPY, 0, 0)
                return 0
        if message == WM_TIMER and wparam == TIMER_ID:
            if not self._parent_is_alive():
                user32.DestroyWindow(hwnd)
                return 0
            self._update_output()
            return 0
        if message == WM_DESTROY:
            user32.KillTimer(hwnd, TIMER_ID)
            if self.font:
                gdi32.DeleteObject(self.font)
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def run(self):
        instance = kernel32.GetModuleHandleW(None)
        class_name = f"FoundryOutputWindow{self.arguments.parent_pid}"
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = ctypes.cast(self.window_proc, ctypes.c_void_p).value
        window_class.hInstance = instance
        window_class.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(32512))
        window_class.hbrBackground = COLOR_WINDOW + 1
        window_class.lpszClassName = class_name
        if not user32.RegisterClassW(ctypes.byref(window_class)):
            return 1

        self.hwnd = user32.CreateWindowExW(
            0,
            class_name,
            self.arguments.title,
            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            900,
            650,
            None,
            None,
            instance,
            None,
        )
        if not self.hwnd:
            return 1
        user32.ShowWindow(self.hwnd, SW_SHOW)
        user32.UpdateWindow(self.hwnd)

        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        return int(message.wParam)


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--watch", required=True)
    parser.add_argument("--parent-pid", required=True, type=int)
    parser.add_argument("--title", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(FoundryOutputWindow(parse_arguments()).run())
