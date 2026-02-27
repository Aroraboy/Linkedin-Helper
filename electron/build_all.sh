#!/usr/bin/env bash
#
# build_all.sh — Complete build: Python bundle + Electron app
#
# This is the ONE script to run on the founder's Mac (or any Mac
# with Node.js and Python3 installed) to produce a .dmg installer.
#
# Prerequisites:
#   - macOS (Intel or Apple Silicon)
#   - Python 3.10+ installed (brew install python3)
#   - Node.js 18+ installed (brew install node)
#
# Usage:
#   cd <project-root>/electron
#   chmod +x build_all.sh build_python.sh
#   ./build_all.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║   LinkedIn Helper — Full Build Pipeline       ║"
echo "╠═══════════════════════════════════════════════╣"
echo "║  Step 1: Bundle Python backend (PyInstaller)  ║"
echo "║  Step 2: Install Electron dependencies        ║"
echo "║  Step 3: Build macOS .dmg (electron-builder)  ║"
echo "╚═══════════════════════════════════════════════╝"
echo ""

# ─── Pre-flight checks ──────────────────────────────────────────────────────
echo "Pre-flight checks..."

if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found. Install with: brew install python3"
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo "ERROR: node not found. Install with: brew install node"
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo "ERROR: npm not found. Install with: brew install node"
    exit 1
fi

echo "  ✓ Python3: $(python3 --version)"
echo "  ✓ Node.js: $(node --version)"
echo "  ✓ npm:     $(npm --version)"
echo ""

# ─── Step 1: Bundle Python ──────────────────────────────────────────────────
echo "═══════════════════════════════════════════════"
echo "  Step 1/3: Bundling Python backend..."
echo "═══════════════════════════════════════════════"
echo ""

bash "$SCRIPT_DIR/build_python.sh"

# Verify bundle was created
if [ ! -d "$SCRIPT_DIR/python_dist/linkedin_helper" ]; then
    echo "ERROR: Python bundle not found at $SCRIPT_DIR/python_dist/linkedin_helper"
    exit 1
fi
echo "  ✓ Python bundle ready"
echo ""

# ─── Step 2: Install Electron dependencies ──────────────────────────────────
echo "═══════════════════════════════════════════════"
echo "  Step 2/3: Installing Electron dependencies..."
echo "═══════════════════════════════════════════════"
echo ""

cd "$SCRIPT_DIR"
npm install
echo "  ✓ Electron dependencies installed"
echo ""

# ─── Step 3: Build Electron app ─────────────────────────────────────────────
echo "═══════════════════════════════════════════════"
echo "  Step 3/3: Building macOS .dmg..."
echo "═══════════════════════════════════════════════"
echo ""

npx electron-builder --mac --publish never

echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║           BUILD COMPLETE! 🎉                  ║"
echo "╚═══════════════════════════════════════════════╝"
echo ""
echo "  Your .dmg installer is at:"
echo "  $SCRIPT_DIR/dist/"
echo ""
ls -lh "$SCRIPT_DIR/dist/"*.dmg 2>/dev/null || echo "  (check dist/ folder)"
echo ""
echo "  To install: Double-click the .dmg, then drag"
echo "  LinkedIn Helper to the Applications folder."
echo ""
