const seatGrid = document.getElementById("seatGrid");
const selectedSeats = new Set();
const submitBtn = document.getElementById("submitBtn");
const statusEl = document.getElementById("status");
async function fetchBookedSeats() {
  try {
    const res = await fetch("/booked-seats");
    const data = await res.json();
    return data.booked || [];
  } catch (err) {
    console.error("Failed to fetch booked seats:", err);
    return [];
  }
}
async function renderSeats() {
  const bookedSeats = await fetchBookedSeats();
  seatGrid.innerHTML = "";
  for (let i = 1; i <= SEAT_COUNT; i++) {
    const div = document.createElement("div");
    div.className = "seat";
    div.textContent = i;
    if (bookedSeats.includes(i)) {
      div.classList.add("booked");
    } else {
    div.addEventListener("click", () => {
      if (div.classList.contains("selected")) {
        div.classList.remove("selected");
        selectedSeats.delete(i);
      } else {
        div.classList.add("selected");
          selectedSeats.add(i);
        }
      });
    }
    seatGrid.appendChild(div);
  }
}

renderSeats();

submitBtn.addEventListener("click", async () => {
  statusEl.textContent = "";
  const name = document.getElementById("name").value.trim();
  const mobile = document.getElementById("mobile").value.trim();
  const userCode = document.getElementById("userCode").value.trim();
  if (!name || !mobile || selectedSeats.size === 0) {
    statusEl.textContent = "Please enter Name, Mobile and select at least one seat.";
    statusEl.style.color = "crimson";
    return;
  }
  const payload = { user_code: userCode, name, mobile, seats: Array.from(selectedSeats) };
  try {
    const res = await fetch("/submit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (data.ok) {
      statusEl.textContent = "Booking saved to Google Sheet.";
      statusEl.style.color = "green";
      document.querySelectorAll(".seat.selected").forEach(el => { el.classList.remove("selected"); el.classList.add("booked"); el.style.pointerEvents = "none"; });
      selectedSeats.clear();
    } else {
      statusEl.textContent = "Error: " + data.message;
      statusEl.style.color = "crimson";
    }
  } catch (err) {
    statusEl.textContent = "Network error: " + err.message;
    statusEl.style.color = "crimson";
  }
});
