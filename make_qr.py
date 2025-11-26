
import os
import qrcode

APP_BASE_URL = os.getenv("APP_BASE_URL", "https://concert-seats-70k7.onrender.com")

# Use root if you don’t have a /book-seat route
endpoint = "/"
full_url = f"{APP_BASE_URL.rstrip('/')}{endpoint}"

print("Using APP_BASE_URL:", APP_BASE_URL)
print("Generating QR for:", full_url)

qr = qrcode.QRCode(version=1, box_size=10, border=5)
qr.add_data(full_url)
qr.make(fit=True)

img = qr.make_image(fill_color="black", back_color="white")
img.save("qr_code.png")
