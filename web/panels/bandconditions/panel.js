// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// The band table every dashboard shows as a PNG, rendered from the underlying
// XML instead -- which means it is readable, themeable, and costs the operator
// no third-party image load.

const CLASS_FOR = { good: "cond-good", fair: "cond-fair", poor: "cond-poor" };

function conditionCell(el, value) {
  const cell = el("td");
  const span = el("span", `cond ${CLASS_FOR[String(value).toLowerCase()] ?? ""}`, value ?? "—");
  cell.append(span);
  return cell;
}

export function render(root, { data, el }) {
  // An ordered list, low band to high, exactly as HamQSL publishes it.
  const bands = data.hamqsl?.data?.hf_conditions ?? [];

  if (bands.length === 0) {
    root.replaceChildren(el("p", "empty", "waiting for the first collector cycle…"));
    return;
  }

  const table = el("table", "bands");
  const thead = el("thead");
  const headRow = el("tr");
  headRow.append(el("th", null, "Band"), el("th", null, "Day"), el("th", null, "Night"));
  thead.append(headRow);
  table.append(thead);

  const body = el("tbody");
  for (const entry of bands) {
    const row = el("tr");
    row.append(
      el("td", null, entry.band),
      conditionCell(el, entry.day),
      conditionCell(el, entry.night),
    );
    body.append(row);
  }
  table.append(body);
  root.replaceChildren(table);
}
