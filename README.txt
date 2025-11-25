# Concert Seat Booking with Permanent QR Code

## Steps to Use:

1. **Set Up Google Sheet**
   - Create a sheet named `ConcertBookings`.
   - Add headers: Timestamp | User Code | Name | Mobile | Selected Seats.

2. **Enable Google Sheets API**
   - Go to Google Cloud Console.
   - Enable Google Sheets API and Google Drive API.
   - Create a Service Account and download JSON key.
   - Place the key as `service_account.json` in project root.
   - Share your Google Sheet with the service account email (Editor access).

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run Locally**
   ```bash
   python app.py
   ```
   Access at: http://127.0.0.1:5000 or your network IP.

5. **Generate Permanent QR Code**
   - Update `APP_BASE_URL` in `make_qr.py` or set environment variable.
   - Run:
     ```bash
     python make_qr.py
     ```
   - This creates `concert_seats_qr.png` in your project folder.
   - Share this QR with users.

6. **Deploy for Permanent Access**
   - Use Render or Heroku for hosting.
   - Update `APP_BASE_URL` in `app.py` and `make_qr.py` to your deployed URL.
   - Regenerate QR code for the public URL.

7. **User Flow**
   - User scans QR code → Opens app → Selects seats → Enters details → Clicks Submit.
   - Data is saved in Google Sheet.
