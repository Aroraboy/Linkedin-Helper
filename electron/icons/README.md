This directory holds the app icons for the Electron build.

Required files:

- icon.icns — macOS app icon (1024x1024 recommended)
- icon.png — Fallback icon (512x512 or 1024x1024 PNG)

How to create icon.icns from a PNG:

1. Start with a 1024x1024 PNG image named "icon.png"

2. Create the iconset folder:
   mkdir icon.iconset

3. Generate all required sizes:
   sips -z 16 16 icon.png --out icon.iconset/icon_16x16.png
   sips -z 32 32 icon.png --out icon.iconset/icon_16x16@2x.png
   sips -z 32 32 icon.png --out icon.iconset/icon_32x32.png
   sips -z 64 64 icon.png --out icon.iconset/icon_32x32@2x.png
   sips -z 128 128 icon.png --out icon.iconset/icon_128x128.png
   sips -z 256 256 icon.png --out icon.iconset/icon_128x128@2x.png
   sips -z 256 256 icon.png --out icon.iconset/icon_256x256.png
   sips -z 512 512 icon.png --out icon.iconset/icon_256x256@2x.png
   sips -z 512 512 icon.png --out icon.iconset/icon_512x512.png
   sips -z 1024 1024 icon.png --out icon.iconset/icon_512x512@2x.png

4. Convert to icns:
   iconutil -c icns icon.iconset

5. Copy icon.icns and icon.png to this directory.

Note: If you skip this, electron-builder will use a default icon.
