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

# 2. Prompt for Gmail App Password
echo ""
echo "--- Gmail App Password ---"
echo "To send email confirmations you need a Gmail App Password."
echo "Steps:"
echo "  1. Visit https://myaccount.google.com/security"
echo "  2. Enable 2-Step Verification (if not on)"
echo "  3. Search 'App passwords' → create one named 'Tennis Booker'"
echo "  4. Copy the 16-character password shown"
echo ""
read -rp "Paste your Gmail App Password (or press Enter to skip): " APP_PASS

if [ -n "$APP_PASS" ]; then
    # Update .env
    sed -i '' "s/your_16_char_app_password_here/$APP_PASS/g" "$SCRIPT_DIR/.env"
    # Update plist
    sed -i '' "s/your_16_char_app_password_here/$APP_PASS/g" "$PLIST"
    echo "  App password saved."
else
    echo "  Skipped – email notifications won't work until you add GMAIL_APP_PASS."
fi

# 3. Register launchd job
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
echo "  • Email $GMAIL_USER on success or failure"
echo ""
echo "To test it RIGHT NOW (without waiting for midnight):"
echo "  python3 $SCRIPT_DIR/book_tennis.py"
echo ""
echo "To uninstall:"
echo "  launchctl unload $PLIST"
echo "  sudo pmset repeat cancel"
echo ""
echo "Logs: $SCRIPT_DIR/logs/"
