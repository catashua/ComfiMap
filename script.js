/* =========================================================
   SETTINGS
   ========================================================= */

const TIF_FOLDER = "/data/FiDi/clipped/";
const DATA_YEAR = 2025;   // year in the Tmrt filenames

// Daylight hours you have data for, per month: [first hour, last hour]
const HOURS_BY_MONTH = {
  6: [5, 19],   // June:   5 AM – 7 PM
  7: [6, 19],   // July:   6 AM – 7 PM
  8: [6, 18],   // August: 6 AM – 6 PM
};

// How strong the heat colours are (0 = invisible, 1 = solid)
const RASTER_OPACITY = 0.6;

// Fixed colour range, so colours mean the same thing at every hour
const TMRT_MIN = 20;
const TMRT_MAX = 65;

// Which base map opens first (must match a name in BASEMAPS below)
const DEFAULT_BASEMAP = "OpenStreetMap (soft)";

// Builds e.g. "Tmrt_2025_006_0500D.tif" for June 5 AM
function tifName(month, hour) {
  const m = String(month).padStart(3, "0");
  const h = String(hour).padStart(2, "0") + "00";
  return `Tmrt_${DATA_YEAR}_${m}_${h}D.tif`;
}

/* =========================================================
   Map
   Layer order, bottom to top:
     base map -> Tmrt colours -> routes -> street names
   ========================================================= */

const map = L.map("map", { zoomControl: false, maxZoom: 20 })
  .setView([40.7075, -74.0110], 17); // FiDi
L.control.zoom({ position: "bottomright" }).addTo(map);

map.createPane("tmrt");
map.getPane("tmrt").style.zIndex = 350;

map.createPane("labels");
map.getPane("labels").style.zIndex = 650;
map.getPane("labels").style.pointerEvents = "none";

// Base maps. None of these need an API key.
const OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTR = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const NYC_ATTR = '© <a href="https://maps.nyc.gov">City of New York</a>';
const ESRI_ATTR = "Imagery © Esri, Maxar, Earthstar Geographics";

const nycLabels = L.tileLayer("https://maps.nyc.gov/xyz/1.0.0/carto/label/{z}/{x}/{y}.png8", {
  pane: "labels", minZoom: 8, maxZoom: 20,
});

// For each base map: its tiles, which street-name layer goes on top (if any),
// and whether the heat colours should blend into it
const BASEMAPS = {
  "OpenStreetMap (soft)": {
    tiles: L.tileLayer(OSM_URL, {
      attribution: OSM_ATTR, maxZoom: 20, maxNativeZoom: 19, className: "osm-soft",
    }),
    labels: null,    // street names are already in the OSM tiles
    blend: true,
  },
  "OpenStreetMap (classic)": {
    tiles: L.tileLayer(OSM_URL, {
      attribution: OSM_ATTR, maxZoom: 20, maxNativeZoom: 19,
    }),
    labels: null,
    blend: false,
  },
  "NYC street map": {
    tiles: L.tileLayer("https://maps.nyc.gov/xyz/1.0.0/carto/basemap/{z}/{x}/{y}.jpg", {
      attribution: NYC_ATTR, minZoom: 8, maxZoom: 20,
    }),
    labels: nycLabels,
    blend: true,
  },
  "Aerial photo": {
    tiles: L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { attribution: ESRI_ATTR, maxZoom: 20, maxNativeZoom: 19 }
    ),
    labels: nycLabels,
    blend: false,
  },
};

let activeLabels = null;

function useBasemap(name) {
  const b = BASEMAPS[name];
  if (activeLabels) map.removeLayer(activeLabels);
  activeLabels = b.labels;
  if (activeLabels) activeLabels.addTo(map);
  document.body.classList.toggle("no-blend", !b.blend);
}

BASEMAPS[DEFAULT_BASEMAP].tiles.addTo(map);
useBasemap(DEFAULT_BASEMAP);

const baseLayers = {};
Object.entries(BASEMAPS).forEach(([name, b]) => (baseLayers[name] = b.tiles));
L.control.layers(baseLayers, null, { position: "topright" }).addTo(map);

map.on("baselayerchange", (e) => useBasemap(e.name));

const message = document.getElementById("message");
document.getElementById("legendMin").textContent = `${TMRT_MIN}°C`;
document.getElementById("legendMax").textContent = `${TMRT_MAX}°C`;

/* =========================================================
   Tmrt shadow layers
   ========================================================= */

const COLORS = [
  [49, 54, 149], [69, 117, 180], [116, 173, 209],
  [254, 224, 144], [244, 109, 67], [165, 0, 38],
];

function tmrtColor(v) {
  let t = (v - TMRT_MIN) / (TMRT_MAX - TMRT_MIN);
  t = Math.max(0, Math.min(1, t)) * (COLORS.length - 1);
  const i = Math.min(Math.floor(t), COLORS.length - 2);
  const f = t - i;
  const [r, g, b] = COLORS[i].map((c, k) => Math.round(c + (COLORS[i + 1][k] - c) * f));
  return `rgb(${r},${g},${b})`;
}

let hourLayers = {};     // hour -> Leaflet layer, for the current month
let loadedMonth = null;
let firstFit = true;

async function loadTif(month, hour) {
  const res = await fetch(TIF_FOLDER + tifName(month, hour));
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const georaster = await parseGeoraster(await res.arrayBuffer());
  return new GeoRasterLayer({
    georaster,
    pane: "tmrt",
    opacity: 0,
    resolution: 128,
    pixelValuesToColorFn: ([v]) => {
      if (v === georaster.noDataValue || v == null || Number.isNaN(v) || v < -100) return null;
      return tmrtColor(v);
    },
  });
}

// Loads every hour of the month up front, so dragging the ruler is instant
async function loadMonth(month) {
  if (month === loadedMonth) return;
  Object.values(hourLayers).forEach((l) => map.removeLayer(l));
  hourLayers = {};
  loadedMonth = month;

  message.textContent = "Loading shadow maps...";
  const failed = [];

  await Promise.all(hoursFor(month).map(async (h) => {
    try {
      const layer = await loadTif(month, h);
      if (loadedMonth !== month) return;   // user switched months while loading
      hourLayers[h] = layer.addTo(map);
    } catch (err) {
      console.error(tifName(month, h), err);
      failed.push(`${tifName(month, h)} (${err.message})`);
    }
  }));

  if (loadedMonth !== month) return;

  message.textContent = failed.length ? `Couldn't load: ${failed.join(", ")}` : "";

  if (firstFit) {
    const anyLayer = Object.values(hourLayers)[0];
    if (anyLayer) map.fitBounds(anyLayer.getBounds());
    firstFit = false;
  }

  showHour(currentHour);
}

function showHour(hour) {
  Object.entries(hourLayers).forEach(([h, layer]) => {
    layer.setOpacity(Number(h) === hour ? RASTER_OPACITY : 0);
  });
}

/* =========================================================
   Day picker: user picks a day, we only use its month
   ========================================================= */

const dayInput = document.getElementById("day");
const MONTHS = Object.keys(HOURS_BY_MONTH).map(Number).sort((a, b) => a - b);
const YEAR_NOW = new Date().getFullYear();
const pad = (n) => String(n).padStart(2, "0");

function lastDayOf(month) {
  return new Date(YEAR_NOW, month, 0).getDate();
}

// Only allow days inside the months we have data for
dayInput.min = `${YEAR_NOW}-${pad(MONTHS[0])}-01`;
dayInput.max = `${YEAR_NOW}-${pad(MONTHS.at(-1))}-${lastDayOf(MONTHS.at(-1))}`;

// Default to today if it's in range, otherwise July 15
const today = new Date();
const todayStr = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
dayInput.value = todayStr >= dayInput.min && todayStr <= dayInput.max
  ? todayStr
  : `${YEAR_NOW}-07-15`;

let lastValidDay = dayInput.value;

// "2026-07-15" -> 7
function selectedMonth() {
  return Number(dayInput.value.split("-")[1]);
}

function hoursFor(month) {
  const [first, last] = HOURS_BY_MONTH[month];
  const list = [];
  for (let h = first; h <= last; h++) list.push(h);
  return list;
}

/* =========================================================
   Address -> coordinates + Route me! button
   ========================================================= */

let routeLayers = [];

async function geocode(address) {
  const url = "https://geosearch.planninglabs.nyc/v2/search?text=" + encodeURIComponent(address);
  const res = await fetch(url);
  const data = await res.json();
  if (data.features.length === 0) return null;
  const [lon, lat] = data.features[0].geometry.coordinates;
  return { lat, lon };
}

// Draws a route with a white outline so it stands out on any base map and the heat colours
function drawRoute(latlngs, color) {
  const outline = L.polyline(latlngs, { color: "white", weight: 9, opacity: 0.9 }).addTo(map);
  const line = L.polyline(latlngs, { color, weight: 5 }).addTo(map);
  routeLayers.push(outline, line);
  return line;
}

document.getElementById("routeBtn").addEventListener("click", async () => {
  const startText = document.getElementById("start").value;
  const endText = document.getElementById("end").value;

  message.textContent = "Finding addresses...";

  const start = await geocode(startText);
  const end = await geocode(endText);

  if (!start || !end) {
    message.textContent = "Couldn't find one of those addresses.";
    return;
  }

  routeLayers.forEach((l) => map.removeLayer(l));
  routeLayers = [];

  routeLayers.push(
    L.marker([start.lat, start.lon]).addTo(map).bindPopup("Start"),
    L.marker([end.lat, end.lon]).addTo(map).bindPopup("End"),
  );

  // Placeholder until the backend returns a real route
  const line = drawRoute([[start.lat, start.lon], [end.lat, end.lon]], "#111");
  map.fitBounds(line.getBounds(), { padding: [60, 60] });

  message.textContent = `Would route with route_${getTimeKey()}.gpkg`;
});

/* =========================================================
   Hour ruler
   ========================================================= */

const CELL = 70; // must match .tick width in CSS
const ruler = document.getElementById("ruler");
let hours = [];        // hours available for the selected month
let currentHour = 12;

function formatHour(h) {
  if (h === 12) return "12 PM";
  return h < 12 ? `${h} AM` : `${h - 12} PM`;
}

// e.g. any day in June at 6 AM -> "06_06", matching route_06_06.gpkg
function getTimeKey() {
  return `${pad(selectedMonth())}_${pad(currentHour)}`;
}

function onTimeChange() {
  showHour(currentHour);
}

function closestHour(h) {
  return hours.reduce((best, x) => (Math.abs(x - h) < Math.abs(best - h) ? x : best), hours[0]);
}

function buildRuler() {
  hours = hoursFor(selectedMonth());
  currentHour = closestHour(currentHour);

  ruler.innerHTML = "";
  ruler.appendChild(Object.assign(document.createElement("div"), { className: "ruler-spacer" }));
  hours.forEach((h) => {
    const tick = document.createElement("div");
    tick.className = "tick";
    tick.dataset.hour = h;
    tick.textContent = formatHour(h);
    ruler.appendChild(tick);
  });
  ruler.appendChild(Object.assign(document.createElement("div"), { className: "ruler-spacer" }));
  sizeSpacers();
  scrollToHour(currentHour, false);
  highlight();
}

// Empty space at both ends so the first and last hour can reach the arrow
function sizeSpacers() {
  const w = ruler.clientWidth / 2 - CELL / 2;
  ruler.querySelectorAll(".ruler-spacer").forEach((s) => (s.style.width = w + "px"));
}

function scrollToIndex(i, smooth = true) {
  i = Math.max(0, Math.min(hours.length - 1, i));
  ruler.scrollTo({ left: i * CELL, behavior: smooth ? "smooth" : "auto" });
}

function scrollToHour(h, smooth = true) {
  scrollToIndex(hours.indexOf(closestHour(h)), smooth);
}

function highlight() {
  ruler.querySelectorAll(".tick").forEach((t) => {
    t.classList.toggle("active", Number(t.dataset.hour) === currentHour);
  });
}

// Whatever is under the arrow becomes the selected hour
ruler.addEventListener("scroll", () => {
  const i = Math.max(0, Math.min(hours.length - 1, Math.round(ruler.scrollLeft / CELL)));
  const h = hours[i];
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
  scrollToIndex(hours.indexOf(currentHour) + Math.sign(e.deltaY));
  setTimeout(() => (wheelLock = false), 150);
}, { passive: false });

window.addEventListener("resize", () => {
  sizeSpacers();
  scrollToHour(currentHour, false);
});

// Changing the day only reloads data if the MONTH changed
dayInput.addEventListener("change", () => {
  if (!dayInput.value || !HOURS_BY_MONTH[selectedMonth()]) {
    dayInput.value = lastValidDay;
    return;
  }
  lastValidDay = dayInput.value;
  buildRuler();
  loadMonth(selectedMonth());
});

/* =========================================================
   Start up
   ========================================================= */

buildRuler();
loadMonth(selectedMonth());