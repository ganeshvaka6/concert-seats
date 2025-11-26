import os
import qrcode

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5000")
img = qrcode.make(APP_BASE_URL)
img.save("concert_seats_qr.png")
