// Upcoming contests. A contest that is running right now is the one piece of
// information here with any urgency, so it gets its own treatment rather than
// just being the first row.

const MAX_ROWS = 8;

function when(event) {
  const start = new Date(event.start);
  const now = new Date();
  const days = Math.round((start - now) / 86_400_000);

  if (event.active) return "on now";
  if (days <= 0) return start.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (days === 1) return "tomorrow";
  if (days < 7) return start.toLocaleDateString(undefined, { weekday: "short" });
  return start.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function render(root, { data, el }) {
  const events = data.contests?.data?.events;
  if (!events) {
    root.replaceChildren(el("p", "empty", "waiting for the first collector cycle…"));
    return;
  }
  if (events.length === 0) {
    root.replaceChildren(el("p", "empty", "nothing scheduled in the next few weeks"));
    return;
  }

  const list = el("ul", "contests");
  for (const event of events.slice(0, MAX_ROWS)) {
    const item = el("li");
    if (event.active) item.classList.add("active");

    const name = event.url ? el("a", null, event.name) : el("span", null, event.name);
    if (event.url) {
      name.href = event.url;
      name.target = "_blank";
      name.rel = "noopener noreferrer nofollow";
    }
    item.append(name, el("span", "contest-when", when(event)));
    list.append(item);
  }
  root.replaceChildren(list);
}
