# Keyboard Input Display

Lightweight keyboard/mouse input overlay for OBS. A small Python server
captures global input with native Windows hooks (zero pip dependencies)
and streams it to a transparent browser overlay: keycaps light up with
a glow as you press them, and a motion widget visualizes your mouse
movement.

## Run it

Double-click `start.bat` (or `python server.py`). To run without a
console window, use `pythonw server.py` instead.

Open http://localhost:8456/ in a browser to preview. Press keys —
they light up even when the browser isn't focused.

Custom port: `python server.py --port 9000`

If the port is already taken (by another app, or a second copy of the
server), it automatically tries the next ones (up to +19) and prints
which port it settled on — update the OBS Browser Source URL to match
if that happens.

### View from another computer (LAN)

By default the server binds to `127.0.0.1`, so only the local machine
can reach it. To open the overlay from another computer on the same
network — e.g. OBS running on a second PC — bind to all interfaces:

Double-click `start-lan.bat` (or `python server.py --host 0.0.0.0`).

On startup it prints your machine's LAN address, e.g.:

```
  Overlay URL : http://192.168.1.50:8456/
  LAN         : reachable from other computers at http://192.168.1.50:8456/
```

Open that URL (or point an OBS Browser Source at it) from the other
computer. Notes:

- **Firewall:** the first connection may trigger a Windows Firewall
  prompt — allow Python on **Private** networks. If no prompt appears
  and it's blocked, add an inbound rule for the port manually.
- **Keep it on your LAN.** There's no authentication and it's plain
  HTTP — fine for a trusted home network, but don't expose it to the
  internet.

## Add to OBS

1. Sources → **+** → **Browser**
2. URL: `http://localhost:8456/`
3. Width/Height: see the profile table below
4. The page background is transparent — position it anywhere on your scene.

Sizing rule for custom layouts:
`width = (rightmost x + w) × (unit + gap) + 48`, same for height with
the bottom edge. The 48 covers the 24px glow margin on each side.

The server must be running for the overlay to show input; if it stops,
the overlay dims and grays out until it reconnects (it retries
automatically — no OBS interaction needed).

**Live reload:** edits to `config.json` or any profile in `profiles/`
apply within a second, no restart. Changes to files in `overlay/` need
a "Refresh cache of current page" in the Browser Source properties;
changes to `server.py` need a server restart.

## Profiles

| profile | contents | OBS size |
| ------- | -------- | -------- |
| **Watherum Aims** (default) | Left half-keyboard (`` ` `` 1–7, Tab/QWERTY, Caps/ASDFG, Shift/ZXCVB, Ctrl/Alt/Space, plus `Y` and `,` side-button binds) + mouse cluster + motion trail | **832 × 400** |
| **Full Keyboard** | Complete 104-key ANSI board: F-row, nav cluster, arrows, numpad (smaller 48px keys) | **1260 × 395** |
| **Full Keyboard + Mouse** | Full Keyboard plus the mouse cluster and motion trail on the right | **1480 × 395** |

The mouse cluster in all profiles is LMB and RMB flanking a wheel
column (▲ scroll-up, ▬ wheel-click, ▼ scroll-down).

Layouts live as JSON files in `profiles/` — one file per layout.
`config.json` just names the active one:

```json
{ "profile": "Watherum Aims" }
```

- **Create** a layout: copy an existing file in `profiles/`, rename it,
  edit away. New files are picked up automatically.
- **Switch**: change the name in `config.json` — the overlay swaps live,
  mid-stream.
- **Pin a source**: add `?profile=Name` to the Browser Source URL
  (e.g. `http://localhost:8456/?profile=Watherum%20Aims`). That source
  ignores `config.json`, so different scenes can show different layouts
  at the same time. URL-encode special characters: space is `%20`,
  `+` is `%2B` (`?profile=Full%20Keyboard%20%2B%20Mouse`).
- `http://localhost:8456/profiles` lists what's available.

Edits to the active profile also apply live, within a second.

## Layout format

```json
{
  "glowColor": "#ff2a3c",  // press glow
  "keyColor": "#1e1e22",   // keycap base color (shading is derived)
  "textColor": "#9a9aa4",  // legend text
  "unit": 64,              // size of a 1x1 key in pixels
  "gap": 8,                // spacing between keys in pixels
                           // (these fields live in the profile file)
  "motion": { "style": "trail", "x": 8.2, "y": 2.0, "w": 2.8, "h": 3.0, "sensitivity": 1.0 },
  "keys": [
    { "id": "W", "x": 2.5, "y": 1 },
    { "id": "LShift", "x": 0, "y": 3, "w": 2.25, "label": "SHIFT", "glow": "#3cb4ff" }
  ]
}
```

Each key:

| field   | meaning                                          | default     |
| ------- | ------------------------------------------------ | ----------- |
| `id`    | which physical key (see names below)             | required    |
| `x`,`y` | position in key units (fractions fine)           | required    |
| `w`,`h` | width/height in key units                        | `1`         |
| `label` | text shown on the cap                            | the `id`    |
| `glow`  | per-key press glow color                         | `glowColor` |
| `color` | per-key cap color                                | `keyColor`  |
| `text`  | per-key legend color                             | `textColor` |

Colors accept any CSS color (`#hex`, `rgb(...)`, names). Any key can be
added anywhere — the canvas grows to fit. The same `id` may appear more
than once (both caps light up). Legends auto-size to their cap and
shrink when a label would touch the edges.

### Mouse motion widget

Mouse movement is captured via Raw Input (true relative motion straight
from the device), so it keeps working in games that lock or hide the
cursor. Configure it with the `motion` section:

| field           | meaning                                            | default |
| --------------- | -------------------------------------------------- | ------- |
| `style`         | `trail`, `pad`, `arrows`, or `off`                 | `off`   |
| `x`,`y`,`w`,`h` | position/size in key units, like keys              | —       |
| `sensitivity`   | motion scale multiplier                            | `1.0`   |
| `glow`,`color`  | color overrides, like per-key colors               | global  |

Styles:

- **`trail`** — glowing line tracing your recent mouse path, fading out.
  Runs on an infinite plane: a soft camera follows the motion, so long
  sweeps never pin against the panel edge.
- **`pad`** — joystick-style dot that deflects with velocity and springs back
- **`arrows`** — four keycap arrows that light up while moving that direction

Delete the `motion` section (or set `"style": "off"`) to hide it.

### Key names

- Letters/digits: `A`–`Z`, `0`–`9`
- Function: `F1`–`F24`
- Modifiers: `LShift`, `RShift`, `LCtrl`, `RCtrl`, `LAlt`, `RAlt`, `LWin`, `RWin`, `Menu`
- Editing: `Space`, `Enter`, `Backspace`, `Tab`, `Esc`, `CapsLock`, `Insert`, `Delete`, `Home`, `End`, `PgUp`, `PgDn`
- Arrows: `Up`, `Down`, `Left`, `Right`
- Punctuation: `Backtick`, `Minus`, `Equals`, `LBracket`, `RBracket`, `Backslash`, `Semicolon`, `Quote`, `Comma`, `Period`, `Slash`
- Numpad: `Numpad0`–`Numpad9`, `NumpadAdd`, `NumpadSub`, `NumpadMul`, `NumpadDiv`, `NumpadDec`, `NumpadEnter`
- Misc: `PrintScreen`, `ScrollLock`, `Pause`, `NumLock`
- Mouse: `LMB`, `RMB`, `MMB`, `M4`, `M5`, `WheelUp`, `WheelDown` (wheel keys flash on scroll)

Unrecognized keys are reported as `VKxx` (hex virtual-key code) — add
that as an `id` if you have an exotic key.

Note: keys remapped in mouse/keyboard software (e.g. a side button
bound to `Y`) arrive as the key they send, so they light that cap —
the overlay can't tell which device pressed it.

## Font

Legends render in **HK Modular**, self-hosted from the `fonts/` folder
(no internet needed; Segoe UI fills in any glyph the font lacks, like
▲ ▬ ▼). To swap the face, drop a font file in `fonts/` and update the
`@font-face` block at the top of `overlay/style.css`. The rounded
variant `HKModular-BoldRounded.otf` is already there if you want a
softer look.

## Files

- `server.py` — input capture + web server (stdlib only)
- `config.json` — names the active profile (live-reloads)
- `profiles/` — one JSON layout per profile
- `overlay/` — the page OBS renders (`index.html`, `style.css`, `app.js`)
- `fonts/` — self-hosted overlay fonts
- `start.bat` — launcher (local only)
- `start-lan.bat` — launcher bound to `0.0.0.0` for LAN access
