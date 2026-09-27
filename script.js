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

// Address suggestions are nudged towards this point (FiDi)
const FIDI_CENTER = { lat: 40.7075, lon: -74.0110 };

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
  .setView([FIDI_CENTER.lat, FIDI_CENTER.lon], 17);
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

/* =========================================================
   Tmrt shadow layers
   ========================================================= */

const COLORS = [
  [37, 99, 235],    // mid blue (coldest) — was deep navy, now more vivid
  [59, 149, 220],   // brighter blue — was more muted/grayish
  [116, 173, 209],  // light blue
  [171, 217, 233],  // pale blue-green
  [224, 243, 219],  // near-white green
  [254, 224, 144],  // pale yellow
  [253, 174, 97],   // orange
  [244, 109, 67],   // red-orange
  [215, 48, 39],    // red
  [165, 0, 38],     // deep red (hottest)
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
let dataBounds = null;   // the area covered by the Tmrt rasters

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

  const anyLayer = Object.values(hourLayers)[0];
  if (anyLayer) {
    dataBounds = anyLayer.getBounds();
    if (firstFit) map.fitBounds(dataBounds);
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
   Custom pins
   ========================================================= */

function createPin(color, label) {
  return L.divIcon({
    className: "custom-pin",
    html: `<div class="pin" style="--pin-color:${color}"><span>${label}</span></div>`,
    iconSize: [32, 42],
    iconAnchor: [16, 40], // tip of the teardrop touches the actual location
  });
}

const startIcon = createPin("rgb(154, 69, 57)", "A");   // was rgb(13, 150, 139)
const endIcon = createPin("rgb(154, 69, 57)", "B");     // was rgb(13, 150, 139)

/* =========================================================
   Address search + suggestions as you type
   ========================================================= */

const GEOSEARCH = "https://geosearch.planninglabs.nyc/v2";

// "100 BROADWAY, New York, NY, USA" -> "100 Broadway"
function prettyName(feature) {
  const raw = feature.properties.name || feature.properties.label.split(",")[0];
  return raw
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bB'Way\b/g, "Broadway");
}

function inDataArea(lat, lon) {
  return !dataBounds || dataBounds.contains([lat, lon]);
}

// Returns up to 6 places, nearest to FiDi and inside the shade data area first
async function searchAddresses(text, endpoint = "autocomplete") {
  const url = `${GEOSEARCH}/${endpoint}?text=${encodeURIComponent(text)}` +
    `&focus.point.lat=${FIDI_CENTER.lat}&focus.point.lon=${FIDI_CENTER.lon}`;
  const res = await fetch(url);
  const data = await res.json();

  const seen = new Set();
  const places = [];
  for (const f of data.features) {
    const [lon, lat] = f.geometry.coordinates;
    const key = `${lat.toFixed(5)},${lon.toFixed(5)}`;
    if (seen.has(key)) continue;   // e.g. "B'WAY" and "BROADWAY" at the same spot
    seen.add(key);
    places.push({
      name: prettyName(f),
      detail: [f.properties.borough, f.properties.postalcode].filter(Boolean).join(" "),
      lat,
      lon,
      inArea: inDataArea(lat, lon),
    });
  }
  places.sort((a, b) => Number(b.inArea) - Number(a.inArea));
  return places.slice(0, 6);
}

function attachAutocomplete(input, list) {
  let items = [];
  let active = -1;
  let timer = null;
  let requestId = 0;

  function close() {
    list.hidden = true;
    items = [];
    active = -1;
  }

  function render() {
    list.innerHTML = "";
    if (items.length === 0) return close();
    items.forEach((place, i) => {
      const li = document.createElement("li");
      li.className = "suggestion" + (i === active ? " active" : "");

      const name = document.createElement("span");
      name.className = "suggestion-name";
      name.textContent = place.name;

      const detail = document.createElement("span");
      detail.className = "suggestion-detail" + (place.inArea ? "" : " suggestion-outside");
      detail.textContent = place.inArea ? place.detail : `${place.detail} · outside shade data area`;

      li.append(name, detail);
      // mousedown instead of click, so it fires before the text box loses focus
      li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        choose(i);
      });
      list.appendChild(li);
    });
    list.hidden = false;
  }

  function choose(i) {
    const place = items[i];
    input.value = place.name;
    input.dataset.lat = place.lat;
    input.dataset.lon = place.lon;
    close();
  }

  input.addEventListener("input", () => {
    delete input.dataset.lat;   // typing again means the old pick no longer applies
    delete input.dataset.lon;
    clearTimeout(timer);
    const text = input.value.trim();
    if (text.length < 2) return close();

    // Wait until the user pauses typing for 200ms before searching
    timer = setTimeout(async () => {
      const id = ++requestId;
      try {
        const results = await searchAddresses(text);
        if (id !== requestId) return;   // a newer search already started
        items = results;
        active = -1;
        render();
      } catch {
        close();
      }
    }, 200);
  });

  input.addEventListener("keydown", (e) => {
    const open = !list.hidden && items.length > 0;
    if (e.key === "ArrowDown" && open) {
      e.preventDefault();
      active = (active + 1) % items.length;
      render();
    } else if (e.key === "ArrowUp" && open) {
      e.preventDefault();
      active = (active - 1 + items.length) % items.length;
      render();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (open) choose(active >= 0 ? active : 0);
      else document.getElementById("routeBtn").click();
    } else if (e.key === "Escape") {
      close();
    }
  });

  input.addEventListener("blur", () => setTimeout(close, 100));
}

const startInput = document.getElementById("start");
const endInput = document.getElementById("end");
attachAutocomplete(startInput, document.getElementById("startSuggestions"));
attachAutocomplete(endInput, document.getElementById("endSuggestions"));

// Uses the suggestion the user picked, or searches for whatever they typed
async function getPoint(input) {
  if (input.dataset.lat) {
    return { lat: Number(input.dataset.lat), lon: Number(input.dataset.lon) };
  }
  const text = input.value.trim();
  if (!text) return null;
  const results = await searchAddresses(text, "search");
  return results[0] ?? null;
}

/* =========================================================
   Route me! / Update time + candidate routes + slider
   ========================================================= */

let routeLayers = [];
let candidateRoutes = [];
let routeLineLayers = []; // parallel array of {outline, line}
let lastStart = null;
let lastEnd = null;

// TEMP stand-in until the routing backend is wired up.
// Replace this with a fetch() to your Dinkelbach/Bellman-Ford endpoint,
// returning routes already sorted fastest -> coolest.
function mockRoutes(start, end, n = 5) {
  const routes = [];
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    const mid = {
      lat: (start.lat + end.lat) / 2 + (t - 0.5) * 0.004,
      lon: (start.lon + end.lon) / 2 + (t - 0.5) * 0.004,
    };
    routes.push({
      latlngs: [[start.lat, start.lon], [mid.lat, mid.lon], [end.lat, end.lon]],
      duration: 600 + t * 300,   // seconds — fastest first
      meanTmrt: 55 - t * 15,     // °C — coolest last
    });
  }
  return routes;
}

function drawCandidateRoutes(routes) {
  routeLineLayers.forEach(({ outline, line }) => {
    map.removeLayer(outline);
    map.removeLayer(line);
  });
  routeLineLayers = routes.map((r, i) => {
    const outline = L.polyline(r.latlngs, { color: "white", weight: 14, opacity: 0.9 }).addTo(map);
    const line = L.polyline(r.latlngs, { color: "#999", weight: 6, opacity: 0.5 }).addTo(map);

    // Clicking either the colored line or its white outline selects that route
    const selectThis = () => {
      document.getElementById("routeRange").value = i;
      highlightRoute(i);
    };
    line.on("click", selectThis);
    outline.on("click", selectThis);

    return { outline, line };
  });

  // Fit once, when routes first appear — not on every slider move
  const group = L.featureGroup(routeLineLayers.map((r) => r.line));
  map.fitBounds(group.getBounds(), { padding: [60, 60] });
}

function highlightRoute(index) {
  routeLineLayers.forEach(({ line }, i) => {
    const active = i === index;
    line.setStyle({
      color: active ? "#9a4539" : "#999",   // was "#0d9488" : "#999"
      weight: active ? 9 : 6,
      opacity: active ? 1 : 0.5,
    });
    if (active) line.bringToFront();
  });
  highlightTableRow(index);
}

function formatHourFull(h) {
  return formatHour(h).replace(" ", ":00 "); // "6 PM" -> "6:00 PM"
}

function buildRouteSlider(routes) {
  const slider = document.getElementById("routeRange");
  const ticks = document.getElementById("routeTicks");
  const wrap = document.getElementById("routeSlider");
  const summary = document.getElementById("routeSummary");

  slider.max = routes.length - 1;
  slider.value = 0;
  ticks.innerHTML = "";
  routes.forEach((_, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    ticks.appendChild(opt);
  });

  wrap.hidden = false;

  const altCount = routes.length - 1;
  summary.innerHTML =
    `<span class="summary-number">${altCount}</span> alternative route${altCount === 1 ? "" : "s"} ` +
    `at <span class="summary-number">${formatHourFull(currentHour)}</span>!`;

  highlightRoute(0);
  buildRouteTable(routes);
}

document.getElementById("routeRange").addEventListener("input", (e) => {
  highlightRoute(Number(e.target.value));
});

function routeDistanceMeters(latlngs) {
  let d = 0;
  for (let i = 1; i < latlngs.length; i++) {
    d += L.latLng(latlngs[i - 1]).distanceTo(latlngs[i]);
  }
  return d;
}

const WALK_SPEED_MPS = 1.4; // average walking speed, ~5 km/h

function formatWalkTime(distanceMeters) {
  return `${Math.round(distanceMeters / WALK_SPEED_MPS / 60)} min`;
}

function buildRouteTable(routes) {
  const tbody = document.getElementById("routeTableBody");
  document.getElementById("routeTable").hidden = false;

  const distances = routes.map((r) => routeDistanceMeters(r.latlngs));
  const shortestIdx = distances.indexOf(Math.min(...distances));
  const baselineTmrt = routes[shortestIdx].meanTmrt;

  tbody.innerHTML = "";
  routes.forEach((r, i) => {
    const coolerPct = ((baselineTmrt - r.meanTmrt) / baselineTmrt) * 100;
    const icon =
      i === 0 ? '<span class="icon-lightning"></span>' :
      i === routes.length - 1 ? '<span class="icon-snowflake"></span>' :
      "";

    const tr = document.createElement("tr");
    tr.dataset.index = i;
    tr.innerHTML = `
      <td>${i + 1}${icon}</td>
      <td>${(distances[i] / 1000).toFixed(2)} km</td>
      <td>${formatWalkTime(distances[i])}</td>
      <td>${i === shortestIdx ? "—" : coolerPct.toFixed(0) + "%"}</td>
    `;
    tr.addEventListener("click", () => {
      document.getElementById("routeRange").value = i;
      highlightRoute(i);
    });
    tbody.appendChild(tr);
  });
}

function highlightTableRow(index) {
  document.querySelectorAll("#routeTableBody tr").forEach((tr) => {
    tr.classList.toggle("active", Number(tr.dataset.index) === index);
  });
}

// Shared by "Route me!" and "Update time" — same logic, different trigger
async function runRouting(start, end) {
  routeLayers.forEach((l) => map.removeLayer(l));
  routeLayers = [];

  routeLayers.push(
    L.marker([start.lat, start.lon], { icon: startIcon }).addTo(map).bindPopup("Start"),
    L.marker([end.lat, end.lon], { icon: endIcon }).addTo(map).bindPopup("End"),
  );

  // TODO: swap for real backend call once routing endpoint is ready
  candidateRoutes = mockRoutes(start, end);
  drawCandidateRoutes(candidateRoutes);
  buildRouteSlider(candidateRoutes);

  if (!inDataArea(start.lat, start.lon) || !inDataArea(end.lat, end.lon)) {
    message.textContent = "Heads up: one of those addresses is outside the area we have shade data for.";
  } else {
    message.textContent = "";
  }
}

document.getElementById("routeBtn").addEventListener("click", async () => {
  message.textContent = "Finding addresses...";

  let start, end;
  try {
    [start, end] = await Promise.all([getPoint(startInput), getPoint(endInput)]);
  } catch (err) {
    message.textContent = "Something went wrong looking up those addresses.";
    return;
  }

  if (!start || !end) {
    message.textContent = "Couldn't find one of those addresses.";
    return;
  }

  lastStart = start;
  lastEnd = end;
  document.getElementById("updateTimeBtn").hidden = false;

  // The button just took up space in .time-bar, so the ruler shrank —
  // recompute spacer widths and re-center the arrow on the current hour
  sizeSpacers();
  scrollToHour(currentHour, false);

  await runRouting(start, end);
});

document.getElementById("updateTimeBtn").addEventListener("click", async () => {
  if (!lastStart || !lastEnd) return;
  message.textContent = "Recalculating...";
  await runRouting(lastStart, lastEnd);
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