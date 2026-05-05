import textwrap
import random
import os
import tempfile
from PIL import Image, ImageDraw, ImageFont

# ─── COLOR THEMES ─────────────────────────────────────────────────────────────
THEMES = [
    {"bg": "#CC0000", "text": "#FFFFFF", "accent": "#FF6666"},  # Red (like sample)
    {"bg": "#1A1A2E", "text": "#FFFFFF", "accent": "#E94560"},  # Dark Navy + Red
    {"bg": "#0F3460", "text": "#FFFFFF", "accent": "#F5A623"},  # Deep Blue + Gold
    {"bg": "#16213E", "text": "#F5A623", "accent": "#FFFFFF"},  # Dark + Gold text
    {"bg": "#1B4332", "text": "#FFFFFF", "accent": "#52B788"},  # Dark Green
    {"bg": "#212529", "text": "#FFFFFF", "accent": "#FFC107"},  # Charcoal + Yellow
]

FONT_BOLD   = "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"

# Fallback fonts
FALLBACK_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FALLBACK_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def get_font(path: str, fallback: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except:
        try:
            return ImageFont.truetype(fallback, size)
        except:
            return ImageFont.load_default()


def wrap_text(text: str, font, max_width: int, draw) -> list[str]:
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def generate_image(main_text: str, sub_text: str = "") -> str:
    """
    Generate a clean, attention-grabbing image like the sample.
    Returns path to saved temp JPEG file.
    """
    W, H = 1200, 630
    theme = random.choice(THEMES)

    bg_rgb   = hex_to_rgb(theme["bg"])
    text_rgb = hex_to_rgb(theme["text"])
    acc_rgb  = hex_to_rgb(theme["accent"])

    img  = Image.new("RGB", (W, H), color=bg_rgb)
    draw = ImageDraw.Draw(img)

    # ── Subtle accent bar at top and bottom ──────────────────────────────────
    bar_h = 8
    for x in range(W):
        draw.point((x, bar_h // 2), fill=acc_rgb)
        draw.point((x, H - bar_h // 2), fill=acc_rgb)

    # ── Main text ─────────────────────────────────────────────────────────────
    font_main = get_font(FONT_BOLD, FALLBACK_BOLD, 80)
    padding   = 100
    max_w     = W - padding * 2

    lines = wrap_text(main_text, font_main, max_w, draw)

    # Calculate total text block height
    line_h     = 90
    total_h    = len(lines) * line_h
    sub_h      = 50 if sub_text else 0
    block_h    = total_h + sub_h + (20 if sub_text else 0)
    start_y    = (H - block_h) // 2

    # Draw each line centered
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font_main)
        lw   = bbox[2] - bbox[0]
        x    = (W - lw) // 2
        y    = start_y + i * line_h

        # Subtle shadow
        draw.text((x + 2, y + 2), line, fill=(0, 0, 0, 80), font=font_main)
        draw.text((x, y), line, fill=text_rgb, font=font_main)

    # ── Sub text ──────────────────────────────────────────────────────────────
    if sub_text:
        font_sub = get_font(FONT_REGULAR, FALLBACK_REG, 42)
        bbox     = draw.textbbox((0, 0), sub_text, font=font_sub)
        sw       = bbox[2] - bbox[0]
        sx       = (W - sw) // 2
        sy       = start_y + total_h + 20
        draw.text((sx, sy), sub_text, fill=acc_rgb, font=font_sub)

    # ── Save ──────────────────────────────────────────────────────────────────
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    img.save(tmp.name, "JPEG", quality=95)
    tmp.close()
    return tmp.name
