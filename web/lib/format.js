// Shared rendering helpers. Everything here builds DOM nodes or returns strings
// destined for textContent -- nothing in this file ever produces markup.

/** Remember a per-viewer preference. Never leaves this browser. */
export function remember(key, value) {
  try {
    localStorage.setItem(`hh.${key}`, JSON.stringify(value));
  } catch {
    // Private windows and blocked site data both throw. A forgotten filter is
    // not worth breaking a panel over.
  }
}

export function recall(key, fallback) {
  try {
    const raw = localStorage.getItem(`hh.${key}`);
    return raw === null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}

/** kHz with a thousands separator, e.g. 14074.0 -> "14 074.0". */
export function khz(value) {
  if (value === null || value === undefined) return "—";
  const [whole, fraction = "0"] = Number(value).toFixed(1).split(".");
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, " ")}.${fraction}`;
}

export function relativeAge(iso) {
  if (!iso) return "";
  const seconds = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

/** Distance in the operator's preferred unit, remembered per browser. */
export function distance(path) {
  if (!path) return "—";
  return recall("miles", false) ? `${Math.round(path.miles)} mi` : `${Math.round(path.km)} km`;
}

/**
 * Which needed-badge a spot earns, if any. New entity outranks a band slot,
 * which outranks a mode slot -- an operator chasing DXCC drops everything for
 * the first and merely notices the third.
 */
export function neededClass(needed) {
  if (!needed || !needed.known) return null;
  if (needed.new_entity) return { cls: "need-entity", label: "NEW" };
  if (needed.new_band) return { cls: "need-band", label: "BAND" };
  if (needed.new_mode) return { cls: "need-mode", label: "MODE" };
  return null;
}

/** A row of toggle chips that writes its selection straight to localStorage. */
export function filterRow(el, { key, options, value, onChange, allLabel = "ALL" }) {
  const row = el("div", "chips");
  const entries = [[null, allLabel], ...options];

  for (const [option, label] of entries) {
    const chip = el("button", "chip", label ?? option);
    chip.type = "button";
    if (option === value) chip.classList.add("on");
    chip.setAttribute("aria-pressed", String(option === value));
    chip.addEventListener("click", () => {
      remember(key, option);
      onChange(option);
    });
    row.append(chip);
  }
  return row;
}
