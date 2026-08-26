// Hammunition Hill - panel host.
//
// The browser only ever talks to this origin. Snapshots are polled as static
// JSON files; there is no API to call and no query to construct. Panels get
// their data handed to them and render into a container they do not own.

const GRID = document.getElementById("grid");
const STATUS = document.getElementById("status");
const STATION_EL = document.getElementById("station");

// Snapshot poll interval. Files are small and local, so this is cheap; the
// collector's own upstream intervals are what actually rate-limit anything.
const POLL_MS = 10_000;

/** @type {Map<string, object>} latest snapshot per source id */
const snapshots = new Map();
/** @type {Array<{manifest: object, module: object, root: HTMLElement}>} */
const panels = [];

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text; // never innerHTML
  return node;
};

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

function relativeAge(iso) {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (seconds < 90) return `${Math.round(seconds)}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

function buildFrame(manifest) {
  const panel = el("section", "panel");
  panel.dataset.panel = manifest.id;
  // A panel may ask for more grid columns; the CSS caps it at what fits.
  if (manifest.span > 1) panel.style.setProperty("--span", String(manifest.span));

  const head = el("div", "panel-head");
  head.append(
    el("span", "panel-title", manifest.name),
    el("span", `tier tier-${manifest.tier}`, `T${manifest.tier}`),
  );
  const age = el("span", "panel-age", "");
  head.append(age);

  const body = el("div", "panel-body");
  panel.append(head, body);
  GRID.append(panel);
  return { body, age };
}

/**
 * Freshness is shown, never hidden. A stale panel and a blank panel are
 * different problems, and with the WAN down that distinction is the whole
 * point of keeping the last good snapshot.
 */
function updateAge(entry) {
  const relevant = entry.manifest.sources
    .map((id) => snapshots.get(id))
    .filter(Boolean);
  if (relevant.length === 0) {
    entry.age.textContent = entry.manifest.tier === 0 ? "" : "no data";
    entry.age.className = "panel-age";
    return;
  }

  const oldest = relevant.reduce((a, b) =>
    Date.parse(a.fetched_at) < Date.parse(b.fetched_at) ? a : b,
  );
  const failed = relevant.find((s) => s.error);
  const isStale =
    (Date.now() - Date.parse(oldest.fetched_at)) / 1000 >
    (oldest.stale_after_seconds ?? Infinity);

  entry.age.textContent = failed
    ? `${relativeAge(oldest.fetched_at)} · fetch failed`
    : relativeAge(oldest.fetched_at);
  entry.age.className =
    "panel-age" + (failed ? " failed" : isStale ? " stale" : "");
}

function renderPanel(entry, station) {
  const data = {};
  for (const id of entry.manifest.sources) data[id] = snapshots.get(id) ?? null;
  try {
    entry.module.render(entry.body, { data, station, el });
  } catch (err) {
    entry.body.replaceChildren(el("p", "error", `panel error: ${err.message}`));
  }
  updateAge(entry);
}

async function poll(station) {
  const wanted = new Set(panels.flatMap((p) => p.manifest.sources));
  const results = await Promise.allSettled(
    [...wanted].map(async (id) => [id, await getJSON(`./data/${id}.json`)]),
  );

  let missing = 0;
  for (const result of results) {
    if (result.status === "fulfilled") {
      const [id, snapshot] = result.value;
      snapshots.set(id, snapshot);
    } else {
      missing += 1;
    }
  }

  for (const entry of panels) renderPanel(entry, station);

  STATUS.textContent = missing
    ? `${wanted.size - missing}/${wanted.size} sources · collector may still be starting`
    : `${wanted.size} sources · updated ${new Date().toLocaleTimeString()}`;
}

async function main() {
  let enabled = [];
  let station = {};

  // The panel list and each panel's manifest are static files. Station details
  // come from a snapshot the collector writes at startup, so web/ stays
  // template-free and can be served by any static file server.
  try {
    const index = await getJSON("./panels/index.json");
    enabled = index.enabled ?? [];
  } catch (err) {
    STATUS.textContent = "could not load panel index";
    GRID.append(el("p", "error", `panels/index.json: ${err.message}`));
    return;
  }

  try {
    station = (await getJSON("./data/station.json")).data ?? {};
  } catch {
    // Not fatal: tier 0 panels degrade to UTC-only without a grid square.
    station = {};
  }

  STATION_EL.textContent = [station.callsign, station.grid]
    .filter(Boolean)
    .join(" \u00b7 ");

  for (const id of enabled) {
    try {
      const manifest = await getJSON(`./panels/${id}/panel.json`);
      const module = await import(`./panels/${id}/panel.js`);
      const { body, age } = buildFrame(manifest);
      panels.push({ manifest, module, body, age });
    } catch (err) {
      console.error(`panel ${id} failed to load`, err);
      GRID.append(el("p", "error", `panel ${id}: ${err.message}`));
    }
  }

  await poll(station);
  setInterval(() => poll(station), POLL_MS);

  // Tier 0 panels tick on their own clock, independent of any fetch.
  setInterval(() => {
    for (const entry of panels) {
      if (entry.manifest.tier === 0) renderPanel(entry, station);
    }
  }, 1000);
}

main();
