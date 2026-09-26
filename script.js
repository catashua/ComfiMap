/* ---------- Map ---------- */

const map = L.map("map", { zoomControl: false }).setView([40.735, -73.97], 12);
L.control.zoom({ position: "bottomright" }).addTo(map);

L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  attribution: "© OpenStreetMap © CARTO",
}).addTo(map);

let layers = [];

/* ---------- Address -> coordinates ---------- */

async function geocode(address) {
  const url = "https://geosearch.planninglabs.nyc/v2/search?text=" + encodeURIComponent(address);
  const res = await fetch(url);
  const data = await res.json();
  if (data.features.length === 0) return null;
  const [lon, lat] = data.features[0].geometry.coordinates;
  return { lat, lon };
}

/* ---------- Route me! button ---------- */

document.getElementById("routeBtn").addEventListener("click", async () => {
  const message = document.getElementById("message");
  const startText = document.getElementById("start").value;
  const endText = document.getElementById("end").value;

  message.textContent = "Finding addresses...";

  const start = await geocode(startText);
  const end = await geocode(endText);

  if (!start || !end) {
    message.textContent = "Couldn't find one of those addresses.";
    return;
  }

  layers.forEach((l) => map.removeLayer(l));

  const startMarker = L.marker([start.lat, start.lon]).addTo(map).bindPopup("Start");
  const endMarker = L.marker([end.lat, end.lon]).addTo(map).bindPopup("End");

  // Placeholder until the backend returns a real route
  const line = L.polyline(
    [[start.lat, start.lon], [end.lat, end.lon]],
    { color: "#0d9488", weight: 5 }
  ).addTo(map);

  layers = [startMarker, endMarker, line];
  map.fitBounds(line.getBounds(), { padding: [50, 50] });

  message.textContent = `Using data file ${getTimeKey()}`;
});

/* ---------- Month + hour ruler ---------- */

const FIRST_HOUR = 5;   // 5 AM
const LAST_HOUR = 19;   // 7 PM
const CELL = 70;        // width of one hour on the ruler, must match .tick in CSS

const monthSelect = document.getElementById("month");
const ruler = document.getElementById("ruler");
let currentHour = 12;

function formatHour(h) {
  if (h === 12) return "12 PM";
  return h < 12 ? `${h} AM` : `${h - 12} PM`;
}

// Matches your file naming, e.g. July 9pm -> "7_21"
function getTimeKey() {
  return `${monthSelect.value}_${currentHour}`;
}

function onTimeChange() {
  console.log("Selected data file:", getTimeKey());
  // Later: update the shadow layer here
}

function buildRuler() {
  ruler.innerHTML = "";
  ruler.appendChild(Object.assign(document.createElement("div"), { className: "ruler-spacer" }));
  for (let h = FIRST_HOUR; h <= LAST_HOUR; h++) {
    const tick = document.createElement("div");
    tick.className = "tick";
    tick.dataset.hour = h;
    tick.textContent = formatHour(h);
    ruler.appendChild(tick);
  }
  ruler.appendChild(Object.assign(document.createElement("div"), { className: "ruler-spacer" }));
  sizeSpacers();
}

// Empty space at both ends so the first and last hour can reach the arrow
function sizeSpacers() {
  const w = ruler.clientWidth / 2 - CELL / 2;
  ruler.querySelectorAll(".ruler-spacer").forEach((s) => (s.style.width = w + "px"));
}

function scrollToHour(h, smooth = true) {
  h = Math.max(FIRST_HOUR, Math.min(LAST_HOUR, h));
  ruler.scrollTo({ left: (h - FIRST_HOUR) * CELL, behavior: smooth ? "smooth" : "auto" });
}

function highlight() {
  ruler.querySelectorAll(".tick").forEach((t) => {
    t.classList.toggle("active", Number(t.dataset.hour) === currentHour);
  });
}

// Whatever is under the arrow becomes the selected hour
ruler.addEventListener("scroll", () => {
  let h = FIRST_HOUR + Math.round(ruler.scrollLeft / CELL);
  h = Math.max(FIRST_HOUR, Math.min(LAST_HOUR, h));
  if (h !== currentHour) {
    currentHour = h;
    highlight();
    onTimeChange();
  }
});

// Click-and-drag with a mouse (touchscreens and trackpads already scroll natively)
let dragStartX = 0;
let dragStartScroll = 0;
let dragging = false;
let moved = false;

ruler.addEventListener("pointerdown", (e) => {
  if (e.pointerType !== "mouse") return;
  dragging = true;
  moved = false;
  dragStartX = e.clientX;
  dragStartScroll = ruler.scrollLeft;
  ruler.classList.add("dragging");
  ruler.setPointerCapture(e.pointerId);
});

ruler.addEventListener("pointermove", (e) => {
  if (!dragging) return;
  const dx = e.clientX - dragStartX;
  if (Math.abs(dx) > 3) moved = true;
  ruler.scrollLeft = dragStartScroll - dx;
});

ruler.addEventListener("pointerup", (e) => {
  if (!dragging) return;
  dragging = false;
  ruler.classList.remove("dragging");
  if (moved) {
    scrollToHour(currentHour);
  } else {
    const tick = document.elementFromPoint(e.clientX, e.clientY)?.closest(".tick");
    if (tick) scrollToHour(Number(tick.dataset.hour));
  }
});

// Mouse wheel moves one hour per notch
let wheelLock = false;
ruler.addEventListener("wheel", (e) => {
  if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
  e.preventDefault();
  if (wheelLock) return;
  wheelLock = true;
  scrollToHour(currentHour + Math.sign(e.deltaY));
  setTimeout(() => (wheelLock = false), 150);
}, { passive: false });

window.addEventListener("resize", () => {
  sizeSpacers();
  scrollToHour(currentHour, false);
});

monthSelect.addEventListener("change", onTimeChange);

buildRuler();
scrollToHour(currentHour, false);
highlight();
onTimeChange();