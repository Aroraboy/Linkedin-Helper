#!/usr/bin/env bash
#
# build_python.sh — Bundle the Python/Flask backend with PyInstaller
#
# Run this on macOS BEFORE running electron-builder.
# It creates a standalone Python app in electron/python_dist/
#
# Usage:
#   cd <project-root>
#   chmod +x electron/build_python.sh
#   ./electron/build_python.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_DIST="$SCRIPT_DIR/python_dist"

echo "============================================="
echo "  LinkedIn Helper — Python Bundle Builder"
echo "============================================="
echo ""

# ─── Step 1: Create/activate a clean virtual environment ─────────────────────
VENV_DIR="$PROJECT_ROOT/.build_venv"

if [ -d "$VENV_DIR" ]; then
    echo "[1/6] Removing old build venv..."
    rm -rf "$VENV_DIR"
fi

echo "[1/6] Creating clean virtual environment..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# ─── Step 2: Install dependencies ────────────────────────────────────────────
echo "[2/6] Installing Python dependencies..."
pip install --upgrade pip setuptools wheel
pip install -r "$PROJECT_ROOT/requirements.txt"
pip install pyinstaller

# ─── Step 3: Install Playwright browsers ─────────────────────────────────────
echo "[3/6] Installing Playwright Chromium browser..."
python -m playwright install chromium

# Find where Playwright installed the browser
PLAYWRIGHT_BROWSERS=$(python -c "import playwright; import os; print(os.path.join(os.path.dirname(playwright.__file__), 'driver', 'package', '.local-browsers'))" 2>/dev/null || true)

if [ -z "$PLAYWRIGHT_BROWSERS" ] || [ ! -d "$PLAYWRIGHT_BROWSERS" ]; then
    # Try the default location
    PLAYWRIGHT_BROWSERS="$HOME/Library/Caches/ms-playwright"
fi

echo "   Playwright browsers at: $PLAYWRIGHT_BROWSERS"

# ─── Step 4: Clean old builds ────────────────────────────────────────────────
echo "[4/6] Cleaning previous builds..."
rm -rf "$PYTHON_DIST"
rm -rf "$PROJECT_ROOT/build"
rm -rf "$PROJECT_ROOT/dist"
rm -f "$PROJECT_ROOT/linkedin_helper.spec"

# ─── Step 5: Run PyInstaller ─────────────────────────────────────────────────
echo "[5/6] Running PyInstaller..."

cd "$PROJECT_ROOT"

pyinstaller \
    --name linkedin_helper \
    --distpath "$PYTHON_DIST" \
    --workpath "$PROJECT_ROOT/build/pyinstaller" \
    --noconfirm \
    --log-level WARN \
    \
    --add-data "web/templates:web/templates" \
    --add-data "web/static:web/static" \
    --add-data "templates:templates" \
    --add-data "config.py:." \
    --add-data "app.py:." \
    --add-data "db.py:." \
    --add-data "logger.py:." \
    --add-data "linkedin_bot.py:." \
    --add-data "spreadsheet_reader.py:." \
    --add-data "web/__init__.py:web" \
    --add-data "web/models.py:web" \
    --add-data "web/auth.py:web" \
    --add-data "web/dashboard.py:web" \
    --add-data "web/forms.py:web" \
    --add-data "web/worker.py:web" \
    --add-data "web/linkedin_auth.py:web" \
    --add-data "web/interactive_login.py:web" \
    --add-data "requirements.txt:." \
    \
    --hidden-import flask \
    --hidden-import flask_login \
    --hidden-import flask_sqlalchemy \
    --hidden-import flask_wtf \
    --hidden-import wtforms \
    --hidden-import email_validator \
    --hidden-import sqlalchemy \
    --hidden-import sqlalchemy.dialects.sqlite \
    --hidden-import playwright \
    --hidden-import playwright.sync_api \
    --hidden-import openpyxl \
    --hidden-import gspread \
    --hidden-import google.auth \
    --hidden-import rich \
    --hidden-import dotenv \
    --hidden-import jinja2 \
    --hidden-import markupsafe \
    --hidden-import werkzeug \
    --hidden-import click \
    --hidden-import itsdangerous \
    --hidden-import blinker \
    --hidden-import greenlet \
    --hidden-import app \
    --hidden-import config \
    --hidden-import db \
    --hidden-import logger \
    --hidden-import linkedin_bot \
    --hidden-import spreadsheet_reader \
    --hidden-import web \
    --hidden-import web.models \
    --hidden-import web.auth \
    --hidden-import web.dashboard \
    --hidden-import web.forms \
    --hidden-import web.worker \
    --hidden-import web.linkedin_auth \
    --hidden-import web.interactive_login \
    \
    --collect-all playwright \
    \
    "$SCRIPT_DIR/pyinstaller_entry.py"

# ─── Step 6: Copy Playwright browsers alongside the bundle ───────────────────
echo "[6/6] Copying Playwright Chromium browser..."

BROWSERS_DEST="$PYTHON_DIST/playwright_browsers"
mkdir -p "$BROWSERS_DEST"

# Copy only Chromium (not Firefox/WebKit) to save space
if [ -d "$PLAYWRIGHT_BROWSERS" ]; then
    CHROMIUM_DIR=$(find "$PLAYWRIGHT_BROWSERS" -maxdepth 1 -type d -name "chromium-*" | head -1)
    if [ -n "$CHROMIUM_DIR" ]; then
        echo "   Copying Chromium from: $CHROMIUM_DIR"
        cp -R "$CHROMIUM_DIR" "$BROWSERS_DEST/"
        echo "   Chromium copied successfully"
    else
        echo "   WARNING: Chromium directory not found in $PLAYWRIGHT_BROWSERS"
        ls -la "$PLAYWRIGHT_BROWSERS" || true
    fi
else
    echo "   WARNING: Playwright browsers directory not found"
fi

# ─── Cleanup ─────────────────────────────────────────────────────────────────
deactivate 2>/dev/null || true
rm -rf "$PROJECT_ROOT/build"
rm -f "$PROJECT_ROOT/linkedin_helper.spec"

# ─── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "============================================="
echo "  Python bundle created successfully!"
echo "============================================="
echo ""
echo "  Bundle location: $PYTHON_DIST"
echo "  Bundle size: $(du -sh "$PYTHON_DIST" | cut -f1)"
echo ""
echo "  Next step: Run 'npm run build' in the electron/ directory"
echo "             to package the Electron app."
echo ""
