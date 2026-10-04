"""Vector-ish artwork for the Vet Soap Notetaker logo: a cute dog holding a notepad.

Two renderings come out of ``render_logo``:

* the **brand logo** (``accent=None``) — the dog holding a notepad, used for the
  static window / taskbar / .exe icon; and
* the **tray icon** (``accent`` set to a colour) — the same dog, but the notepad
  is swapped for a big green/red/yellow status disc so the pipeline state
  (idle / recording / processing) reads at a glance even at 16px.

Everything is drawn on a 4x supersampled canvas and then downscaled with
LANCZOS, which keeps the small tray/taskbar renderings crisp. ``STATUS_SAMPLE``
(in 0..1 canvas coordinates) points at the centre of the status disc, whose
flat fill survives the downscale, which is what the tray-icon state tests
sample.
"""

from PIL import Image, ImageDraw

# Centre of the tray status disc, in fractions of the icon's width/height.
# Sampling here yields (very close to) the accent colour, which the state-colour
# tests rely on.
STATUS_SAMPLE = (0.75, 0.74)

_SUPERSAMPLE = 4

# Palette for a friendly golden/tan dog.
_FUR = (240, 200, 130, 255)
_EAR = (176, 122, 66, 255)
_MUZZLE = (252, 232, 196, 255)
_NOSE = (60, 44, 40, 255)
_EYE = (56, 42, 38, 255)
_WHITE = (255, 255, 255, 255)
_PAPER = (250, 250, 248, 255)
_PAPER_EDGE = (208, 208, 200, 255)
_LINE = (150, 176, 210, 255)
_OUTLINE = (108, 74, 44, 255)
# The brand logo's collar (decorative); the tray keeps a plain brown collar so
# only the status disc carries colour.
_COLLAR_BRAND = (70, 130, 180, 255)
_COLLAR_PLAIN = (150, 104, 58, 255)


def _rgba(color):
    """Accept a PIL colour name or an RGB(A) tuple, return an RGBA tuple."""
    if isinstance(color, str):
        img = Image.new("RGBA", (1, 1), color)
        return img.getpixel((0, 0))
    if len(color) == 3:
        return (*color, 255)
    return color


def render_logo(size: int, accent=None) -> Image.Image:
    """Render the dog logo at ``size`` px.

    ``accent`` ``None`` draws the brand logo (dog + notepad). Passing a colour
    draws the tray variant, replacing the notepad with a status disc of that
    colour.
    """
    s = size * _SUPERSAMPLE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return (x0 * s, y0 * s, x1 * s, y1 * s)

    lw = max(1, round(s * 0.012))
    collar = _COLLAR_BRAND if accent is None else _COLLAR_PLAIN

    # --- Ears (drawn first so the head overlaps their inner edge) ---
    d.ellipse(box(0.06, 0.24, 0.30, 0.62), fill=_EAR, outline=_OUTLINE, width=lw)
    d.ellipse(box(0.70, 0.24, 0.94, 0.62), fill=_EAR, outline=_OUTLINE, width=lw)

    # --- Collar band (behind the head) ---
    d.rounded_rectangle(
        box(0.16, 0.62, 0.84, 0.84), radius=s * 0.05, fill=collar, outline=_OUTLINE, width=lw
    )
    # A little tag hanging off the collar.
    d.ellipse(box(0.46, 0.80, 0.54, 0.90), fill=(255, 214, 92, 255), outline=_OUTLINE, width=lw)

    # --- Head ---
    d.ellipse(box(0.16, 0.14, 0.84, 0.72), fill=_FUR, outline=_OUTLINE, width=lw)

    # --- Muzzle ---
    d.ellipse(box(0.34, 0.40, 0.66, 0.68), fill=_MUZZLE, outline=_OUTLINE, width=lw)

    # --- Eyes (with highlight) ---
    for cx in (0.37, 0.63):
        d.ellipse(box(cx - 0.055, 0.32, cx + 0.055, 0.44), fill=_EYE)
        d.ellipse(box(cx - 0.01, 0.34, cx + 0.03, 0.38), fill=_WHITE)

    # --- Nose ---
    d.ellipse(box(0.44, 0.47, 0.56, 0.56), fill=_NOSE)
    d.ellipse(box(0.465, 0.485, 0.5, 0.515), fill=(120, 100, 96, 255))

    if accent is None:
        _draw_notepad(d, box, s, lw)
    else:
        _draw_status_disc(d, box, s, lw, _rgba(accent))

    return img.resize((size, size), Image.LANCZOS)


def _draw_notepad(d, box, s, lw):
    """The brand logo's notepad, tucked at the lower-right as if held up."""
    d.rounded_rectangle(
        box(0.58, 0.58, 0.96, 0.95), radius=s * 0.02, fill=_PAPER, outline=_PAPER_EDGE, width=lw
    )
    # Spiral binding across the top.
    for i in range(5):
        x = 0.62 + i * 0.07
        d.line((x * s, 0.565 * s, x * s, 0.615 * s), fill=_OUTLINE, width=max(1, round(s * 0.01)))
    # Ruled lines.
    for j in range(4):
        y = 0.68 + j * 0.06
        d.line((0.63 * s, y * s, 0.91 * s, y * s), fill=_LINE, width=max(1, round(s * 0.012)))


def _draw_status_disc(d, box, s, lw, accent):
    """The tray variant's state disc, in the notepad's lower-right spot."""
    d.ellipse(box(0.56, 0.55, 0.96, 0.95), fill=accent, outline=_OUTLINE, width=lw)
    # A soft highlight so the disc reads as a glossy dot, not a flat blob.
    d.ellipse(box(0.62, 0.60, 0.72, 0.68), fill=(255, 255, 255, 90))
