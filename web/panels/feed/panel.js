// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Items arrive as plain text with http(s)-only links -- the collector strips
// markup and rejects other schemes before writing the snapshot. Rendering with
// textContent keeps that guarantee end to end.

export function render(root, { data, el }) {
  const feed = data.amsat?.data;
  if (!feed?.items?.length) {
    root.replaceChildren(el("p", "empty", "waiting for the first collector cycle…"));
    return;
  }

  const list = el("ul", "feed");
  for (const item of feed.items.slice(0, 8)) {
    const li = el("li");
    if (item.link) {
      const link = el("a", null, item.title || item.link);
      link.href = item.link;
      link.target = "_blank";
      link.rel = "noopener noreferrer nofollow";
      li.append(link);
    } else {
      li.append(el("span", null, item.title));
    }
    if (item.published) li.append(el("span", "when", item.published));
    list.append(li);
  }
  root.replaceChildren(list);
}
