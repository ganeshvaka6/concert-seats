import os
import json
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

@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json(force=True) or {}
    user_code = str(data.get("user_code", "")).strip()
    name = str(data.get("name", "")).strip()
    mobile = str(data.get("mobile", "")).strip()
    seats = data.get("seats", [])

    if not name or not mobile or not seats:
        return jsonify({"ok": False, "message": "Name, Mobile and at least one seat are required."}), 400
    if not all(str(s).isdigit() for s in seats):
        return jsonify({"ok": False, "message": "Seats must be numeric."}), 400
    if not mobile.isdigit() or len(mobile) < 10:
        return jsonify({"ok": False, "message": "Invalid mobile number."}), 400

    try:
        ws = get_sheet()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        seats_str = ", ".join(map(str, seats))
        ws.append_row([timestamp, user_code, name, mobile, seats_str])
        return jsonify({"ok": True, "message": "Booking saved."}), 200
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
