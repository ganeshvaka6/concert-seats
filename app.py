import os
import json
import re
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file
import gspread
from google.oauth2.service_account import Credentials
import qrcode
from io import BytesIO

# Environment variables
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "ConcertBookings")
GOOGLE_SHEET_KEY = os.getenv("GOOGLE_SHEET_KEY")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE", "/etc/secrets/service_account.json")
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://concert-seats-70k7.onrender.com")
CLEAR_TOKEN = os.getenv("CLEAR_TOKEN")  # Optional security token

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

app = Flask(__name__)

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
    ws.batch_clear(["A2:ZZZ"])  # Clears all rows except header
    return "Sheet contents cleared below header."

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", seat_count=200)

# ---------- Helpers ----------

def extract_ints_from_string(s: str):
    """Extract all integer numbers from a string."""
    return [int(x) for x in re.findall(r"\d+", s or "")]

def normalize_seats(seats):
    """
    Normalize seats input into a list of integers.
    Handles:
      - [1, 2]                        (array of ints)
      - ["1", "Selected Seat: 2"]     (array of strings)
      - "1, 2"                        (comma-separated string)
      - "Selected Seat: 1"            (single string with label)
    """
    result = []
    if isinstance(seats, list):
        for item in seats:
            if isinstance(item, int):
                result.append(item)
            elif isinstance(item, str):
                result.extend(extract_ints_from_string(item))
    elif isinstance(seats, str):
        result.extend(extract_ints_from_string(seats))
    # Deduplicate & sort
    return sorted(set(result))

def normalize_mobile(mobile: str):
    """Normalize mobile by removing non-digit characters (keeps only digits)."""
    digits = re.findall(r"\d+", mobile or "")
    return "".join(digits)

# ---------- End Helpers ----------

@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json(force=True) or {}

    # Support multiple registrations:
    # - direct array: [ {...}, {...} ]
    # - object with "users": { "users": [ {...}, {...} ] }
    # - single object: { ... }
    if isinstance(data, list):
        bookings = data
    elif isinstance(data, dict) and "users" in data:
        bookings = data["users"]
    else:
        bookings = [data]

    ws = get_sheet()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        for booking in bookings:
            user_code = str(booking.get("user_code", "")).strip()
            name = str(booking.get("name", "")).strip()
            mobile_raw = str(booking.get("mobile", "")).strip()
            seats_raw = booking.get("seats", [])

            # Normalize inputs
            mobile = normalize_mobile(mobile_raw)
            seats = normalize_seats(seats_raw)

            # Validation
            if not name or not mobile or not seats:
                return jsonify({"ok": False, "message": "Name, Mobile and at least one seat are required."}), 400
            if len(mobile) < 10:
                return jsonify({"ok": False, "message": "Invalid mobile number: must have at least 10 digits."}), 400

            # Optional: enforce seat range (adjust per layout)
            invalid = [s for s in seats if s < 1 or s > 200]
            if invalid:
                return jsonify({"ok": False, "message": f"Invalid seat numbers: {invalid}. Allowed range is 1-200."}), 400

            # Save to Google Sheets: seats as comma-separated string
            seats_str = ", ".join(map(str, seats))
            ws.append_row([timestamp, user_code, name, mobile, seats_str])

        return jsonify({"ok": True, "message": f"{len(bookings)} booking(s) saved."}), 200

    except Exception as e:
        return jsonify({"ok": False, "message": f"Failed to save: {e}"}), 500

@app.route("/booked-seats", methods=["GET"])
def booked_seats():
    try:
        ws = get_sheet()
        col_values = ws.col_values(5)[1:]  # skip header
        booked = []
        for v in col_values:
            if v:
                booked.extend([int(s.strip()) for s in v.split(",") if s.strip().isdigit()])
        return jsonify({"booked": booked})
    except Exception as e:
        return jsonify({"booked": [], "error": str(e)}), 500

@app.route("/qr", methods=["GET"])
def qr():
    target = APP_BASE_URL.rstrip("/")
    img = qrcode.make(target)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    response = send_file(buf, mimetype="image/png")
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.route("/clear-sheet", methods=["POST"])
def clear_sheet_route():
    if CLEAR_TOKEN:
        auth = request.headers.get("X-CLEAR-TOKEN")
        if not auth or auth != CLEAR_TOKEN:
            return jsonify({"ok": False, "message": "Unauthorized"}), 401
    try:
        msg = clear_google_sheet_values()
        return jsonify({"ok": True, "message": msg})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
