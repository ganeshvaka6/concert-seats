
import os
import json
import re
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
    """Ensure destination number is formatted as whatsapp:+<E.164>"""
    digits = re.sub(r"\D+", "", number_str or "")

    if digits.startswith("91") and len(digits) == 12:
        return f"whatsapp:+{digits}"
    elif len(digits) == 10:
        return f"whatsapp:+91{digits}"
    else:
        print(f"[WARN] Unexpected mobile format: {number_str} -> {digits}")
        return f"whatsapp:+{digits}"


def send_whatsapp_template_concert(to_number: str, name: str, seat: int, event_time: str):
    """
    Sends WhatsApp Content Template (Production correct)
    Variables:
        {{1}} -> name
        {{2}} -> seat
        {{3}} -> event_time
    """

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


def clear_google_sheet_values():
    ws = get_sheet()
    ws.batch_clear(["A2:ZZZ"])
    return "Sheet cleared"


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
    return render_template("index.html", seat_count=310)


@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json(force=True) or {}

    bookings = data["users"] if isinstance(data, dict) and "users" in data else (data if isinstance(data, list) else [data])

    ws = get_sheet()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        all_confirmed = []

        for booking in bookings:
            user_code = str(booking.get("user_code", "")).strip()
            names = normalize_names_to_list(booking.get("name", ""))
            mobiles = normalize_mobile_to_list(booking.get("mobile", ""))
            seats = normalize_seats(booking.get("seats", []))

            if not names or not mobiles or not seats:
                return jsonify({"ok": False, "message": "Name, Mobile, Seat required"}), 400

            invalid = [s for s in seats if s < 1 or s > 310]
            if invalid:
                return jsonify({"ok": False, "message": f"Invalid seats: {invalid}"}), 400

            row_tuples = pair_rows_for_booking(user_code, names, mobiles, seats)
            event_time = os.getenv("EVENT_TIME_STR", "January 31st, 2026 at 7:00 PM")

            for (uc, nm, mb, seat) in row_tuples:
                ws.append_row([timestamp, uc, nm, mb, str(seat)])
                all_confirmed.append(seat)

                send_whatsapp_template_concert(mb, nm, seat, event_time)

        final = ", ".join(map(str, all_confirmed))
        return jsonify({
            "ok": True,
            "message": f"Thank you for registering! Seat(s) {final} confirmed."
        }), 310

    except Exception as e:
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
        return jsonify({"ok": True, "message": clear_google_sheet_values()})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
