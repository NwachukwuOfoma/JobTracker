#!/bin/bash
# Sets up JobTracker background server to run on login
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

python server.py --install-service
echo ""
echo "Setup complete! You can open http://localhost:5050 in Chrome."
