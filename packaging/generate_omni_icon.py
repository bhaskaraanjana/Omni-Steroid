"""Render the Omni logo mark into the app icon set (.ico + PNG sizes).

Purpose: turns the in-app brand mark (apps/ui/src/components/omni-mark.tsx —
overlapping fluid wave rings + ink core on Daylight teal/cyan/indigo) into
the static icon files Tauri and PyInstaller consume. Build-time tool only —
Pillow is an analysis/build dependency, never a runtime one (run via
`uv run --no-project --with pillow python packaging/generate_omni_icon.py`).
Pipeline position: run manually (or in CI) before `tauri build` /
`pyinstaller`; outputs land in apps/ui/src-tauri/icons/ and packaging/.

No security surface: pure local rendering, no input, no network.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# Daylight brand colours (tokens.css --accent family + omni-mark accents).
CANVAS = (247, 245, 240, 255)  # soft paper — readable on Windows taskbar
ACCENT = (0, 104, 85, 200)  # --accent ≈ #006855
CYAN = (6, 182, 212, 170)  # #06b6d4
INDIGO = (99, 102, 241, 150)  # #6366f1
RING = (214, 212, 206, 255)  # grey-200-ish boundary
CORE = (28, 27, 24, 255)  # --ink

VIEWBOX = 100.0
SUPERSAMPLE = 1024

REPO_ROOT = Path(__file__).resolve().parent.parent
TAURI_ICONS_DIR = REPO_ROOT / "apps" / "ui" / "src-tauri" / "icons"
PACKAGING_DIR = REPO_ROOT / "packaging"


def render_mark(canvas_px: int) -> Image.Image:
    """Static wave-ring mark at `canvas_px` square on a soft Daylight tile."""
    scale = SUPERSAMPLE / VIEWBOX
    image = Image.new("RGBA", (SUPERSAMPLE, SUPERSAMPLE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")

    # Rounded square tile so the taskbar icon is not a floating blob.
    pad = 4 * scale
    radius = 22 * scale
    draw.rounded_rectangle(
        (pad, pad, SUPERSAMPLE - pad, SUPERSAMPLE - pad),
        radius=radius,
        fill=CANVAS,
    )

    # Soft outer ring.
    ring_pad = 14 * scale
    draw.ellipse(
        (ring_pad, ring_pad, SUPERSAMPLE - ring_pad, SUPERSAMPLE - ring_pad),
        outline=RING,
        width=max(2, round(1.5 * scale)),
    )

    # Three translucent overlapping ellipses — static stand-in for the waves.
    layers = (
        (ACCENT, (18, 16, 82, 84)),
        (CYAN, (22, 20, 78, 80)),
        (INDIGO, (26, 24, 74, 76)),
    )
    for fill, box in layers:
        x0, y0, x1, y1 = (v * scale for v in box)
        draw.ellipse((x0, y0, x1, y1), fill=fill)

    # Central ink core.
    cx = cy = 50.0 * scale
    r = 7.0 * scale
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=CORE)

    return image.resize((canvas_px, canvas_px), Image.LANCZOS)


def main() -> None:
    """Write the Tauri icon set + the PyInstaller .ico."""
    TAURI_ICONS_DIR.mkdir(parents=True, exist_ok=True)

    render_mark(32).save(TAURI_ICONS_DIR / "32x32.png")
    render_mark(128).save(TAURI_ICONS_DIR / "128x128.png")
    render_mark(256).save(TAURI_ICONS_DIR / "128x128@2x.png")
    render_mark(512).save(TAURI_ICONS_DIR / "icon.png")

    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base = render_mark(256)
    base.save(TAURI_ICONS_DIR / "icon.ico", sizes=ico_sizes)
    base.save(PACKAGING_DIR / "omni-engine.ico", sizes=ico_sizes)

    print(f"wrote icons to {TAURI_ICONS_DIR} and {PACKAGING_DIR / 'omni-engine.ico'}")


if __name__ == "__main__":
    main()
