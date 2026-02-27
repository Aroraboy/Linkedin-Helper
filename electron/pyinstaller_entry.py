"""
PyInstaller entry point for the LinkedIn Helper Electron app.
This wraps the Flask app to run as a standalone executable.
"""

import os
import sys
import signal

def main():
    # Ensure we're running from the right directory
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        base_dir = sys._MEIPASS
        # Add the bundle dir to Python path so all modules are found
        if base_dir not in sys.path:
            sys.path.insert(0, base_dir)
        os.chdir(base_dir)
        
        # Set PLAYWRIGHT_BROWSERS_PATH if not already set
        if 'PLAYWRIGHT_BROWSERS_PATH' not in os.environ:
            # Look for browsers alongside the frozen app
            browsers_path = os.path.join(os.path.dirname(sys.executable), '..', 'playwright_browsers')
            if os.path.isdir(browsers_path):
                os.environ['PLAYWRIGHT_BROWSERS_PATH'] = os.path.abspath(browsers_path)
    
    # Set port from environment (Electron passes this)
    port = int(os.environ.get('PORT', '5000'))
    
    # Import and create the Flask app
    from app import create_app
    app = create_app()
    
    # Handle SIGTERM gracefully
    def handle_sigterm(signum, frame):
        print("[PyInstaller] Received SIGTERM, shutting down...")
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, handle_sigterm)
    
    # Run the Flask server
    print(f"[PyInstaller] Starting Flask server on port {port}")
    app.run(
        host='127.0.0.1',
        port=port,
        debug=False,
        use_reloader=False,  # IMPORTANT: no reloader in frozen app
        threaded=True,
    )

if __name__ == '__main__':
    main()
