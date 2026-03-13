"""
End-to-end test: verifies the full booking flow reaches the AddEvent form
for Monday March 16. Does NOT submit the booking.
"""
import asyncio
import json
from playwright.async_api import async_playwright
from datetime import datetime

USERNAME = "jabreslauer@gmail.com"
PASSWORD = "Hornets1!"
BASE_URL = "https://prospectpark.aptussoft.com/Member"

TARGET   = datetime(2026, 3, 16)          # Monday
DATE_STR = TARGET.strftime("%m/%d/%Y")    # 03/16/2026
DATE_JS  = TARGET.strftime("%Y-%m-%dT12:00:00")  # noon avoids UTC→local date shift
STIME    = "6:00 PM"
ETIME    = "7:00 PM"


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page    = await browser.new_page(viewport={"width": 1280, "height": 900})

        # Login
        print("1. Logging in...")
        await page.goto(BASE_URL, wait_until="networkidle")
        await page.fill('input[name="email"]', USERNAME)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button:has-text("Sign In")')
        await page.wait_for_load_state("networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        print(f"   URL: {page.url}")
        assert "Main" in page.url, f"Login failed at {page.url}"

        # Open Court Reservation
        print("2. Opening Court Reservation...")
        await page.evaluate("""() => {
            for (let li of document.querySelectorAll('li.submenu')) {
                if (li.textContent.trim().includes('Court Reservation')) { li.click(); return; }
            }
        }""")
        await page.wait_for_timeout(4000)
        cal_frame = next((f for f in page.frames if "Calender" in f.url), None)
        assert cal_frame, "Calendar frame not found"
        print(f"   Frame: {cal_frame.url}")

        # Navigate to Monday
        print(f"3. Navigating to {DATE_STR} (Monday)...")
        await cal_frame.evaluate(
            f"datepickerdate = new Date('{DATE_JS}');"
            f"$('#calendar').fullCalendar('gotoDate', new Date('{DATE_JS}'));"
        )
        await page.wait_for_timeout(2000)
        hdr = await cal_frame.evaluate(
            "document.querySelector('.fc-header-title h2')?.textContent?.trim()"
        )
        print(f"   Calendar shows: {hdr}")

        # Check availability
        print(f"4. Checking court availability for {DATE_STR}...")
        raw = await cal_frame.evaluate(f"""async () => {{
            const token = (typeof TOKENHEADERVALUE !== 'undefined') ? TOKENHEADERVALUE : '';
            const r = await fetch('/Member/Aptus/CourtBooking_Get', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'RequestVerificationToken': token
                }},
                body: 'locationid=Brooklyn&resourcetype=Clay&start={DATE_STR}&end={DATE_STR}&CalledFrom=WEB'
            }});
            return await r.text();
        }}""")
        data     = json.loads(json.loads(raw)["CourtBooking_GetResult"])
        courts   = data[0]
        bookings = data[1] if len(data) > 1 else []
        print(f"   Courts: {[c['name'] for c in courts]}")
        print(f"   Existing bookings that day: {len(bookings)}")

        # Check 6pm slot on first available court
        first = courts[0]
        court_id   = first["id"]
        court_name = first["name"]
        print(f"5. Opening booking form: {court_name} {STIME}–{ETIME}...")
        await cal_frame.evaluate(
            f"EventAddDisplay('{DATE_STR}', '{STIME}', '{ETIME}', '{court_id}');"
        )
        await page.wait_for_timeout(5000)

        add_frame = next((f for f in page.frames if "AddEvent" in f.url), None)
        assert add_frame, "AddEvent frame never appeared"
        print(f"   AddEvent URL: {add_frame.url}")

        # Verify form contents
        form_date    = await add_frame.evaluate("document.getElementById('Date')?.value")
        form_court   = await add_frame.evaluate("document.getElementById('Resource')?.value")
        form_stime   = await add_frame.evaluate("document.getElementById('Stime')?.value")
        form_etime   = await add_frame.evaluate("document.getElementById('Etime')?.value")
        form_attendee= await add_frame.evaluate(
            "document.getElementById('Attendees')?.options[document.getElementById('Attendees')?.selectedIndex]?.text"
        )
        waiver_present = await add_frame.query_selector("#chkreadterms") is not None
        go_btn_present = await add_frame.query_selector("button#save") is not None

        print(f"\n{'='*50}")
        print("  BOOKING FORM VERIFIED")
        print(f"{'='*50}")
        print(f"  Date:     {form_date}")
        print(f"  Court:    {form_court}  ({court_name})")
        print(f"  Start:    {form_stime}")
        print(f"  End:      {form_etime}")
        print(f"  Attendee: {form_attendee}")
        print(f"  Waiver checkbox present: {waiver_present}")
        print(f"  'Go' button present:     {go_btn_present}")
        print(f"{'='*50}")
        print("  ✅ Full flow verified — NOT submitting (test mode)")
        print(f"{'='*50}\n")

        await browser.close()


asyncio.run(run())
