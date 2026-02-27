# LinkedIn Helper — Desktop App Build Guide

## Overview

This guide builds a standalone **macOS desktop app** (.dmg installer) that bundles everything:

- Python runtime + all pip packages
- Flask web server
- Playwright + Chromium browser
- Electron desktop shell

The founder just **installs the .dmg** and double-clicks to run. No Python, Node.js, or terminal needed.

---

## Prerequisites (Build Machine Only)

You need these installed **only on the machine where you build** the app.
The resulting .dmg has everything self-contained.

### 1. Install Homebrew (if not installed)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. Install Python 3.10+

```bash
brew install python3
python3 --version   # Should show 3.10 or higher
```

### 3. Install Node.js 18+

```bash
brew install node
node --version   # Should show 18 or higher
npm --version
```

---

## Build Steps

### Step 1: Clone the repo

```bash
git clone https://github.com/Aroraboy/Linkedin-Helper.git
cd Linkedin-Helper
```

### Step 2: Run the one-command build

```bash
cd electron
chmod +x build_all.sh build_python.sh
./build_all.sh
```

This will:

1. Create a clean Python virtual environment
2. Install all pip dependencies
3. Install Playwright Chromium browser
4. Bundle Python + dependencies with PyInstaller
5. Install Electron + electron-builder
6. Package everything into a macOS .dmg

**Build time:** ~5–10 minutes (depending on internet speed)

### Step 3: Find your installer

The .dmg file will be at:

```
electron/dist/LinkedIn Helper-1.0.0-universal.dmg
```

---

## Installing on the Founder's MacBook

1. **Double-click** the `.dmg` file
2. **Drag** "LinkedIn Helper" to the Applications folder
3. **Open** LinkedIn Helper from Applications
4. If macOS shows "unidentified developer" warning:
   - Go to **System Preferences → Privacy & Security**
   - Click **"Open Anyway"** next to the LinkedIn Helper message
   - Or: Right-click the app → Open → Open

---

## Using the App

1. Launch **LinkedIn Helper** from Applications
2. **Register** an account (first time only, local to your Mac)
3. Go to **Settings** → **Login in Browser** to log into LinkedIn
4. **Upload** a CSV/XLSX with LinkedIn profile URLs
5. Choose mode: **Connect**, **Connect + Note**, or **Message**
6. Click **Start** and watch the progress!

---

## App Data Location

All data (database, settings) is stored at:

```
~/Library/Application Support/linkedin-helper/
```

---

## Troubleshooting

### "App is damaged and can't be opened"

```bash
xattr -cr /Applications/LinkedIn\ Helper.app
```

### The app won't start

Check the console log:

```bash
/Applications/LinkedIn\ Helper.app/Contents/MacOS/LinkedIn\ Helper --no-sandbox
```

### Chromium crashes

The app needs ~1GB of free RAM. Close other apps if needed.

---

## Custom App Icon (Optional)

To replace the default icon:

1. Place a 1024×1024 PNG as `electron/icons/icon.png`
2. Run: `cd electron && python3 generate_icon.py`
3. Rebuild: `./build_all.sh`

Or use the automated generator:

```bash
cd electron
pip3 install Pillow
python3 generate_icon.py
```
