import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file
import gspread
from google.oauth2.service_account import Credentials
import qrcode
from io import BytesIO

GOOGLE_SHEET_NAME = os.getenv("1dnwP1uMBZWiKn9j9tmJqQhs_3pgjsSoF4Rr4XqZRucw", "ConcertBookings")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE", "service_account.json")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5000")

app = Flask(__name__)

def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    sh = client.open(GOOGLE_SHEET_NAME)
    ws = sh.sheet1
    values = ws.get_all_values()
    if not values:
        ws.append_row(["Timestamp", "User Code", "Name", "Mobile", "Selected Seats"])
    return ws

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", seat_count=300)

@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json(force=True)
    user_code = data.get("user_code", "").strip()
    name = data.get("name", "").strip()
    mobile = data.get("mobile", "").strip()
    seats = data.get("seats", [])
    if not name or not mobile or not seats:
        return jsonify({"ok": False, "message": "Name, Mobile and at least one seat are required."}), 400
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
        values = ws.get_all_values()[1:]  # skip header
        booked = []
        for row in values:
            if len(row) >= 5 and row[4]:
                booked.extend([int(s.strip()) for s in row[4].split(",") if s.strip().isdigit()])
        return jsonify({"booked": booked})
    except Exception as e:
        return jsonify({"booked": [], "error": str(e)})

@app.route("/qr", methods=["GET"])
def qr():
    target_url = APP_BASE_URL
    img = qrcode.make(target_url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
