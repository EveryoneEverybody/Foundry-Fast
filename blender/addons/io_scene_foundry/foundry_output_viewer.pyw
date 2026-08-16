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
import time
import xml.etree.ElementTree as ET


WM_CREATE = 0x0001
WM_DESTROY = 0x0002
WM_SIZE = 0x0005
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_SETICON = 0x0080
WM_SETFONT = 0x0030
WM_COPY = 0x0301
EM_SETSEL = 0x00B1
EM_SCROLLCARET = 0x00B7
EM_SETLIMITTEXT = 0x00C5
EM_SETREADONLY = 0x00CF
WM_USER = 0x0400
EM_SETBKGNDCOLOR = WM_USER + 67
EM_SETCHARFORMAT = WM_USER + 68

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_VSCROLL = 0x00200000
WS_HSCROLL = 0x00100000
WS_TABSTOP = 0x00010000
WS_GROUP = 0x00020000
WS_EX_CLIENTEDGE = 0x00000200
ES_MULTILINE = 0x0004
ES_AUTOVSCROLL = 0x0040
ES_AUTOHSCROLL = 0x0080
ES_READONLY = 0x0800
SS_RIGHT = 0x0002
SS_CENTERIMAGE = 0x0200
BS_PUSHBUTTON = 0x00000000
BS_AUTOCHECKBOX = 0x00000003
BS_AUTORADIOBUTTON = 0x00000009
BS_PUSHLIKE = 0x00001000
SW_SHOW = 5
CW_USEDEFAULT = -2147483648
COLOR_WINDOW = 5
DEFAULT_CHARSET = 1
FIXED_PITCH = 1
FF_MODERN = 48
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
ICON_SMALL = 0
ICON_BIG = 1
BM_GETCHECK = 0x00F0
BM_SETCHECK = 0x00F1
BST_CHECKED = 1
WPARAM_MINUS_ONE = ctypes.c_size_t(-1).value
SCF_SELECTION = 0x0001
CFM_BOLD = 0x00000001
CFE_BOLD = 0x00000001
CFM_BACKCOLOR = 0x04000000
CFM_COLOR = 0x40000000

ICON_PATH = Path(__file__).parent / "icons" / "foundry.png"

BUTTON_CLEAR = 1001
BUTTON_COPY = 1002
BUTTON_OUTPUT = 1003
BUTTON_MESSAGES = 1004
FILTER_MESSAGE = 1005
FILTER_WARNING = 1006
FILTER_ERROR = 1007
TIMER_ID = 1
MAX_DISPLAY_CHARACTERS = 2_000_000
MAX_DISPLAY_LINES = 100_000

ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")

SEPARATOR_LINE = re.compile(r"^-{20,}$")
EXPORT_BANNER_LINE = re.compile(r"^>{3}\s+.*\bEXPORT\b.*<{3}$", re.IGNORECASE)
EXPORT_COMPLETE_LINE = re.compile(r"^Export Completed in\s+(.+)$", re.IGNORECASE)
SECTION_LINE = re.compile(r"^[-=]{8,}$")
WARNING_LINE = re.compile(r"^(?:\[?warning\]?|warn)\s*[:\-]", re.IGNORECASE)
ERROR_LINE = re.compile(r"^(?:\[?error\]?|fatal(?: error)?|critical|traceback|exception)\b", re.IGNORECASE)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32
gdiplus = ctypes.windll.gdiplus
shell32 = ctypes.windll.shell32
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


class GdiplusStartupInput(ctypes.Structure):
    _fields_ = [
        ("GdiplusVersion", wintypes.UINT),
        ("DebugEventCallback", ctypes.c_void_p),
        ("SuppressBackgroundThread", wintypes.BOOL),
        ("SuppressExternalCodecs", wintypes.BOOL),
    ]

class CHARFORMAT2W(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwMask", wintypes.DWORD),
        ("dwEffects", wintypes.DWORD),
        ("yHeight", wintypes.LONG),
        ("yOffset", wintypes.LONG),
        ("crTextColor", wintypes.DWORD),
        ("bCharSet", wintypes.BYTE),
        ("bPitchAndFamily", wintypes.BYTE),
        ("szFaceName", wintypes.WCHAR * 32),
        ("wWeight", wintypes.WORD),
        ("sSpacing", ctypes.c_short),
        ("crBackColor", wintypes.DWORD),
        ("lcid", wintypes.DWORD),
        ("dwReserved", wintypes.DWORD),
        ("sStyle", ctypes.c_short),
        ("wKerning", wintypes.WORD),
        ("bUnderlineType", wintypes.BYTE),
        ("bAnimation", wintypes.BYTE),
        ("bRevAuthor", wintypes.BYTE),
        ("bUnderlineColor", wintypes.BYTE),
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
kernel32.LoadLibraryW.argtypes = [wintypes.LPCWSTR]
kernel32.LoadLibraryW.restype = wintypes.HMODULE
RICHEDIT_MODULE = kernel32.LoadLibraryW("Msftedit.dll")
OUTPUT_CONTROL_CLASS = "RICHEDIT50W" if RICHEDIT_MODULE else "EDIT"
gdi32.CreateFontW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR]
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
user32.DestroyIcon.argtypes = [wintypes.HICON]
gdiplus.GdiplusStartup.argtypes = [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(GdiplusStartupInput), ctypes.c_void_p]
gdiplus.GdipCreateBitmapFromFile.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
gdiplus.GdipCreateHICONFromBitmap.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.HICON)]
gdiplus.GdipDisposeImage.argtypes = [ctypes.c_void_p]
gdiplus.GdiplusShutdown.argtypes = [ctypes.c_size_t]
shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]


def load_png_icon(path):
    if not path.is_file():
        return None
    token = ctypes.c_size_t()
    startup = GdiplusStartupInput(1, None, False, False)
    if gdiplus.GdiplusStartup(ctypes.byref(token), ctypes.byref(startup), None) != 0:
        return None
    try:
        bitmap = ctypes.c_void_p()
        if gdiplus.GdipCreateBitmapFromFile(str(path), ctypes.byref(bitmap)) != 0:
            return None
        try:
            icon = wintypes.HICON()
            if gdiplus.GdipCreateHICONFromBitmap(bitmap, ctypes.byref(icon)) != 0:
                return None
            return icon.value
        finally:
            gdiplus.GdipDisposeImage(bitmap)
    finally:
        gdiplus.GdiplusShutdown(token)


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


class LogEntry:
    __slots__ = ("text", "level", "context", "message", "foreground", "bold", "has_newline")

    def __init__(self, text, level="message", context=(), message=None, foreground=None, bold=False, has_newline=True):
        self.text = text
        self.level = level
        self.context = tuple(context)
        self.message = text if message is None else message
        self.foreground = foreground
        self.bold = bold
        self.has_newline = has_newline


class BonoboOutput:
    def __init__(self):
        self.clear()

    def clear(self):
        self.entries = []
        self.current_line = ""
        self.pending_carriage_return = False
        self.last_source = ""
        self.total_characters = 0

    @staticmethod
    def _tool_text(value):
        result = []
        escaped = False
        for character in value or "":
            if escaped:
                result.append({"n": "\n", "r": "\r", "t": "\t"}.get(character, character))
                escaped = False
            elif character == "\\":
                escaped = True
            else:
                result.append(character)
        return "".join(result)

    @staticmethod
    def _parse_color(value):
        try:
            values = tuple(max(0, min(255, round(float(component.strip()) * 255))) for component in value.split(","))
        except (AttributeError, TypeError, ValueError):
            return None
        return values if len(values) == 3 else None

    @staticmethod
    def _plain_context(text):
        match = re.match(r"^((?:[A-Za-z0-9_.-]+:){1,8})\s*(.*)$", text)
        if not match:
            return (), text
        context = tuple(part for part in match.group(1).strip(":").split(":") if part)
        if context[0].lower() in {"warning", "warn", "error", "fatal", "critical"}:
            return (), text
        return context, match.group(2) or text

    @staticmethod
    def _plain_level(raw_text, text):
        lowered = text.lower()
        if "\x1b[91m" in raw_text or "\x1b[31m" in raw_text or ERROR_LINE.match(text):
            return "error"
        if "\x1b[93m" in raw_text or "\x1b[33m" in raw_text or WARNING_LINE.match(text):
            return "warning"
        if EXPORT_COMPLETE_LINE.match(text) or lowered in {"succeeded.", "success"}:
            return "success"
        if SECTION_LINE.match(text) or EXPORT_BANNER_LINE.match(text):
            return "status"
        return "message"

    def _entries_from_text(self, text, level="message", context=(), message=None, foreground=None, bold=False, add_newline=True):
        normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        parts = normalized.split("\n")
        if len(parts) > 1 and parts[-1] == "" and add_newline:
            parts.pop()
        if not parts:
            parts = [""]
        entries = []
        for index, part in enumerate(parts):
            part_message = part if message is None or len(parts) > 1 else message
            entries.append(LogEntry(part, level, context, part_message, foreground, bold, add_newline if index == len(parts) - 1 else True))
        return entries

    def _parse_structured(self, raw_text):
        text = raw_text.strip()
        if not text.startswith("<"):
            return None
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return None
        tag = root.tag.rpartition("}")[2]
        attributes = root.attrib
        if tag in {"block_begin", "block_end", "modify", "wait_for_keypress"}:
            return []
        if tag == "output":
            message = self._tool_text(attributes.get("message", ""))
            add_newline = attributes.get("newline", "1") == "1"
            return self._entries_from_text(message, foreground=self._parse_color(attributes.get("color")), add_newline=add_newline)
        if tag == "debug":
            return self._entries_from_text(self._tool_text(attributes.get("message", "")))
        if tag in {"error", "alert"}:
            level = "error" if tag == "error" else "warning"
            return self._entries_from_text(self._tool_text(attributes.get("message", "")), level, ("Tool",))
        if tag == "event":
            level = attributes.get("level", "message").lower()
            if level not in {"verbose", "status", "message", "warning", "error", "critical"}:
                level = "message"
            context = tuple(part for part in attributes.get("context", "").split(":") if part)
            category = attributes.get("category", "").strip(": ")
            message = attributes.get("message", "")
            body = ": ".join(part for part in (category, message) if part)
            prefix = ":".join(context)
            display = f"{prefix}: {body}" if prefix else body
            return [LogEntry(display, level, context, body, self._parse_color(attributes.get("color")))]
        if tag == "progress_begin":
            return self._entries_from_text(self._tool_text(attributes.get("message", "")), "status", bold=True)
        if tag == "progress_update":
            description = self._tool_text(attributes.get("description", ""))
            optional = self._tool_text(attributes.get("optional_description", ""))
            progress = attributes.get("progress", "")
            message = " ".join(part for part in (description, optional, f"({progress}%)" if progress else "") if part)
            return self._entries_from_text(message, "status")
        if tag == "progress_end":
            message = self._tool_text(attributes.get("message", ""))
            return self._entries_from_text(message, "success" if message else "status", bold=True)
        if tag == "ask_user":
            caption = self._tool_text(attributes.get("caption", ""))
            message = self._tool_text(attributes.get("message", ""))
            return self._entries_from_text(": ".join(part for part in (caption, message) if part), "warning", ("Tool",))
        return []

    def feed(self, text, source=""):
        if source and source != self.last_source:
            if self.last_source and (self.entries or self.current_line):
                self._add_entry(LogEntry(f"[{source}]", "status", bold=True))
            self.last_source = source
        for character in text:
            if self.pending_carriage_return:
                self.pending_carriage_return = False
                if character == "\n":
                    self._finish_line()
                    continue
                self.current_line = ""
            if character == "\f":
                self.clear()
            elif character == "\r":
                self.pending_carriage_return = True
            elif character == "\n":
                self._finish_line()
            elif character == "\b":
                self.current_line = self.current_line[:-1]
            elif character != "\x00":
                self.current_line += character

    def _finish_line(self):
        raw_text = self.current_line
        self.current_line = ""
        structured_entries = self._parse_structured(raw_text)
        if structured_entries is not None:
            for entry in structured_entries:
                self._add_entry(entry)
            return
        clean_text = ANSI_ESCAPE.sub("", raw_text)
        level = self._plain_level(raw_text, clean_text)
        context, message = self._plain_context(clean_text)
        if level in {"warning", "error", "critical"} and not context:
            context = ("Foundry",)
        if SECTION_LINE.match(clean_text) and self.entries and self.entries[-1].text.strip() and self.entries[-1].level in {"message", "verbose"}:
            self.entries[-1].level = "status"
            self.entries[-1].bold = True
        self._add_entry(LogEntry(clean_text, level, context, message, bold=level in {"status", "success"}))

    def _add_entry(self, entry):
        if self.entries and not self.entries[-1].has_newline:
            previous = self.entries[-1]
            previous.text += entry.text
            previous.message += entry.message
            previous.has_newline = entry.has_newline
            if entry.level not in {"message", "verbose"}:
                previous.level = entry.level
            self.total_characters += len(entry.text)
            return
        if self.entries and entry.text == self.entries[-1].text and entry.level == self.entries[-1].level and entry.context == self.entries[-1].context:
            return
        self.entries.append(entry)
        self.total_characters += len(entry.text) + 2
        while self.entries and (len(self.entries) > MAX_DISPLAY_LINES or self.total_characters > MAX_DISPLAY_CHARACTERS):
            removed = self.entries.pop(0)
            self.total_characters -= len(removed.text) + 2

    @staticmethod
    def _filter_level(level):
        if level == "warning" or level == "warning_header":
            return "warning"
        if level in {"error", "critical", "error_header", "critical_header"}:
            return "error"
        return "message"

    def filtered_entries(self, enabled_levels):
        return [entry for entry in self.entries if self._filter_level(entry.level) in enabled_levels]

    def counts(self):
        counts = {"message": 0, "warning": 0, "error": 0}
        for entry in self.entries:
            counts[self._filter_level(entry.level)] += 1
        return counts

    def grouped_entries(self, enabled_levels):
        unique = {}
        for entry in self.entries:
            filter_level = self._filter_level(entry.level)
            if filter_level not in {"warning", "error"} or filter_level not in enabled_levels:
                continue
            key = (entry.level, entry.context or ("Foundry",), entry.message)
            unique[key] = unique.get(key, 0) + 1
        if not unique:
            return [LogEntry("No warnings or errors.", "status", bold=True)]

        result = []
        severity_groups = (("critical", "Critical Errors"), ("error", "Errors"), ("warning", "Warnings"))
        for severity, title in severity_groups:
            items = [(key, count) for key, count in unique.items() if key[0] == severity]
            if not items:
                continue
            total = sum(count for _, count in items)
            result.append(LogEntry(f"{title} ({total})", f"{severity}_header", bold=True))
            tree = {}
            for (level, context, message), count in items:
                node = tree
                for part in context:
                    node = node.setdefault(part, {"_messages": []})
                node.setdefault("_messages", []).append((message, count))

            def append_node(node, depth):
                for name in sorted(key for key in node if key != "_messages"):
                    child = node[name]
                    child_count = sum(count for _, count in child.get("_messages", []))
                    stack = [value for key, value in child.items() if key != "_messages"]
                    while stack:
                        nested = stack.pop()
                        child_count += sum(count for _, count in nested.get("_messages", []))
                        stack.extend(value for key, value in nested.items() if key != "_messages")
                    result.append(LogEntry(f"{'  ' * depth}> {name} ({child_count})", f"{severity}_header", bold=True))
                    append_node(child, depth + 1)
                for message, count in sorted(node.get("_messages", [])):
                    suffix = f" (x{count})" if count > 1 else ""
                    result.append(LogEntry(f"{'  ' * depth}- {message}{suffix}", severity))

            append_node(tree, 1)
        return result


class ExportStatus:
    def __init__(self):
        self.clear()

    def clear(self):
        self.status = "Ready"
        self.started_at = None
        self.completed_duration = None
        self.current_line = ""
        self.previous_line = ""
        self.pending_carriage_return = False

    def feed(self, text):
        text = ANSI_ESCAPE.sub("", text)
        for character in text:
            if self.pending_carriage_return:
                self.pending_carriage_return = False
                if character == "\n":
                    self._finish_line()
                    continue
                self.current_line = ""

            if character == "\f":
                self.clear()
            elif character == "\r":
                self.pending_carriage_return = True
            elif character == "\n":
                self._finish_line()
            elif character == "\b":
                self.current_line = self.current_line[:-1]
            elif character != "\x00":
                self.current_line += character

    def _finish_line(self):
        line = self.current_line.strip()
        self.current_line = ""
        if EXPORT_BANNER_LINE.match(line) and self.started_at is None:
            self.started_at = time.monotonic()
        if SEPARATOR_LINE.match(line):
            heading = self.previous_line.strip()
            if heading and not SEPARATOR_LINE.match(heading):
                if self.started_at is None:
                    self.started_at = time.monotonic()
                self.status = heading
                completed = EXPORT_COMPLETE_LINE.match(heading)
                if completed:
                    self.completed_duration = completed.group(1)
        self.previous_line = line

    def timer_text(self):
        if self.completed_duration is not None:
            return f"Total: {self.completed_duration}"
        elapsed = 0.0 if self.started_at is None else time.monotonic() - self.started_at
        milliseconds = int(elapsed * 1000)
        minutes, remainder = divmod(milliseconds, 60_000)
        seconds, milliseconds = divmod(remainder, 1000)
        if minutes >= 60:
            hours, minutes = divmod(minutes, 60)
            value = f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"
        else:
            value = f"{minutes:02}:{seconds:02}.{milliseconds:03}"
        return f"Elapsed: {value}"

class FoundryOutputWindow:
    def __init__(self, arguments):
        self.arguments = arguments
        self.sources = OutputSources(arguments.log, arguments.watch)
        self.output = BonoboOutput()
        self.export_status = ExportStatus()
        self.hwnd = None
        self.edit = None
        self.clear_button = None
        self.copy_button = None
        self.output_button = None
        self.messages_button = None
        self.show_label = None
        self.filter_message = None
        self.filter_warning = None
        self.filter_error = None
        self.filter_summary = None
        self.status_label = None
        self.timer_label = None
        self.show_messages = False
        self.enabled_levels = {"message", "warning", "error"}
        self.font = None
        self.icon = load_png_icon(ICON_PATH)
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
            OUTPUT_CONTROL_CLASS,
            "",
            WS_CHILD | WS_VISIBLE | WS_VSCROLL | WS_HSCROLL | ES_MULTILINE | ES_AUTOVSCROLL | ES_AUTOHSCROLL | ES_READONLY,
            8,
            8,
            780,
            480,
            hwnd,
            None,
            None,
            None,
        )
        user32.SendMessageW(self.edit, EM_SETLIMITTEXT, MAX_DISPLAY_CHARACTERS, 0)
        user32.SendMessageW(self.edit, EM_SETBKGNDCOLOR, 0, 0x00FFFFFF)
        self.output_button = user32.CreateWindowExW(
            0, "BUTTON", "Output",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | WS_GROUP | BS_AUTORADIOBUTTON | BS_PUSHLIKE,
            8, 496, 78, 26, hwnd, BUTTON_OUTPUT, None, None,
        )
        self.messages_button = user32.CreateWindowExW(
            0, "BUTTON", "Messages",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_AUTORADIOBUTTON | BS_PUSHLIKE,
            86, 496, 90, 26, hwnd, BUTTON_MESSAGES, None, None,
        )
        self.show_label = user32.CreateWindowExW(
            0, "STATIC", "Show:", WS_CHILD | WS_VISIBLE | SS_CENTERIMAGE,
            188, 496, 45, 26, hwnd, None, None, None,
        )
        self.filter_message = user32.CreateWindowExW(
            0, "BUTTON", "Message", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_AUTOCHECKBOX,
            236, 496, 88, 26, hwnd, FILTER_MESSAGE, None, None,
        )
        self.filter_warning = user32.CreateWindowExW(
            0, "BUTTON", "Warning", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_AUTOCHECKBOX,
            324, 496, 88, 26, hwnd, FILTER_WARNING, None, None,
        )
        self.filter_error = user32.CreateWindowExW(
            0, "BUTTON", "Error", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_AUTOCHECKBOX,
            412, 496, 72, 26, hwnd, FILTER_ERROR, None, None,
        )
        self.filter_summary = user32.CreateWindowExW(
            0, "STATIC", "Messages: 0   Warnings: 0   Errors: 0",
            WS_CHILD | WS_VISIBLE | SS_RIGHT | SS_CENTERIMAGE,
            492, 496, 390, 26, hwnd, None, None, None,
        )
        self.clear_button = user32.CreateWindowExW(
            0, "BUTTON", "Clear", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
            8, 536, 90, 28, hwnd, BUTTON_CLEAR, None, None,
        )
        self.copy_button = user32.CreateWindowExW(
            0, "BUTTON", "Copy All", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
            106, 536, 90, 28, hwnd, BUTTON_COPY, None, None,
        )
        self.status_label = user32.CreateWindowExW(
            WS_EX_CLIENTEDGE, "STATIC", "Ready", WS_CHILD | WS_VISIBLE | SS_CENTERIMAGE,
            204, 536, 520, 28, hwnd, None, None, None,
        )
        self.timer_label = user32.CreateWindowExW(
            WS_EX_CLIENTEDGE, "STATIC", "Elapsed: 00:00.000",
            WS_CHILD | WS_VISIBLE | SS_RIGHT | SS_CENTERIMAGE,
            732, 536, 150, 28, hwnd, None, None, None,
        )
        self.font = gdi32.CreateFontW(
            -16, 0, 0, 0, 400, False, False, False, DEFAULT_CHARSET,
            0, 0, 0, FIXED_PITCH | FF_MODERN, "Consolas",
        )
        for control in (
            self.edit, self.output_button, self.messages_button, self.show_label,
            self.filter_message, self.filter_warning, self.filter_error, self.filter_summary,
            self.clear_button, self.copy_button, self.status_label, self.timer_label,
        ):
            user32.SendMessageW(control, WM_SETFONT, self.font, True)
        user32.SendMessageW(self.output_button, BM_SETCHECK, BST_CHECKED, 0)
        user32.SendMessageW(self.filter_message, BM_SETCHECK, BST_CHECKED, 0)
        user32.SendMessageW(self.filter_warning, BM_SETCHECK, BST_CHECKED, 0)
        user32.SendMessageW(self.filter_error, BM_SETCHECK, BST_CHECKED, 0)
        user32.SetTimer(hwnd, TIMER_ID, 100, None)

    def _resize_controls(self, width, height):
        button_height = 30
        filter_height = 26
        margin = 8
        control_top = max(margin, height - margin - button_height)
        filter_top = max(margin, control_top - margin - filter_height)
        edit_height = max(80, filter_top - margin * 2)
        user32.MoveWindow(self.edit, margin, margin, max(100, width - margin * 2), edit_height, True)
        user32.MoveWindow(self.output_button, margin, filter_top, 78, filter_height, True)
        user32.MoveWindow(self.messages_button, margin + 78, filter_top, 90, filter_height, True)
        user32.MoveWindow(self.show_label, margin + 180, filter_top, 45, filter_height, True)
        user32.MoveWindow(self.filter_message, margin + 228, filter_top, 88, filter_height, True)
        user32.MoveWindow(self.filter_warning, margin + 316, filter_top, 88, filter_height, True)
        user32.MoveWindow(self.filter_error, margin + 404, filter_top, 72, filter_height, True)
        summary_left = margin + 484
        user32.MoveWindow(self.filter_summary, summary_left, filter_top, max(80, width - summary_left - margin), filter_height, True)
        user32.MoveWindow(self.clear_button, margin, control_top, 90, button_height, True)
        user32.MoveWindow(self.copy_button, margin + 98, control_top, 90, button_height, True)
        status_left = margin + 196
        timer_width = 220
        timer_left = max(status_left + 100, width - margin - timer_width)
        user32.MoveWindow(self.status_label, status_left, control_top, max(80, timer_left - status_left - margin), button_height, True)
        user32.MoveWindow(self.timer_label, timer_left, control_top, timer_width, button_height, True)

    def _update_status_controls(self):
        user32.SetWindowTextW(self.status_label, self.export_status.status)
        user32.SetWindowTextW(self.timer_label, self.export_status.timer_text())

    @staticmethod
    def _colorref(rgb):
        red, green, blue = rgb
        return red | (green << 8) | (blue << 16)

    def _enabled_levels(self):
        return set(self.enabled_levels)

    def _entry_format(self, entry):
        styles = {
            "message": ((0, 0, 0), (255, 255, 255), False),
            "verbose": ((90, 90, 90), (255, 255, 255), False),
            "status": ((255, 255, 255), (15, 35, 53), True),
            "warning": ((0, 0, 0), (255, 183, 38), False),
            "warning_header": ((0, 0, 0), (255, 183, 38), True),
            "error": ((255, 255, 255), (211, 47, 47), False),
            "error_header": ((255, 255, 255), (211, 47, 47), True),
            "critical": ((255, 255, 255), (128, 0, 0), False),
            "critical_header": ((255, 255, 255), (128, 0, 0), True),
            "success": ((255, 255, 255), (0, 128, 0), True),
        }
        foreground, background, bold = styles.get(entry.level, styles["message"])
        if entry.foreground:
            foreground = entry.foreground
        format_value = CHARFORMAT2W()
        format_value.cbSize = ctypes.sizeof(CHARFORMAT2W)
        format_value.dwMask = CFM_COLOR | CFM_BACKCOLOR | CFM_BOLD
        format_value.dwEffects = CFE_BOLD if entry.bold or bold else 0
        format_value.crTextColor = self._colorref(foreground)
        format_value.crBackColor = self._colorref(background)
        return format_value

    def _update_filter_summary(self):
        counts = self.output.counts()
        summary = f"Messages: {counts['message']}   Warnings: {counts['warning']}   Errors: {counts['error']}"
        user32.SetWindowTextW(self.filter_summary, summary)

    def _render_output(self):
        enabled_levels = self._enabled_levels()
        entries = self.output.grouped_entries(enabled_levels) if self.show_messages else self.output.filtered_entries(enabled_levels)

        user32.SendMessageW(self.edit, EM_SETREADONLY, 0, 0)
        rendered = "\r".join(entry.text for entry in entries)
        if entries:
            rendered += "\r"
        user32.SetWindowTextW(self.edit, rendered)
        position = 0
        for entry in entries:
            end = position + len(entry.text)
            user32.SendMessageW(self.edit, EM_SETSEL, position, end)
            format_value = self._entry_format(entry)
            user32.SendMessageW(self.edit, EM_SETCHARFORMAT, SCF_SELECTION, ctypes.addressof(format_value))
            position = end + 1
        user32.SendMessageW(self.edit, EM_SETSEL, WPARAM_MINUS_ONE, -1)
        user32.SendMessageW(self.edit, EM_SCROLLCARET, 0, 0)
        user32.SendMessageW(self.edit, EM_SETREADONLY, 1, 0)
        self._update_filter_summary()

    def _update_output(self):
        chunks = self.sources.read_new()
        for source, text in chunks:
            self.output.feed(text, source)
            if source == "Foundry":
                self.export_status.feed(text)
        if chunks:
            self._render_output()
        self._update_status_controls()

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
                self.output.clear()
                self.export_status.clear()
                self._render_output()
                self._update_status_controls()
                return 0
            if command == BUTTON_COPY:
                user32.SendMessageW(self.edit, EM_SETSEL, 0, -1)
                user32.SendMessageW(self.edit, WM_COPY, 0, 0)
                return 0
            if command == BUTTON_OUTPUT:
                self.show_messages = False
                user32.SendMessageW(self.output_button, BM_SETCHECK, BST_CHECKED, 0)
                user32.SendMessageW(self.messages_button, BM_SETCHECK, 0, 0)
                self._render_output()
                return 0
            if command == BUTTON_MESSAGES:
                self.show_messages = True
                user32.SendMessageW(self.output_button, BM_SETCHECK, 0, 0)
                user32.SendMessageW(self.messages_button, BM_SETCHECK, BST_CHECKED, 0)
                self._render_output()
                return 0
            if command in {FILTER_MESSAGE, FILTER_WARNING, FILTER_ERROR}:
                control, level = {
                    FILTER_MESSAGE: (self.filter_message, "message"),
                    FILTER_WARNING: (self.filter_warning, "warning"),
                    FILTER_ERROR: (self.filter_error, "error"),
                }[command]
                if user32.SendMessageW(control, BM_GETCHECK, 0, 0) == BST_CHECKED:
                    self.enabled_levels.add(level)
                else:
                    self.enabled_levels.discard(level)
                self._render_output()
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
            if self.icon:
                user32.DestroyIcon(self.icon)
                self.icon = None
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def run(self):
        shell32.SetCurrentProcessExplicitAppUserModelID("Foundry.Output")
        instance = kernel32.GetModuleHandleW(None)
        class_name = f"FoundryOutputWindow{self.arguments.parent_pid}"
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = ctypes.cast(self.window_proc, ctypes.c_void_p).value
        window_class.hInstance = instance
        window_class.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(32512))
        window_class.hIcon = self.icon
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
        if self.icon:
            user32.SendMessageW(self.hwnd, WM_SETICON, ICON_BIG, self.icon)
            user32.SendMessageW(self.hwnd, WM_SETICON, ICON_SMALL, self.icon)
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
