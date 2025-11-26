
import os
import qrcode

# Get base URL from environment variable or fallback to Render URL
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://concert-seats-70k7.onrender.com")

# Example endpoint
endpoint = "/book-seat"  # Change as per your app
full_url = f"{APP_BASE_URL}{endpoint}"

# Generate QR code
qr = qrcode.QRCode(version=1, box_size=10, border=5)
qr.add_data(full_url)
qr.make(fit=True)

img = qr.make_image(fill="black", back_color="white")
img.save("qr_code.png")

print(f"QR code generated for: {full_url}")
