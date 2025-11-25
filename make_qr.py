
import qrcode
import os

# Permanent URL for QR code (update this to your network IP or deployed URL)
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5000")

# Generate QR code
img = qrcode.make(APP_BASE_URL)

# Save QR code to local path
qr_file_path = "concert_seats_qr.png"
img.save(qr_file_path)

