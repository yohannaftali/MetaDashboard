"""The monitoring terminal during a fetch (Windows): start it minimized, keep it minimized, close it afterwards.

A terminal that is already running (opened by hand) is left as it is: not started again and not closed.
"""
import ctypes
import os
import subprocess
import time
from ctypes import wintypes

SW_SHOWMINNOACTIVE = 7  # minimized, without taking the focus
WM_CLOSE = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _image(pid):
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        buf, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None
    finally:
        k32.CloseHandle(h)


def running(path):
    """True when a process of this terminal64.exe is running."""
    pids, needed = (wintypes.DWORD * 4096)(), wintypes.DWORD()
    if not ctypes.windll.psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(needed)):
        return False
    target = _norm(path)
    return any(img and _norm(img) == target
               for img in (_image(pid) for pid in pids[:needed.value // ctypes.sizeof(wintypes.DWORD)] if pid))


def _windows(pid):
    user32, found = ctypes.windll.user32, []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(each, 0)
    return found


class Terminal:
    """with Terminal(path): ... starts the terminal minimized unless it already runs, and closes what it started."""

    def __init__(self, path, log=print):
        self.path, self.log, self.proc = path, log, None

    def __enter__(self):
        if running(self.path):
            self.log('terminal already open, left as it is: %s' % self.path)
            return self
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = SW_SHOWMINNOACTIVE
        self.proc = subprocess.Popen([self.path, '/portable'], startupinfo=si, cwd=os.path.dirname(self.path))
        end = time.monotonic() + 15
        while time.monotonic() < end and self.proc.poll() is None and not _windows(self.proc.pid):
            time.sleep(0.25)
        self.minimize()
        return self

    def minimize(self):
        """The terminal can restore its window while it starts or logs in; call after each login."""
        if self.proc and self.proc.poll() is None:
            for hwnd in _windows(self.proc.pid):
                if not ctypes.windll.user32.IsIconic(hwnd):
                    ctypes.windll.user32.ShowWindow(hwnd, SW_SHOWMINNOACTIVE)

    def __exit__(self, *exc):
        if not self.proc or self.proc.poll() is not None:
            return
        for hwnd in _windows(self.proc.pid):  # a normal close, so the terminal saves its settings
            ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        try:
            self.proc.wait(20)
        except subprocess.TimeoutExpired:
            self.log('terminal did not close in 20 s, stopped')
            self.proc.kill()
            self.proc.wait()
