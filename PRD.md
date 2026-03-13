# Prospect Park Tennis Center – Auto-Booker
## Product Requirements Document

**Owner:** Jack Breslauer
**Status:** Built & Ready to Deploy
**Last Updated:** March 2026

---

## Problem

Prospect Park Tennis Center (Brooklyn, NY) releases court bookings at midnight, exactly 7 days in advance. Courts are in high demand and are typically fully reserved within minutes of opening. The manual booking process requires being awake at midnight, which is not realistic.

---

## Goal

Automatically book a 1-hour indoor clay court every Monday–Thursday at midnight, securing the 6–8 PM time window, without any user intervention.

---

## Solution

A Python script using browser automation (Playwright) that:
1. Runs nightly at midnight via macOS `launchd`
2. Logs into the member portal
3. Checks court availability for the eligible date (7 days out)
4. Books the first available court in the preferred time window
5. Sends an email confirmation (success or failure)

---

## Functional Requirements

### Scheduling
| Requirement | Value |
|---|---|
| Run time | 12:00 AM daily |
| Booking window | 7 days in advance (per center policy) |
| Eligible booking days | Monday, Tuesday, Wednesday, Thursday only |
| Behavior on ineligible days | Exit silently (no action, no email) |

### Booking Preferences
| Preference | Value |
|---|---|
| Duration | 60 minutes |
| Time slots (priority order) | 6:00–7:00 PM, then 7:00–8:00 PM |
| Court type | Clay (indoor) |
| Court preference | None – first available |
| Location | Brooklyn (Prospect Park Tennis Center) |

### Availability Logic
- Query the `CourtBooking_Get` API for all 9 clay courts on the target date
- Iterate time slots (6–7 PM first, 7–8 PM second)
- Within each slot, iterate all courts and attempt the first free one
- Stop as soon as one booking succeeds

### Booking Flow
1. Log in to `https://prospectpark.aptussoft.com/Member`
2. Open Court Reservation (via sidebar)
3. Navigate calendar to target date
4. Trigger `EventAddDisplay()` with date, time, and court ID
5. Accept the liability waiver checkbox
6. Submit the booking form (`OnlineBooking_AddCart` API)
7. Handle cart/payment confirmation page if present

### Notifications
- **On success:** Email to `jabreslauer@gmail.com` with date, time, and court name
- **On failure:** Email to `jabreslauer@gmail.com` with reason and log file path
- **On ineligible day:** No email sent
- Sent via Gmail SMTP using an App Password stored in the environment

---

## Non-Functional Requirements

- Runs headlessly (no visible browser window)
- Mac can be screen-off and locked; only needs to be powered on
- macOS `pmset` wakes the machine at 11:58 PM nightly, script runs at midnight, machine resumes sleep
- All actions logged to timestamped files in `~/tennis/logs/`
- Credentials stored outside source code (environment variable / `.env` file)

---

## System Architecture

```
macOS launchd (midnight)
    └── book_tennis.py
            ├── Login (Playwright / Chromium headless)
            ├── CourtBooking_Get API  →  availability check
            ├── EventAddDisplay()     →  booking modal
            ├── OnlineBooking_AddCart →  submit booking
            └── smtplib (Gmail)       →  email confirmation
```

### Key API Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /Aptus/CourtBooking_Get` | Fetch availability for a date |
| `POST /Aptus/AddEventSetup` | Load booking configuration |
| `POST /Aptus/CourtBookings_checkcardonfile` | Verify card on file |
| `GET  /Aptus/AddEvent?events=...` | Load booking form |
| `POST /Aptus/OnlineBooking_AddCart` | Submit the booking |

### Court ID Map (Clay courts)

| Court Name | Resource ID |
|---|---|
| Court 1b | Clay1 |
| Court 3a | Clay2 |
| Court 2a | Clay3 |
| Court 1a | Clay4 |
| Court 2b | Clay5 |
| Court 3b | Clay6 |
| Court 4b | Clay7 |
| Court 5b | Clay8 |
| Court 6b | Clay9 |

---

## File Structure

```
~/tennis/
├── book_tennis.py          # Main booking script
├── e2e_test.py             # End-to-end test (no submission)
├── setup.sh                # One-time setup installer
├── .env                    # Gmail App Password (not committed)
└── logs/                   # Timestamped run logs

~/Library/LaunchAgents/
└── com.jackbreslauer.tennis.plist   # macOS scheduler
```

---

## Setup Instructions

1. Get a Gmail App Password:
   - Visit [myaccount.google.com/security](https://myaccount.google.com/security)
   - Enable 2-Step Verification
   - Search "App passwords" → create one named "Tennis Booker"

2. Run the setup script:
   ```bash
   cd ~/tennis && bash setup.sh
   ```
   This will prompt for the App Password, register the launchd job, and configure the nightly wake schedule.

3. To test manually:
   ```bash
   python3 ~/tennis/book_tennis.py
   ```

---

## Constraints & Known Limitations

- The booking site uses a Knockout.js + FullCalendar frontend; all automation targets the underlying API calls directly rather than pixel-level UI interaction, making it robust to minor UI changes.
- The script depends on the site's `TOKENHEADERVALUE` CSRF token, which is injected on page load. This is handled automatically via the browser session.
- If the site undergoes a major redesign or the API endpoints change, the script will need to be updated.
- Booking is limited to the member's account only (no guest booking currently implemented).
- The 7-day advance booking window is enforced server-side (`reservecutoff: 168` hours).
