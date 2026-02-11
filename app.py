
import os
import json
import re
import threading
import time
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file

import gspread
from google.oauth2.service_account import Credentials
import qrcode
from io import BytesIO

# ----------------- TWILIO WHATSAPP INTEGRATION (TEMPLATE ONLY) -----------------
from twilio.rest import Client

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM")  # e.g., whatsapp:+919901760422
TWILIO_CONTENT_SID_CONCERT = os.getenv("TWILIO_CONTENT_SID_CONCERT")  # HX...

twilio_client = Client(TWILIO_SID, TWILIO_AUTH)


def _format_wa_to(number_str: str) -> str:
    digits = re.sub(r"\D+", "", number_str or "")

    if digits.startswith("91") and len(digits) == 12:
        return f"whatsapp:+{digits}"
    elif len(digits) == 10:
        return f"whatsapp:+91{digits}"
    else:
        print(f"[WARN] Unexpected mobile format: {number_str} -> {digits}")
        return f"whatsapp:+{digits}"


# ---------------- ASYNC WHATSAPP SENDING FIX ----------------
def async_send_whatsapp(number, name, seat, event_time):
    threading.Thread(
        target=send_whatsapp_template_concert,
        args=(number, name, seat, event_time),
        daemon=True,
    ).start()


def send_whatsapp_template_concert(to_number: str, name: str, seat: int, event_time: str):

    if not (TWILIO_SID and TWILIO_AUTH and TWILIO_WHATSAPP_FROM and TWILIO_CONTENT_SID_CONCERT):
        print("[ERROR] Missing Twilio credentials or Content SID")
        return None

    try:
        to_formatted = _format_wa_to(to_number)

        payload = {
            "from_": TWILIO_WHATSAPP_FROM,
            "to": to_formatted,
            "content_sid": TWILIO_CONTENT_SID_CONCERT,
            "content_variables": json.dumps({
                "1": name,
                "2": str(seat),
                "3": event_time
            })
        }

        print("[INFO] Sending WA Template:", payload)

        msg = twilio_client.messages.create(**payload)

        print("[INFO] Template WhatsApp SENT:", msg.sid)
        return msg.sid

    except Exception as e:
        print("[ERROR] WhatsApp Template Send Failed:", e)
        return None

# -------------------------------------------------------------------------------


# ------------------ EXISTING CONFIG --------------------------------------------
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "ConcertBookings")
GOOGLE_SHEET_KEY = os.getenv("GOOGLE_SHEET_KEY")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE", "/etc/secrets/service_account.json")
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://concert-seats-70k7.onrender.com")
CLEAR_TOKEN = os.getenv("CLEAR_TOKEN")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

app = Flask(__name__)

# -------------------- CONCURRENCY GUARDS ----------------------
# Fast anti-double-click cache with TTL
_recent_cache = {}
_recent_cache_lock = threading.Lock()
FAST_DUP_WINDOW_SEC = int(os.getenv("FAST_DUP_WINDOW_SEC", "8"))  # adjustable window

def _now():
    return int(time.time())

def is_fast_duplicate(name: str, mobile: str, seat: int) -> bool:
    """
    Prevents rapid duplicate submissions from the same user for the same seat.
    Entries expire after FAST_DUP_WINDOW_SEC.
    """
    key = f"{name.strip().lower()}|{mobile.strip()}|{seat}"
    now = _now()
    with _recent_cache_lock:
        # purge old
        to_del = [k for k, t in _recent_cache.items() if now - t > FAST_DUP_WINDOW_SEC]
        for k in to_del:
            _recent_cache.pop(k, None)

        if key in _recent_cache:
            return True
        _recent_cache[key] = now
        return False

# Global write lock: guarantees atomic "check-then-append" against the sheet
sheet_write_lock = threading.Lock()

# ---------- Google Sheets ----------
def build_creds():
    return Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)


def get_sheet():
    creds = build_creds()
    client = gspread.authorize(creds)
    sh = client.open_by_key(GOOGLE_SHEET_KEY) if GOOGLE_SHEET_KEY else client.open(GOOGLE_SHEET_NAME)
    ws = sh.sheet1
    values = ws.get_all_values()
    if not values:
        ws.append_row(["Timestamp", "User Code", "Name", "Mobile", "Selected Seats"])
    return ws


def is_duplicate_booking(ws, name, mobile, seat):
    """Return True if same booking exists (Name+Mobile+Seat)."""
    # NOTE: This is intentionally a read of the whole sheet.
    # We will call it ONLY inside the global write lock or for coarse pre-checks.
    rows = ws.get_all_records()
    name_cmp = name.strip().lower()
    mobile_cmp = mobile.strip()
    seat_cmp = str(seat)
    for row in rows:
        if (
            str(row.get("Name", "")).strip().lower() == name_cmp and
            str(row.get("Mobile", "")).strip() == mobile_cmp and
            str(row.get("Selected Seats", "")).strip() == seat_cmp
        ):
            return True

    return False


# ---------- Helpers ----------
def extract_ints_from_string(s: str):
    return [int(x) for x in re.findall(r"\d+", s or "")]


def normalize_seats(seats):
    result = []
    if isinstance(seats, list):
        for item in seats:
            if isinstance(item, int):
                result.append(item)
            elif isinstance(item, str):
                result.extend(extract_ints_from_string(item))
    elif isinstance(seats, str):
        result.extend(extract_ints_from_string(seats))
    return result


def normalize_mobile_to_list(mobile):
    def only_digits(s):
        return "".join(re.findall(r"\d+", s or ""))

    if isinstance(mobile, list):
        out = [only_digits(m) for m in mobile]
    elif isinstance(mobile, str):
        parts = [p.strip() for p in mobile.split(",")] if "," in mobile else [mobile.strip()]
        out = [only_digits(p) for p in parts]
    else:
        out = []

    return [m for m in out if m]


def normalize_names_to_list(name):
    if isinstance(name, list):
        return [str(n).strip() for n in name if str(n).strip()]
    elif isinstance(name, str):
        parts = [p.strip() for p in name.split(",")] if "," in name else [name.strip()]
        return [p for p in parts if p]
    return []


def pair_rows_for_booking(user_code, names_list, mobiles_list, seats_ordered):
    rows = []
    n_names = len(names_list)
    n_mobiles = len(mobiles_list)
    n_seats = len(seats_ordered)

    for m in mobiles_list:
        if len(m) < 10:
            raise ValueError("Invalid mobile number")

    if n_names == n_seats and n_mobiles == n_seats:
        return [(user_code, names_list[i], mobiles_list[i], seats_ordered[i]) for i in range(n_seats)]

    if n_names == 1 and n_mobiles == 1:
        return [(user_code, names_list[0], mobiles_list[0], s) for s in seats_ordered]

    if n_names == 1 and n_mobiles == n_seats:
        return [(user_code, names_list[0], mobiles_list[i], seats_ordered[i]) for i in range(n_seats)]

    if n_mobiles == 1 and n_names == n_seats:
        return [(user_code, names_list[i], mobiles_list[0], seats_ordered[i]) for i in range(n_seats)]

    raise ValueError("Cannot pair names/mobiles/seats")


# ---------- Routes ----------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", seat_count=300)


@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json(force=True) or {}

    bookings = data["users"] if isinstance(data, dict) and "users" in data else (data if isinstance(data, list) else [data])

    ws = get_sheet()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        all_confirmed = []
        # We'll collect candidate rows and WhatsApp payloads,
        # then write atomically under a lock, re-checking duplicates.
        candidate_rows = []
        candidate_wa = []

        for booking in bookings:
            user_code = str(booking.get("user_code", "")).strip()
            names = normalize_names_to_list(booking.get("name", ""))
            mobiles = normalize_mobile_to_list(booking.get("mobile", ""))
            seats = normalize_seats(booking.get("seats", []))

            if not names or not mobiles or not seats:
                return jsonify({"ok": False, "message": "Name, Mobile, Seat required"}), 400

            invalid = [s for s in seats if s < 1 or s > 300]
            if invalid:
                return jsonify({"ok": False, "message": f"Invalid seats: {invalid}"}), 400

            row_tuples = pair_rows_for_booking(user_code, names, mobiles, seats)
            event_time = os.getenv("EVENT_TIME_STR", "February 28th, 2026 at 7:00 PM")

            for (uc, nm, mb, seat) in row_tuples:

                # ---- FAST anti-double-click (TTL in-memory) ----
                if is_fast_duplicate(nm, mb, seat):
                    print(f"[SKIP] FAST duplicate (cache) -> {nm}, {mb}, seat {seat}")
                    continue

                # (Coarse) pre-check to reduce noise (not atomic, final check happens in lock)
                if is_duplicate_booking(ws, nm, mb, seat):
                    print(f"[SKIP] Already in sheet (pre-check) -> {nm}, seat {seat}")
                    continue

                candidate_rows.append([timestamp, uc, nm, mb, str(seat)])
                candidate_wa.append((mb, nm, seat, event_time))

        # ---------- Atomic section: re-check + append once ----------
        written_rows = []
        written_wa = []
        if candidate_rows:
            with sheet_write_lock:
                # Re-pull records and filter candidates that are truly new
                existing = ws.get_all_records()
                # Build a quick lookup set for current sheet
                existing_keys = set()
                for r in existing:
                    nm = str(r.get("Name", "")).strip().lower()
                    mb = str(r.get("Mobile", "")).strip()
                    st = str(r.get("Selected Seats", "")).strip()
                    existing_keys.add(f"{nm}|{mb}|{st}")

                filtered_rows = []
                filtered_wa = []
                for row, wa in zip(candidate_rows, candidate_wa):
                    nm = row[2].strip().lower()
                    mb = row[3].strip()
                    st = str(row[4]).strip()
                    key = f"{nm}|{mb}|{st}"
                    if key in existing_keys:
                        print(f"[SKIP] Duplicate (atomic check) -> {row[2]}, seat {row[4]}")
                        continue
                    # mark as existing to prevent duplicates among our own batch too
                    existing_keys.add(key)
                    filtered_rows.append(row)
                    filtered_wa.append(wa)

                if filtered_rows:
                    ws.append_rows(filtered_rows)
                    written_rows = filtered_rows
                    written_wa = filtered_wa

        # build confirmation and send WhatsApp only for rows actually written
        if written_rows:
            all_confirmed.extend([int(r[4]) for r in written_rows])
            for mb, nm, seat, event_time in written_wa:
                async_send_whatsapp(mb, nm, seat, event_time)

        final = ", ".join(map(str, all_confirmed)) if all_confirmed else "none"
        return jsonify({
            "ok": True,
            "message": f"Thank you for registering! Seat(s) {final} confirmed."
        }), 200

    except Exception as e:
        print("[ERROR] submit failed:", e)
        return jsonify({"ok": False, "message": f"Failed: {e}"}), 500


@app.route("/booked-seats")
def booked_seats():
    try:
        ws = get_sheet()
        col_values = ws.col_values(5)[1:]
        booked = [int(s.strip()) for v in col_values for s in v.split(",") if s.strip().isdigit()]
        return jsonify({"booked": booked})
    except Exception as e:
        return jsonify({"booked": [], "error": str(e)})


@app.route("/qr")
def qr():
    target = APP_BASE_URL.rstrip("/")
    img = qrcode.make(target)
    buf = BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/clear-sheet", methods=["POST"])
def clear_sheet_route():
    if CLEAR_TOKEN and request.headers.get("X-CLEAR-TOKEN") != CLEAR_TOKEN:
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    try:
        ws = get_sheet()
        ws.batch_clear(["A2:ZZZ"])
        return jsonify({"ok": True, "message": "Sheet cleared"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


# (Optional) health endpoint to help keep instance warm (for QR scans)
@app.route("/health")
def health():
    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
