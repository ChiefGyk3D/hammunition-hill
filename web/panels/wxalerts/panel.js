// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Active weather alerts for the operator's area.
//
// Everything else on this dashboard is about the ionosphere. This one is about
// the tower: whether to bring the beam to a safe heading, whether to pull the
// feedline, and whether the club net is about to become a SKYWARN activation.
//
// Ordering is worst-and-soonest-first, decided by the collector. The panel does
// not re-sort -- if two viewers on the same LAN see different orders because
// one of them has a different idea about tie-breaking, that is a bug waiting to
// waste somebody's afternoon.

const MAX_SHOWN = 6;

// Rendered as a countdown rather than a timestamp. "expires in 40m" is what an
// operator acts on; "2026-08-27T19:40:00-06:00" is something they have to do
// arithmetic on first, on a screen they are reading from across the shack.
function until(iso) {
  if (!iso) return "";
  const seconds = (Date.parse(iso) - Date.now()) / 1000;
  if (Number.isNaN(seconds)) return "";
  if (seconds < 0) return "expired";
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

function alertRow(el, alert) {
  const item = el("li", `wx-alert level-${alert.level}`);

  const head = el("div", "wx-alert-head");
  head.append(el("span", "wx-event", alert.event));
  const sev = el("span", "wx-sev", alert.severity);
  head.append(sev);
  const left = until(alert.expires);
  if (left) head.append(el("span", "wx-until", left === "expired" ? left : `${left} left`));
  item.append(head);

  if (alert.area) item.append(el("div", "wx-area", alert.area));

  // The instruction is what the NWS wants a person to *do*, so it wins over the
  // description when both are present and space is short.
  const body = alert.instruction || alert.headline || alert.description;
  if (body) item.append(el("div", "wx-body", body));

  return item;
}

export function render(root, { data, el }) {
  const snapshot = data.wxalerts;
  if (!snapshot) {
    root.replaceChildren(el("p", "empty", "waiting for the first collector cycle…"));
    return;
  }

  const payload = snapshot.data;
  if (!payload) {
    root.replaceChildren(
      el("p", "error", snapshot.error ? `fetch failed: ${snapshot.error}` : "no data"),
    );
    return;
  }

  const alerts = payload.alerts ?? [];
  const parts = [];

  // The quiet case is a result, not an absence, and it should look like one.
  // A blank panel means "we do not know"; this means "we asked, and there is
  // nothing in force" -- which on a summer afternoon is worth stating plainly.
  const summary = el("div", `wx-summary level-${payload.worst ?? "good"}`);
  summary.append(
    el(
      "span",
      "wx-count",
      payload.count === 0 ? "No active alerts" : `${payload.count} active`,
    ),
  );
  if (payload.by_event?.length) {
    summary.append(
      el(
        "span",
        "wx-events",
        payload.by_event
          .slice(0, 4)
          .map((e) => (e.count > 1 ? `${e.event} ×${e.count}` : e.event))
          .join(" · "),
      ),
    );
  }
  parts.push(summary);

  if (alerts.length) {
    const list = el("ul", "wx-alerts");
    for (const alert of alerts.slice(0, MAX_SHOWN)) list.append(alertRow(el, alert));
    parts.push(list);
    if (payload.count > MAX_SHOWN) {
      parts.push(
        el(
          "p",
          "count",
          payload.truncated
            ? `${MAX_SHOWN} of ${payload.shown} shown · ${payload.count} in force`
            : `${MAX_SHOWN} of ${payload.count} shown`,
        ),
      );
    }
  }

  root.replaceChildren(...parts);
}
