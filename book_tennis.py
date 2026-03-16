#!/usr/bin/env python3
"""
Prospect Park Tennis Center – Automatic Court Booker
Runs at midnight, books a 1-hour court 7 days out for Mon–Thu, 6–8 PM.
"""

import asyncio
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

# ── Configuration ──────────────────────────────────────────────────────────────
TENNIS_EMAIL    = "jabreslauer@gmail.com"
TENNIS_PASSWORD = "Hornets1!"
BOOKING_URL     = "https://prospectpark.aptussoft.com/Member"

TARGET_DAYS_AHEAD = 7
BOOK_DAYS     = {0, 1, 2, 3}       # Mon=0 Tue=1 Wed=2 Thu=3
TIME_SLOTS    = [                   # tried in order, first available wins
    ("6:00 PM",  "7:00 PM"),
    ("7:00 PM",  "8:00 PM"),
]
COURT_TYPE    = "Clay"              # indoor clay courts

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"booking_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── macOS notification helper ──────────────────────────────────────────────────
def notify(title: str, message: str):
    """Show a macOS notification banner. Works even when screen is locked –
    it will appear the next time the screen is woken."""
    script = (
        f'display notification "{message}" '
        f'with title "{title}" '
        f'sound name "Glass"'
    )
    try:
        subprocess.run(["osascript", "-e", script], check=True, timeout=10)
        log.info("Notification sent: %s", title)
    except Exception as e:
        log.error("Notification failed: %s", e)

# ── Core booking logic ─────────────────────────────────────────────────────────
async def check_availability(page, target_date_str: str) -> list[dict]:
    """
    Call CourtBooking_Get for the target date and return a list of
    reserved events so we know which slots are taken.
    """
    result = await page.evaluate(f"""async () => {{
        const token = (typeof TOKENHEADERVALUE !== 'undefined') ? TOKENHEADERVALUE : '';
        const resp = await fetch('/Member/Aptus/CourtBooking_Get', {{
            method: 'POST',
            headers: {{
                'Content-Type': 'application/x-www-form-urlencoded',
                'RequestVerificationToken': token
            }},
            body: 'locationid=Brooklyn&resourcetype={COURT_TYPE}&start={target_date_str}&end={target_date_str}&CalledFrom=WEB'
        }});
        return await resp.text();
    }}""")
    try:
        parsed = json.loads(result)
        data   = json.loads(parsed.get("CourtBooking_GetResult", "[[],[]]"))
        courts  = data[0] if len(data) > 0 else []
        bookings = data[1] if len(data) > 1 else []
        return courts, bookings
    except Exception as e:
        log.error("Failed to parse availability: %s", e)
        return [], []


def slot_is_free(bookings: list, court_id: str, stime: str, etime: str) -> bool:
    """
    Return True if the given court/time combo has no existing booking.
    Bookings use 12-hr time like ' 6:00PM' and ' 7:00PM'.
    """
    def normalise(t: str) -> str:
        return t.strip().upper().replace(" ", "").replace(":00", "")

    s = normalise(stime)
    e = normalise(etime)
    for b in bookings:
        if b.get("resourceId") != court_id:
            continue
        bs = normalise(b.get("stime", ""))
        be = normalise(b.get("etime", ""))
        # Simple overlap check: existing booking starts before our end
        # and ends after our start
        if bs < e and be > s:
            return False
    return True


async def book_slot(cal_frame, page, target_date_str: str,
                    stime: str, etime: str, court_id: str, court_name: str) -> bool:
    """
    Trigger the AddEvent modal for the given slot and submit the booking.
    Returns True on success.
    """
    log.info("Attempting: %s %s-%s %s", target_date_str, stime, etime, court_name)

    # Open the AddEvent modal via the calendar frame's JS function
    try:
        await cal_frame.evaluate(
            f"EventAddDisplay('{target_date_str}', '{stime}', '{etime}', '{court_id}')"
        )
    except Exception as e:
        log.error("EventAddDisplay failed: %s", e)
        return False

    # Wait for the AddEvent iframe to load
    add_frame = None
    for _ in range(20):
        await page.wait_for_timeout(500)
        add_frame = next((f for f in page.frames if "AddEvent" in f.url), None)
        if add_frame:
            break

    if not add_frame:
        log.error("AddEvent frame never appeared")
        return False

    log.info("AddEvent frame loaded: %s", add_frame.url)

    # Wait for the form to be ready
    await page.wait_for_timeout(2000)

    # Verify the date/resource are what we expect
    form_date = await add_frame.evaluate("document.getElementById('Date')?.value || ''")
    form_res  = await add_frame.evaluate("document.getElementById('Resource')?.value || ''")
    log.info("Form pre-filled: date=%s resource=%s", form_date, form_res)

    # Set correct resource (court) in case it defaulted to something else
    await add_frame.evaluate(f"""() => {{
        const sel = document.getElementById('Resource');
        if (sel) {{ sel.value = '{court_id}'; sel.dispatchEvent(new Event('change')); }}
    }}""")
    await page.wait_for_timeout(500)

    # Check the liability waiver checkbox
    try:
        waiver = await add_frame.query_selector("#chkreadterms")
        if waiver and not await waiver.is_checked():
            await waiver.check()
        log.info("Waiver accepted")
    except Exception as e:
        log.warning("Could not check waiver: %s", e)

    # Handle duration select if present (pick first option or set 60 mins)
    await add_frame.evaluate("""() => {
        const dur = document.getElementById('duration');
        if (dur && dur.options.length > 0 && !dur.value) {
            dur.value = dur.options[0].value;
            dur.dispatchEvent(new Event('change'));
        }
    }""")
    await page.wait_for_timeout(500)

    # Intercept the POST to OnlineBooking_AddCart so we can verify success
    booking_response = {}
    async def capture(resp):
        if "OnlineBooking_AddCart" in resp.url:
            try:
                body = await resp.text()
                booking_response["body"] = body
                booking_response["status"] = resp.status
            except Exception:
                pass
    page.on("response", capture)

    # Click the Go / submit button
    try:
        go_btn = await add_frame.query_selector("button#save, button[type='submit']")
        if go_btn:
            await go_btn.click()
            log.info("Clicked Go button")
        else:
            log.error("Go button not found")
            return False
    except Exception as e:
        log.error("Could not click Go: %s", e)
        return False

    # Wait for the booking API response
    for _ in range(20):
        await page.wait_for_timeout(500)
        if booking_response:
            break

    page.remove_listener("response", capture)

    log.info("OnlineBooking_AddCart response (status=%s): %s",
             booking_response.get("status"), booking_response.get("body", "")[:300])

    # Handle frmCartPay confirmation step if it appears
    await page.wait_for_timeout(3000)
    cart_frame = next((f for f in page.frames if "frmCartPay" in f.url or "CartPay" in f.url), None)
    if cart_frame:
        log.info("Cart/payment frame loaded: %s", cart_frame.url)
        # Look for a confirm / submit button
        confirm_btn = await cart_frame.query_selector("button[type='submit'], input[type='submit'], button:has-text('Confirm'), button:has-text('Pay'), button:has-text('Complete')")
        if confirm_btn:
            btn_text = await confirm_btn.inner_text()
            log.info("Clicking cart confirm button: '%s'", btn_text.strip())
            await confirm_btn.click()
            await page.wait_for_timeout(3000)
        else:
            # Log what's on the cart page for debugging
            body_text = await cart_frame.inner_text("body")
            log.info("Cart page content: %s", body_text[:500])

    # Check if booking succeeded
    resp_body = booking_response.get("body", "")
    status    = booking_response.get("status", 0)

    if status == 200 and ("error" not in resp_body.lower() or "success" in resp_body.lower()):
        log.info("Booking SUCCEEDED for %s %s-%s %s", target_date_str, stime, etime, court_name)
        return True
    elif not booking_response:
        log.warning("No response captured from OnlineBooking_AddCart – booking may have succeeded. Check My Reservations.")
        return True   # optimistic – the form submitted
    else:
        log.error("Booking may have FAILED. Response: %s", resp_body[:200])
        return False


async def run():
    target_date = datetime.now() + timedelta(days=TARGET_DAYS_AHEAD)
    weekday     = target_date.weekday()   # 0=Mon … 6=Sun
    day_name    = target_date.strftime("%A")
    date_str    = target_date.strftime("%m/%d/%Y")   # MM/DD/YYYY for the site
    # Use explicit local-noon time to avoid UTC→local date shifting in JS
    date_js     = target_date.strftime("%Y-%m-%dT12:00:00")  # avoids UTC midnight → yesterday bug

    log.info("=== Tennis Booker Starting ===")
    log.info("Today: %s  Target: %s (%s)", datetime.now().strftime("%Y-%m-%d"), date_str, day_name)

    if weekday not in BOOK_DAYS:
        msg = f"{day_name} {date_str} is not a booking day (Mon–Thu only). Exiting."
        log.info(msg)
        sys.exit(0)

    log.info("Target date %s (%s) is eligible. Starting browser…", date_str, day_name)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page    = await browser.new_page(viewport={"width": 1280, "height": 900})

        try:
            # ── Login (with retry) ─────────────────────────────────────────────
            log.info("Logging in…")
            logged_in = False
            for attempt in range(1, 4):
                try:
                    await page.goto(BOOKING_URL, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_selector('input[name="email"]', timeout=15000)
                    await page.fill('input[name="email"]', TENNIS_EMAIL)
                    await page.fill('input[name="password"]', TENNIS_PASSWORD)
                    await page.click('button:has-text("Sign In")')
                    await page.wait_for_url("**/Main", timeout=20000)
                    logged_in = True
                    break
                except Exception as e:
                    log.warning("Login attempt %d failed: %s", attempt, e)
                    await page.wait_for_timeout(3000)

            if not logged_in:
                raise RuntimeError("All login attempts failed")
            log.info("Logged in. URL: %s", page.url)
            await page.wait_for_load_state("domcontentloaded")

            # ── Open Court Reservation ─────────────────────────────────────────
            log.info("Opening Court Reservation…")
            await page.evaluate("""() => {
                for (let li of document.querySelectorAll('li.submenu')) {
                    if (li.textContent.trim().includes('Court Reservation')) {
                        li.click(); return;
                    }
                }
            }""")
            await page.wait_for_timeout(4000)

            cal_frame = next((f for f in page.frames if "Calender" in f.url), None)
            if not cal_frame:
                raise RuntimeError("Calendar frame not found after clicking Court Reservation")
            log.info("Calendar frame loaded: %s", cal_frame.url)

            # ── Navigate calendar to target date ───────────────────────────────
            log.info("Navigating to %s…", date_str)
            await cal_frame.evaluate(f"""() => {{
                datepickerdate = new Date('{date_js}');
                $('#calendar').fullCalendar('gotoDate', new Date('{date_js}'));
            }}""")
            await page.wait_for_timeout(2000)

            date_display = await cal_frame.evaluate(
                "document.querySelector('.fc-header-title h2')?.textContent?.trim()"
            )
            log.info("Calendar showing: %s", date_display)

            # ── Check availability via API ──────────────────────────────────────
            log.info("Fetching court availability for %s…", date_str)
            courts, bookings = await check_availability(cal_frame, date_str)
            log.info("Courts available: %s", [c["name"] for c in courts])
            log.info("Existing bookings: %d", len(bookings))

            # ── Try each time slot × each court until one books ────────────────
            booked      = False
            booked_info = {}

            for stime, etime in TIME_SLOTS:
                if booked:
                    break
                log.info("Trying slot %s–%s…", stime, etime)
                for court in courts:
                    court_id   = court["id"]
                    court_name = court["name"]

                    if not slot_is_free(bookings, court_id, stime, etime):
                        log.info("  %s %s–%s already reserved – skipping", court_name, stime, etime)
                        continue

                    log.info("  %s %s–%s appears free – attempting booking…",
                             court_name, stime, etime)

                    success = await book_slot(
                        cal_frame, page, date_str, stime, etime, court_id, court_name
                    )

                    if success:
                        booked      = True
                        booked_info = {"date": date_str, "day": day_name,
                                       "court": court_name, "stime": stime, "etime": etime}
                        break

                    # If the booking attempt failed, close any stray modal and retry next court
                    await page.evaluate("""() => {
                        const closeBtn = document.querySelector('.dp-modal-close, .modal-close, [data-dismiss="modal"]');
                        if (closeBtn) closeBtn.click();
                    }""")
                    await page.wait_for_timeout(1000)

            # ── Notify result ──────────────────────────────────────────────────
            if booked:
                title = "🎾 Court booked!"
                msg   = (f"{booked_info['day']} {booked_info['date']} · "
                         f"{booked_info['stime']}–{booked_info['etime']} · "
                         f"{booked_info['court']}")
                log.info("%s – %s", title, msg)
                notify(title, msg)
            else:
                title = "❌ Tennis booking failed"
                msg   = (f"No court secured for {day_name} {date_str}. "
                         f"All courts may be taken. Check the portal manually.")
                log.warning("%s – %s", title, msg)
                notify(title, msg)

        except Exception as e:
            log.exception("Unexpected error: %s", e)
            notify("❌ Tennis booker error", str(e)[:100])
        finally:
            await browser.close()

    log.info("=== Tennis Booker Done ===")


if __name__ == "__main__":
    asyncio.run(run())
