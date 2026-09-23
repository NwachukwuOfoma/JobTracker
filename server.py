import sys
import json
import time
import os
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import subprocess

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from jobs import run_fetch_pipeline

PORT = 5050
HOST = "127.0.0.1"

# Concurrency & state tracking
fetch_lock = threading.Lock()
is_fetching = False
last_fetch_info = {
    "timestamp": None,
    "brand_new_added": 0,
    "total_unvisited": 0,
    "status": "idle"
}

class JobTrackerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self.path = "/new_jobs.html"
            return super().do_GET()

        if path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            response_data = {
                "status": "ok",
                "is_fetching": is_fetching,
                "last_fetch": last_fetch_info
            }
            self.wfile.write(json.dumps(response_data).encode("utf-8"))
            return

        if path == "/api/fetch":
            # Allow triggering via GET as well for simple browser testing
            self.handle_fetch_request(parsed)
            return

        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/fetch":
            self.handle_fetch_request(parsed)
            return

        self.send_response(404)
        self._send_cors_headers()
        self.end_headers()

    def handle_fetch_request(self, parsed):
        global is_fetching, last_fetch_info

        query_params = parse_qs(parsed.query)
        force_refresh = query_params.get("refresh", ["false"])[0].lower() in ("true", "1", "yes")

        # Non-blocking lock check
        if not fetch_lock.acquire(blocking=False):
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "busy",
                "message": "A fetch is already in progress. Please wait."
            }).encode("utf-8"))
            return

        try:
            is_fetching = True
            last_fetch_info["status"] = "running"
            
            # Execute pipeline
            result = run_fetch_pipeline(force_refresh=force_refresh, print_output=True)
            
            last_fetch_info = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "brand_new_added": result["brand_new_added"],
                "total_unvisited": result["total_unvisited"],
                "status": "success"
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "success",
                "data": result
            }).encode("utf-8"))

        except Exception as e:
            last_fetch_info["status"] = "error"
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "error",
                "message": str(e)
            }).encode("utf-8"))

        finally:
            is_fetching = False
            fetch_lock.release()

def install_launchd_service():
    """Configures macOS launchd to run the server in the background automatically on login."""
    plist_dir = Path(os.path.expanduser("~/Library/LaunchAgents"))
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "com.jobtracker.server.plist"

    python_bin = sys.executable
    server_script = str(BASE_DIR / "server.py")
    log_out = str(BASE_DIR / "logs" / "server_stdout.log")
    log_err = str(BASE_DIR / "logs" / "server_stderr.log")

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jobtracker.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_bin}</string>
        <string>{server_script}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{str(BASE_DIR)}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_out}</string>
    <key>StandardErrorPath</key>
    <string>{log_err}</string>
</dict>
</plist>
"""
    with open(plist_path, "w", encoding="utf-8") as f:
        f.write(plist_content)

    print(f"Created launchd agent configuration at:\n  {plist_path}")
    try:
        subprocess.run(["launchctl", "unload", str(plist_path)], stderr=subprocess.DEVNULL)
        subprocess.run(["launchctl", "load", "-w", str(plist_path)], check=True)
        print("Successfully loaded background service! Server is now active on port 5050.")
    except Exception as e:
        print(f"Warning: Could not load service automatically: {e}")
        print(f"Run manually: launchctl load -w {plist_path}")

def uninstall_launchd_service():
    plist_path = Path(os.path.expanduser("~/Library/LaunchAgents/com.jobtracker.server.plist"))
    if plist_path.exists():
        try:
            subprocess.run(["launchctl", "unload", str(plist_path)], stderr=subprocess.DEVNULL)
        except Exception:
            pass
        plist_path.unlink()
        print("Background service uninstalled successfully.")
    else:
        print("No background service plist found.")

if __name__ == "__main__":
    if "--install-service" in sys.argv:
        install_launchd_service()
        sys.exit(0)
    elif "--uninstall-service" in sys.argv:
        uninstall_launchd_service()
        sys.exit(0)

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((HOST, PORT), JobTrackerHandler)
    print(f"\n==========================================")
    print(f"🚀 JobTracker Server running on http://{HOST}:{PORT}")
    print(f"👉 Dashboard: http://{HOST}:{PORT}/new_jobs.html")
    print(f"👉 API Endpoint: http://{HOST}:{PORT}/api/fetch")
    print(f"Press Ctrl+C to stop.")
    print(f"==========================================\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        server.server_close()
