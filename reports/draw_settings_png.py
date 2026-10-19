"""Draw the rebuilt FreeDictate settings structure as a PNG.

The same content as reports/settings-page-structure.html, drawn with Pillow so
the proof can also be delivered as a thread attachment. The app binary was not
run for this slice, so this is a drawing of the page structure, not a
screenshot of the live window.
"""
from PIL import Image, ImageDraw, ImageFont

W = 760
BG = "#11111b"
PANEL = "#1e1e2e"
SURFACE = "#181825"
FIELD = "#11111b"
LINE = "#313244"
TEXT = "#cdd6f4"
SUB = "#bac2de"
ACCENT = "#89b4fa"
ON_ACCENT = "#11111b"
WARN = "#f9e2af"
OK = "#a6e3a1"

REG = "C:/Windows/Fonts/segoeui.ttf"
BOLD = "C:/Windows/Fonts/segoeuib.ttf"
MONO = "C:/Windows/Fonts/consola.ttf"

f_body = ImageFont.truetype(REG, 15)
f_small = ImageFont.truetype(REG, 13)
f_bold = ImageFont.truetype(BOLD, 16)
f_title = ImageFont.truetype(BOLD, 21)
f_mono = ImageFont.truetype(MONO, 13)

img = Image.new("RGB", (W, 6000), BG)
d = ImageDraw.Draw(img)


def wrap(text, font, width):
    words = text.split()
    lines, line = [], ""
    for word in words:
        probe = (line + " " + word).strip()
        if d.textlength(probe, font=font) <= width or not line:
            line = probe
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def para(text, font, width, color, x, y, gap=4):
    for line in wrap(text, font, width):
        d.text((x, y), line, font=font, fill=color)
        y += font.size + gap
    return y


def chip(x, y, label, fill=FIELD, border=LINE, color=TEXT, font=f_small, pad=10, h=26):
    w = d.textlength(label, font=font) + pad * 2
    d.rounded_rectangle([x, y, x + w, y + h], radius=6, fill=fill, outline=border)
    d.text((x + pad, y + (h - font.size) / 2 - 1), label, font=font, fill=color)
    return x + w + 8


def card(x, y, w, title, rows):
    y += 4
    d.text((x, y), title, font=f_bold, fill=TEXT)
    y += 26
    top = y
    for row in rows:
        d.line([(x, top), (x + w, top)], fill=LINE)
        top += 12
        d.text((x, top), row["t"], font=f_body, fill=TEXT)
        top += 21
        if row.get("d"):
            top = para(row["d"], f_small, w - 8, SUB, x, top)
        if row.get("n"):
            top = para(row["n"], f_small, w - 8, row.get("nc", SUB), x, top)
        if row.get("c"):
            cx = x
            for label, kind in row["c"]:
                if kind == "toggle":
                    on = kind == "on"
                    d.rounded_rectangle([cx, top + 2, cx + 40, top + 22], radius=10,
                                        fill=ACCENT if on else BG,
                                        outline=None if on else LINE)
                    d.ellipse([cx + 22, top + 4, cx + 38, top + 20], fill=ON_ACCENT)
                    cx += 48
                else:
                    cx = chip(cx, top, label, font=f_small)
            top += 34
        top += 10
    d.line([(x, top), (x + w, top)], fill=LINE)
    return top + 16


# ---------------------------------------------------------------- the header
y = 18
d.text((14, y), "FreeDictate — settings page rebuilt on the Fluent widget set", font=f_title, fill=TEXT)
y += 32
y = para("rust-rewrite/src/ui/pages/settings.rs — the shim that delegated to the legacy view is gone. "
         "The structure below is read off the new file; the app binary was not run (this slice is cargo-only).",
         f_small, W - 28, SUB, 14, y)
y += 10
for label in ("cargo check: pass, no warnings from the file",
              "cargo test: 21 binaries, 160 passed, 0 failed, 18 ignored",
              "41 settings messages bound, none invented",
              "7 sections, Python order and labels"):
    d.rounded_rectangle([14, y, W - 14, y + 30], radius=8, fill=SURFACE)
    d.text((26, y + 8), label, font=f_small, fill=SUB)
    y += 36
panel_top = y + 8

# ------------------------------------------- the section content on a layer
layer = Image.new("RGBA", (W, 6000), (0, 0, 0, 0))
d = ImageDraw.Draw(layer)
content_x = 26 + 168 + 18
content_w = W - content_x - 26
cy = 16
d.text((content_x, cy), "Dictation", font=f_title, fill=TEXT)
cy += 34
d.rounded_rectangle([content_x, cy, content_x + content_w, cy + 74], radius=8,
                    fill="#1f2333", outline="#3d5a8a")
cy = para("Welcome to FreeDictate. Click where you want text, hold Ctrl + Win, talk, and let go. "
          "The Small speech model (487 MB) downloads once, then everything runs offline on this PC.",
          f_small, content_w - 24, TEXT, content_x + 12, cy + 10)
cy += 12

cy = card(content_x, cy, content_w, "Shortcut", [
    {"t": "Dictation shortcut", "d": "Click the box, then press the keys you want.",
     "n": "Ctrl + Win", "c": [("Ctrl + Win", "field"), ("Reset", "field")]},
    {"t": "Stop key",
     "d": "Stops a take at any point: while you talk, or while it's being written out. Click the box, then press the key you want.",
     "c": [("Esc", "field")]},
    {"t": "How the shortcut works", "d": "Hold the shortcut while you talk. Let go to finish.",
     "c": [("Hold", "seg"), ("Press to start and stop", "seg"), ("Both", "seg")]},
])
cy = card(content_x, cy, content_w, "Microphone", [
    {"t": "Microphone", "d": "System default picks the microphone Windows is using.",
     "c": [("System default", "field")]},
    {"t": "Test your microphone", "d": "Speak normally. The bar should reach about halfway."},
])
cy = card(content_x, cy, content_w, "Recording", [
    {"t": "Language", "c": [("Detect automatically", "field")]},
    {"t": "Words it should know", "d": "Helps with names and terms it would otherwise misspell.",
     "c": [("Names, separated by commas", "field")]},
    {"t": "Longest take", "d": "A take this long finishes by itself.",
     "n": "Longest take: 600 (10 seconds to 1 hour)"},
])
cy = card(content_x, cy, content_w, "While I dictate", [
    {"t": "Keep my mic private",
     "d": "Other apps, like calls, can't use the mic while I dictate. If the mic is busy, dictation still works and they keep it."},
    {"t": "Mute other apps' sound",
     "d": "Other apps go quiet while I dictate and come back when I stop. Free Dictate's beeps still play.",
     "n": "These switches apply on the next take."},
    {"t": "What other apps do", "d": "Only applies while the row above is on.",
     "n": "The level below only shows while Mute other apps' sound is on.", "nc": WARN},
])
cy = card(content_x, cy, content_w, "Feedback", [
    {"t": "Sounds", "d": "A short tone when recording starts and stops, and when the text arrives."},
    {"t": "Sound volume", "n": "Sound volume: 50%"},
    {"t": "Recording bar", "d": "A small bar on screen while it listens and transcribes.",
     "c": [("On", "field")]},
])
chip(content_x, cy, "Back", font=f_body, h=30)
content_height = cy + 40

# ------------------------------------------ the panel, the rail, the content
d = ImageDraw.Draw(img)
d.rounded_rectangle([10, panel_top, W - 10, panel_top + content_height], radius=10,
                    fill=PANEL, outline=LINE)
img.paste(layer.crop((0, 0, W, content_height)), (0, panel_top), layer.crop((0, 0, W, content_height)))

rail_x = 26
d.rounded_rectangle([rail_x, panel_top + 16, rail_x + 168, panel_top + 96], radius=8, fill=SURFACE)
d.ellipse([rail_x + 12, panel_top + 30, rail_x + 22, panel_top + 40], fill=OK)
d.text((rail_x + 30, panel_top + 26), "Ready. Hold Ctrl + Win", font=f_small, fill=TEXT)
d.text((rail_x + 30, panel_top + 44), "to dictate", font=f_small, fill=TEXT)
d.text((rail_x + 12, panel_top + 64), "models unloaded", font=f_small, fill=SUB)
chip(rail_x + 12, panel_top + 80, "Pause", font=f_small)

nav = [("mic", "Dictation", True), ("cpu", "Speech model", False),
       ("text", "Text and pasting", False), ("palette", "Appearance", False),
       ("clock", "History", False), ("sliders", "General", False),
       ("info", "About", False)]
ny = panel_top + 112
for glyph, label, selected in nav:
    if selected:
        d.rounded_rectangle([rail_x, ny - 4, rail_x + 168, ny + 26], radius=6, fill=SURFACE)
    d.text((rail_x + 10, ny + 2), glyph, font=f_mono, fill=ACCENT if selected else SUB)
    d.text((rail_x + 20 + d.textlength(glyph, font=f_mono), ny),
           label, font=f_bold if selected else f_body, fill=ACCENT if selected else TEXT)
    ny += 32
d.text((rail_x + 4, panel_top + content_height - 28), "Version 3.6.1", font=f_small, fill=SUB)

# ------------------------------------------------------ the section index
y = panel_top + content_height + 26
d.text((14, y), "Every section and every row", font=f_bold, fill=TEXT)
y += 26
sections = [
    ("general", "mic · Dictation", ["Dictation shortcut", "Stop key", "How the shortcut works",
                                    "Microphone", "Test your microphone", "Language",
                                    "Words it should know", "Stop when you go quiet", "Longest take",
                                    "Keep my mic private", "Mute other apps' sound", "What other apps do",
                                    "Sounds", "Sound volume", "Recording bar", "Bar position",
                                    "Bar material", "Show the timer"]),
    ("models", "cpu · Speech model", ["Speech model", "Model files", "GPU acceleration",
                                      "Run the model on", "Free graphics memory when idle",
                                      "Keep models loaded for", "Silence threshold", "Precision",
                                      "Search width", "Limit processor cores", "Processor cores",
                                      "Skip silent parts"]),
    ("text", "text · Text and pasting", ["How the text arrives", "Keep my clipboard", "Add a space after",
                                         "Capital letter at the start", "Full stop at the end",
                                         "Remove um and uh", "Remove repeated words",
                                         "Spoken punctuation and lists", "\"Submit\" presses Enter",
                                         "Tidy with AI", "Writing model", "Replacements"]),
    ("look", "palette · Appearance", ["Theme", "Accent colour", "Font", "Material", "Tint",
                                      "Keep the effect in the background", "Title bar", "Reduce motion"]),
    ("history", "clock · History", ["Clear all", "Save my dictations", "Delete dictations older than"]),
    ("startup", "sliders · General", ["Start with Windows", "Run as administrator",
                                      "Check for updates automatically", "Include test versions",
                                      "FreeDictate 3.6.1", "Settings and history", "Logs",
                                      "Back up your settings", "Reset all settings"]),
    ("about", "info · About", ["FreeDictate", "Version 3.6.1", "Project page", "Report a problem",
                                "What's new", "Built with"]),
]
for key, label, rows in sections:
    d.text((14, y), key, font=f_mono, fill=ACCENT)
    d.text((14, y + 18), label, font=f_small, fill=SUB)
    half = (len(rows) + 1) // 2
    col_w = (W - 28) // 2
    for col, chunk in enumerate((rows[:half], rows[half:])):
        ry = y
        for row in chunk:
            d.text((190 + col * col_w, ry), "· " + row, font=f_small, fill=SUB)
            ry += 18
    y += max(18 * half, 38) + 12

y += 4
note = ("Read-only rows. The Python page has a control the Rust message set has no variant for. The row is still "
        "shown with the Python wording and the current value as plain text, and the gap is listed in the report: "
        "the stop key, the vocabulary, the silence dropdown, the recording bar switches, the per-model library "
        "buttons, GPU support, the writing model buttons, the word replacements, tint, title bar, reduce motion, "
        "run as administrator, the update switches, open folder, export and import, the history search and list, "
        "and the About links. No message variant was invented.")
lines = wrap(note, f_small, W - 48)
d.rounded_rectangle([10, y, W - 10, y + 24 + len(lines) * 17], radius=8, fill=SURFACE)
para(note, f_small, W - 48, SUB, 24, y + 12)
y += 24 + len(lines) * 17 + 10

img = img.crop((0, 0, W, y))
out = "H:/System Configuration/work/repo-standard/freedictate/reports/settings-page-structure.png"
img.save(out, "PNG")
print("saved", out, img.size)
