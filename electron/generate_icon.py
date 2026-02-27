#!/usr/bin/env python3
"""
generate_icon.py — Generate a simple LinkedIn Helper app icon.
Run on macOS to create icon.icns from a generated PNG.

Usage:
    pip3 install Pillow
    python3 generate_icon.py
"""

import sys
import os
import subprocess

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Installing Pillow...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image, ImageDraw, ImageFont

ICON_SIZE = 1024
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICONS_DIR = os.path.join(SCRIPT_DIR, "icons")

def create_icon():
    """Create a simple LinkedIn Helper icon."""
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Rounded rectangle background (LinkedIn blue)
    margin = 50
    radius = 180
    bg_color = (0, 119, 181)  # LinkedIn blue
    
    # Draw rounded rect
    x0, y0 = margin, margin
    x1, y1 = ICON_SIZE - margin, ICON_SIZE - margin
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=bg_color)
    
    # Draw "in" text (LinkedIn style)
    try:
        # Try to use a system font
        font_large = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 480)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 200)
    except (OSError, IOError):
        try:
            font_large = ImageFont.truetype("arial.ttf", 480)
            font_small = ImageFont.truetype("arial.ttf", 200)
        except (OSError, IOError):
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()
    
    # Draw "in" centered
    text = "in"
    bbox = draw.textbbox((0, 0), text, font=font_large)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (ICON_SIZE - text_w) // 2
    text_y = (ICON_SIZE - text_h) // 2 - 40
    draw.text((text_x, text_y), text, fill="white", font=font_large)
    
    # Draw small "H" for Helper  
    h_text = "H"
    bbox2 = draw.textbbox((0, 0), h_text, font=font_small)
    h_w = bbox2[2] - bbox2[0]
    h_x = ICON_SIZE - margin - h_w - 30
    h_y = ICON_SIZE - margin - 220
    draw.text((h_x, h_y), h_text, fill=(255, 255, 255, 180), font=font_small)
    
    # Save PNG
    png_path = os.path.join(ICONS_DIR, "icon.png")
    img.save(png_path, "PNG")
    print(f"Saved: {png_path}")
    
    # On macOS, also create .icns
    if sys.platform == "darwin":
        create_icns(png_path)
    
    return png_path

def create_icns(png_path):
    """Convert PNG to .icns on macOS."""
    iconset_dir = os.path.join(ICONS_DIR, "icon.iconset")
    os.makedirs(iconset_dir, exist_ok=True)
    
    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    
    img = Image.open(png_path)
    for size, name in sizes:
        resized = img.resize((size, size), Image.LANCZOS)
        resized.save(os.path.join(iconset_dir, name), "PNG")
    
    # Use iconutil to create .icns
    icns_path = os.path.join(ICONS_DIR, "icon.icns")
    try:
        subprocess.check_call(["iconutil", "-c", "icns", iconset_dir, "-o", icns_path])
        print(f"Saved: {icns_path}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("WARNING: iconutil not found. icon.icns not created.")
        print("         This is fine — electron-builder will use icon.png as fallback.")
    
    # Cleanup iconset
    import shutil
    shutil.rmtree(iconset_dir, ignore_errors=True)

if __name__ == "__main__":
    os.makedirs(ICONS_DIR, exist_ok=True)
    create_icon()
    print("\nDone! Icon files are in the icons/ directory.")
