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
    ws.batch_clear(["A2:ZZZ"])  # Clears all rows except header
    return "Sheet contents cleared below header."

# ---------- Helpers ----------

def extract_ints_from_string(s: str):
    """Extract all integer numbers from a string."""
    return [int(x) for x in re.findall(r"\d+", s or "")]

def normalize_seats(seats):
    """Normalize seats input into an ordered list of integers."""
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
    """Normalize mobile(s) to a list of digit-only strings."""
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
    """Normalize name(s) to a list."""
    if isinstance(name, list):
        return [str(n).strip() for n in name if str(n).strip()]
    elif isinstance(name, str):
        parts = [p.strip() for p in name.split(",")] if "," in name else [name.strip()]
        return [p for p in parts if p]
    else:
        return []

def pair_rows_for_booking(user_code, names_list, mobiles_list, seats_ordered):
    """Build rows to append to the sheet based on provided lists."""
    rows = []
    n_names = len(names_list)
    n_mobiles = len(mobiles_list)
    n_seats = len(seats_ordered)

    for m in mobiles_list:
        if len(m) < 10:
            raise ValueError("Invalid mobile number: each must have at least 10 digits.")

    if n_names == n_seats and n_mobiles == n_seats:
        for i in range(n_seats):
            rows.append((user_code, names_list[i], mobiles_list[i], seats_ordered[i]))
        return rows

    if n_names == 1 and n_mobiles == 1 and n_seats >= 1:
        for seat in seats_ordered:
            rows.append((user_code, names_list[0], mobiles_list[0], seat))
        return rows

    if n_names == 1 and n_mobiles == n_seats:
        for i in range(n_seats):
            rows.append((user_code, names_list[0], mobiles_list[i], seats_ordered[i]))
        return rows

    if n_mobiles == 1 and n_names == n_seats:
        for i in range(n_seats):
            rows.append((user_code, names_list[i], mobiles_list[0], seats_ordered[i]))
        return rows

    raise ValueError(
        "Cannot pair names, mobiles, and seats. "
        "Ensure either counts all match, or single name+mobile with multiple seats."
    )

# ---------- Routes ----------

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", seat_count=200)

@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json(force=True) or {}

    if isinstance(data, list):
        bookings = data
    elif isinstance(data, dict) and "users" in data:
        bookings = data["users"]
    else:
        bookings = [data]

    ws = get_sheet()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        all_confirmed_seats = []

        for booking in bookings:
            user_code = str(booking.get("user_code", "")).strip()
            names_list = normalize_names_to_list(booking.get("name", ""))
            mobiles_list = normalize_mobile_to_list(booking.get("mobile", ""))
            seats_ordered = normalize_seats(booking.get("seats", []))

            if not names_list or not mobiles_list or not seats_ordered:
                return jsonify({
                    "ok": False,
                    "message": "Name(s), Mobile(s), and at least one seat are required."
                }), 400

            invalid_seats = [s for s in seats_ordered if s < 1 or s > 200]
            if invalid_seats:
                return jsonify({
                    "ok": False,
                    "message": f"Invalid seat numbers: {invalid_seats}. Allowed range is 1-200."
                }), 400

            try:
                row_tuples = pair_rows_for_booking(user_code, names_list, mobiles_list, seats_ordered)
            except ValueError as ve:
                return jsonify({"ok": False, "message": str(ve)}), 400

            for (uc, nm, mb, seat) in row_tuples:
                ws.append_row([timestamp, uc, nm, mb, str(seat)])
                all_confirmed_seats.append(seat)

        confirmed_seats = ", ".join(map(str, all_confirmed_seats))
        return jsonify({
            "ok": True,
            "message": (
                "Thank you for registering for the Music Concert! "
                f"Your seat number(s) {confirmed_seats} are confirmed. "
                "We look forward to seeing you there!"
            )
        }), 200

    except Exception as e:
        return jsonify({"ok": False, "message": f"Failed to save: {e}"}), 500

@app.route("/booked-seats", methods=["GET"])
def booked_seats():
    try:
        ws = get_sheet()
        col_values = ws.col_values(5)[1:]
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
