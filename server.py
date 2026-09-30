"""Keyboard Input Display - capture server.

Hooks global keyboard + mouse input via the Win32 API (no pip packages
required) and streams events to the browser overlay over Server-Sent
Events. Point an OBS Browser Source at the printed URL.

Usage:
    python server.py [--port 8456]
    pythonw server.py        (no console window)
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
OVERLAY_DIR = os.path.join(BASE_DIR, "overlay")
PROFILES_DIR = os.path.join(BASE_DIR, "profiles")


def list_profiles():
    try:
        return sorted(os.path.splitext(f)[0] for f in os.listdir(PROFILES_DIR)
                      if f.lower().endswith(".json"))
    except OSError:
        return []


def active_profile():
    try:
        with open(CONFIG_PATH, encoding="utf-8-sig") as f:
            return json.load(f).get("profile")
    except (OSError, ValueError):
        return None


def profile_path(name):
    fname = os.path.basename(name)
    if not fname.lower().endswith(".json"):
        fname += ".json"
    return os.path.join(PROFILES_DIR, fname)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------------------------------------------------------------- key names

VK_NAMES = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause",
    0x14: "CapsLock", 0x1B: "Esc", 0x20: "Space",
    0x21: "PgUp", 0x22: "PgDn", 0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    0x2C: "PrintScreen", 0x2D: "Insert", 0x2E: "Delete",
    0x5B: "LWin", 0x5C: "RWin", 0x5D: "Menu",
    0x6A: "NumpadMul", 0x6B: "NumpadAdd", 0x6D: "NumpadSub",
    0x6E: "NumpadDec", 0x6F: "NumpadDiv",
    0x90: "NumLock", 0x91: "ScrollLock",
    0xA0: "LShift", 0xA1: "RShift", 0xA2: "LCtrl", 0xA3: "RCtrl",
    0xA4: "LAlt", 0xA5: "RAlt",
    0xBA: "Semicolon", 0xBB: "Equals", 0xBC: "Comma", 0xBD: "Minus",
    0xBE: "Period", 0xBF: "Slash", 0xC0: "Backtick",
    0xDB: "LBracket", 0xDC: "Backslash", 0xDD: "RBracket", 0xDE: "Quote",
}
for _c in range(0x30, 0x3A):                      # 0-9
    VK_NAMES[_c] = chr(_c)
for _c in range(0x41, 0x5B):                      # A-Z
    VK_NAMES[_c] = chr(_c)
for _i in range(24):                              # F1-F24
    VK_NAMES[0x70 + _i] = f"F{_i + 1}"
for _i in range(10):                              # Numpad0-9
    VK_NAMES[0x60 + _i] = f"Numpad{_i}"

LLKHF_EXTENDED = 0x01


def vk_to_name(vk, flags):
    if vk == 0x0D and flags & LLKHF_EXTENDED:
        return "NumpadEnter"
    return VK_NAMES.get(vk, f"VK{vk:02X}")


# ------------------------------------------------------------- broadcasting

clients_lock = threading.Lock()
clients = []          # list[(queue.Queue, wants_motion)]
held_lock = threading.Lock()
held = set()          # currently pressed key names


def broadcast(msg, motion=False):
    # motion messages only go to overlays that have a motion widget
    data = json.dumps(msg)
    with clients_lock:
        for q, wants_motion in clients:
            if motion and not wants_motion:
                continue
            try:
                q.put_nowait(data)
            except queue.Full:
                pass


def key_down(name):
    with held_lock:
        if name in held:          # ignore auto-repeat
            return
        held.add(name)
    broadcast({"t": "down", "k": name})


def key_up(name):
    with held_lock:
        if name not in held:      # never shown as down, nothing to clear
            return
        held.discard(name)
    broadcast({"t": "up", "k": name})


# raw mouse motion and wheel ticks, accumulated between broadcast ticks so
# high-rate mice and free-spinning wheels can't flood the stream
move_lock = threading.Lock()
move_acc = [0, 0]
wheel_acc = {"WheelUp": False, "WheelDown": False}


def wheel_tick(name):
    with move_lock:
        wheel_acc[name] = True


def motion_thread():
    while True:
        time.sleep(1 / 30)
        with move_lock:
            dx, dy = move_acc
            move_acc[0] = move_acc[1] = 0
            wheels = [k for k, hit in wheel_acc.items() if hit]
            for k in wheels:
                wheel_acc[k] = False
        for k in wheels:
            broadcast({"t": "flash", "k": k})
        if dx or dy:
            broadcast({"t": "move", "dx": dx, "dy": dy}, motion=True)


# ------------------------------------------------------------- win32 hooks

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
        ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wt.POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD),
        ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)

# explicit signatures: defaults truncate 64-bit handles (hook fails, err 126)
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HMODULE, wt.DWORD]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]

WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105

MOUSE_DOWN = {0x0201: "LMB", 0x0204: "RMB", 0x0207: "MMB"}
MOUSE_UP = {0x0202: "LMB", 0x0205: "RMB", 0x0208: "MMB"}
WM_XBUTTONDOWN, WM_XBUTTONUP, WM_MOUSEWHEEL = 0x020B, 0x020C, 0x020A


def _kbd_proc(n_code, w_param, l_param):
    if n_code >= 0:
        kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        name = vk_to_name(kb.vkCode, kb.flags)
        if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
            key_down(name)
        elif w_param in (WM_KEYUP, WM_SYSKEYUP):
            key_up(name)
    return user32.CallNextHookEx(None, n_code, w_param, l_param)


def _mouse_proc(n_code, w_param, l_param):
    if n_code >= 0:
        ms = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
        if w_param in MOUSE_DOWN:
            key_down(MOUSE_DOWN[w_param])
        elif w_param in MOUSE_UP:
            key_up(MOUSE_UP[w_param])
        elif w_param == WM_XBUTTONDOWN:
            key_down("M4" if (ms.mouseData >> 16) == 1 else "M5")
        elif w_param == WM_XBUTTONUP:
            key_up("M4" if (ms.mouseData >> 16) == 1 else "M5")
        elif w_param == WM_MOUSEWHEEL:
            delta = ctypes.c_short(ms.mouseData >> 16).value
            wheel_tick("WheelUp" if delta > 0 else "WheelDown")
    return user32.CallNextHookEx(None, n_code, w_param, l_param)


# --------------------------------------------------- raw input (mouse motion)
# Raw Input reports true relative motion straight from the device, so the
# overlay keeps working when games lock or recenter the cursor.

class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wt.DWORD), ("dwSize", wt.DWORD),
        ("hDevice", wt.HANDLE), ("wParam", wt.WPARAM),
    ]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [
        ("usFlags", wt.USHORT), ("ulButtons", wt.ULONG),
        ("ulRawButtons", wt.ULONG), ("lLastX", wt.LONG),
        ("lLastY", wt.LONG), ("ulExtraInformation", wt.ULONG),
    ]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wt.USHORT), ("usUsage", wt.USHORT),
        ("dwFlags", wt.DWORD), ("hwndTarget", ctypes.c_void_p),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_void_p, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HMODULE), ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p), ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
    ]


user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [ctypes.c_void_p, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.CreateWindowExW.restype = ctypes.c_void_p
user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_void_p, wt.HMODULE, ctypes.c_void_p,
]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.GetRawInputData.restype = wt.UINT
user32.GetRawInputData.argtypes = [
    ctypes.c_void_p, wt.UINT, ctypes.c_void_p,
    ctypes.POINTER(wt.UINT), wt.UINT,
]

WM_INPUT, RID_INPUT, RIM_TYPEMOUSE = 0x00FF, 0x10000003, 0
MOUSE_MOVE_ABSOLUTE = 0x01
RIDEV_INPUTSINK = 0x0100


def _wnd_proc(hwnd, msg, w_param, l_param):
    if msg == WM_INPUT:
        ri = RAWINPUT()
        size = wt.UINT(ctypes.sizeof(ri))
        got = user32.GetRawInputData(
            ctypes.c_void_p(l_param), RID_INPUT, ctypes.byref(ri),
            ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER))
        if (got not in (0, 0xFFFFFFFF)
                and ri.header.dwType == RIM_TYPEMOUSE
                and not ri.mouse.usFlags & MOUSE_MOVE_ABSOLUTE):
            with move_lock:
                move_acc[0] += ri.mouse.lLastX
                move_acc[1] += ri.mouse.lLastY
    return user32.DefWindowProcW(hwnd, msg, w_param, l_param)


# keep references so the callbacks are never garbage collected
_kbd_callback = HOOKPROC(_kbd_proc)
_mouse_callback = HOOKPROC(_mouse_proc)
_wnd_callback = WNDPROC(_wnd_proc)


def hook_thread():
    h_mod = kernel32.GetModuleHandleW(None)
    kbd_hook = user32.SetWindowsHookExW(13, _kbd_callback, h_mod, 0)
    mouse_hook = user32.SetWindowsHookExW(14, _mouse_callback, h_mod, 0)
    if not kbd_hook or not mouse_hook:
        raise ctypes.WinError(ctypes.get_last_error())

    # hidden window that receives WM_INPUT for raw mouse motion
    wc = WNDCLASSW()
    wc.lpfnWndProc = _wnd_callback
    wc.hInstance = h_mod
    wc.lpszClassName = "KIDRawInput"
    user32.RegisterClassW(ctypes.byref(wc))
    hwnd = user32.CreateWindowExW(
        0, "KIDRawInput", None, 0, 0, 0, 0, 0, None, None, h_mod, None)
    rid = RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, hwnd)  # generic mouse
    if not user32.RegisterRawInputDevices(
            ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE)):
        print("warning: raw mouse motion unavailable", flush=True)

    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


# ------------------------------------------------------------ config watch

def config_watch_thread():
    last = None
    while True:
        snap = {}
        paths = [CONFIG_PATH]
        try:
            paths += [os.path.join(PROFILES_DIR, f)
                      for f in os.listdir(PROFILES_DIR)
                      if f.lower().endswith(".json")]
        except OSError:
            pass
        for p in paths:
            try:
                snap[p] = os.path.getmtime(p)
            except OSError:
                pass
        if last is not None and snap != last:
            broadcast({"t": "reload"})
        last = snap
        time.sleep(1)


# -------------------------------------------------------------- http server

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".otf": "font/otf",
    ".ttf": "font/ttf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def handle(self):
        # a client (browser/OBS) dropping the connection surfaces here as a
        # ConnectionError out of the base read loop; treat it as a normal
        # disconnect instead of letting it print a traceback
        try:
            super().handle()
        except (ConnectionError, OSError):
            pass

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/events":
            self.serve_events(query)
        elif path == "/config.json":
            self.serve_config(query)
        elif path == "/profiles":
            body = json.dumps(
                {"active": active_profile(), "profiles": list_profiles()},
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path.startswith("/fonts/"):
            self.serve_file(
                os.path.join(BASE_DIR, "fonts", os.path.basename(path)))
        else:
            name = os.path.basename(path) or "index.html"
            self.serve_file(os.path.join(OVERLAY_DIR, name))

    def serve_config(self, query):
        # ?profile=Name overrides the active profile from config.json,
        # so different OBS sources can show different layouts at once
        params = urllib.parse.parse_qs(query)
        name = params.get("profile", [None])[0] or active_profile()
        if name is None:
            self.serve_file(CONFIG_PATH)   # legacy: layout directly in config
            return
        self.serve_file(profile_path(name))

    def serve_file(self, full_path):
        if not os.path.isfile(full_path):
            self.send_error(404)
            return
        with open(full_path, "rb") as f:
            body = f.read()
        ext = os.path.splitext(full_path)[1].lower()
        self.send_response(200)
        self.send_header("Content-Type",
                         CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def serve_events(self, query):
        # ?motion=0 opts out of mouse motion (overlay has no motion widget)
        params = urllib.parse.parse_qs(query)
        wants_motion = params.get("motion", ["1"])[0] != "0"

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        q = queue.Queue(maxsize=512)
        entry = (q, wants_motion)
        with clients_lock:
            clients.append(entry)
        try:
            with held_lock:
                snapshot = sorted(held)
            self._sse([json.dumps({"t": "state", "held": snapshot})])
            while True:
                try:
                    batch = [q.get(timeout=15)]
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                # drain anything else already queued into the same write
                while True:
                    try:
                        batch.append(q.get_nowait())
                    except queue.Empty:
                        break
                self._sse(batch)
        except (ConnectionError, OSError):
            pass
        finally:
            with clients_lock:
                if entry in clients:
                    clients.remove(entry)

    def _sse(self, batch):
        self.wfile.write("".join(f"data: {d}\n\n" for d in batch).encode())
        self.wfile.flush()


class Server(ThreadingHTTPServer):
    # SO_REUSEADDR on Windows binds taken ports without error,
    # which would break port-conflict detection
    allow_reuse_address = False


def lan_ip():
    # no packet is actually sent; this just asks the OS which local
    # interface it would use to reach an external address
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "localhost"
    finally:
        s.close()


def main():
    parser = argparse.ArgumentParser(description="Keyboard Input Display server")
    parser.add_argument("--port", type=int, default=8456)
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="address to bind (default 127.0.0.1, local only); "
             "use 0.0.0.0 to allow other computers on your LAN")
    args = parser.parse_args()

    threading.Thread(target=hook_thread, daemon=True).start()
    threading.Thread(target=config_watch_thread, daemon=True).start()
    threading.Thread(target=motion_thread, daemon=True).start()

    # if the port is taken, walk up to the next free one
    server = None
    port = args.port
    for offset in range(20):
        try:
            server = Server((args.host, args.port + offset), Handler)
            port = args.port + offset
            break
        except OSError:
            continue
    if server is None:
        print(f"error: ports {args.port}-{args.port + 19} are all in use")
        return

    server.daemon_threads = True
    # when bound to all interfaces, point the overlay URL at the LAN IP so
    # it can be copied straight onto another computer
    host = lan_ip() if args.host == "0.0.0.0" else "localhost"
    url = f"http://{host}:{port}/"
    print("Keyboard Input Display")
    if port != args.port:
        print(f"  NOTE: port {args.port} was taken, using {port} -- "
              "update the OBS Browser Source URL to match")
    print(f"  Overlay URL : {url}")
    print("  OBS         : add a Browser Source with that URL")
    if args.host == "0.0.0.0":
        print(f"  LAN         : reachable from other computers at {url}")
        print("                (allow Python through Windows Firewall if prompted)")
    print(f"  Profile     : {active_profile() or '(layout in config.json)'}")
    print(f"  Available   : {', '.join(list_profiles()) or '(none)'}")
    print("  Switch      : edit \"profile\" in config.json, or use "
          f"{url}?profile=Name per source")
    print("  Stop        : Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
