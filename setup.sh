#!/bin/bash
# setup.sh – run this once to install the tennis booker
set -e

PLIST="$HOME/Library/LaunchAgents/com.jackbreslauer.tennis.plist"
SCRIPT_DIR="$HOME/tennis"

echo "=== Prospect Park Tennis Auto-Booker Setup ==="
echo ""

# 1. Check Python + Playwright
echo "Checking dependencies..."
if ! python3 -c "import playwright" 2>/dev/null; then
    echo "  Installing playwright..."
    pip3 install playwright
    python3 -m playwright install chromium
else
    echo "  Playwright OK"
fi

# 2. Register launchd job
echo ""
echo "Registering launchd job (runs at midnight daily)..."
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST"
echo "  Registered: com.jackbreslauer.tennis"

# 4. Schedule Mac wake at 11:58 PM nightly so it's awake at midnight
echo ""
echo "Configuring Mac to wake at 11:58 PM nightly..."
echo "(This lets the Mac sleep during the day and still run the script at midnight)"
sudo pmset repeat wakeorpoweron MTWRFSU 23:58:00
echo "  Wake schedule set."

# 5. Verify launchd job
echo ""
echo "=== Setup Complete ==="
echo ""
echo "The booker will:"
echo "  • Wake your Mac at 11:58 PM each night"
echo "  • Run at midnight"
echo "  • Book a Clay court Mon–Thu, 6–8 PM, 7 days in advance"
echo "  • Send a macOS notification on success or failure"
echo ""
echo "To test it RIGHT NOW (without waiting for midnight):"
echo "  python3 $SCRIPT_DIR/book_tennis.py"
echo ""
echo "To uninstall:"
echo "  launchctl unload $PLIST"
echo "  sudo pmset repeat cancel"
echo ""
echo "Logs: $SCRIPT_DIR/logs/"
