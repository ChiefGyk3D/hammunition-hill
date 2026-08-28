// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can see one at https://mozilla.org/MPL/2.0/.

// The band colour ramp, in one place.
//
// A band must be the same colour on every display or the colours stop meaning
// anything. The map and the band globes each carried a copy of this table with
// a comment promising they matched; the third consumer (reception reports) is
// where a promise becomes a maintenance bug, so now there is one table.

export const BAND_COLORS = {
  "160m": "#e05c5c", "80m": "#e08a3c", "60m": "#e0c23c", "40m": "#5cc45c",
  "30m": "#3cc4a8", "20m": "#3ca0e0", "17m": "#8a7ce0", "15m": "#e07cc4",
  "12m": "#e05c9c", "10m": "#e0603c", "6m": "#e0a83c", "2m": "#9aa4b0",
  "70cm": "#7a8490",
};

export const DEFAULT_COLOR = "#8f98a4";

/** Wavelength order, longest first — the order band lists read naturally in. */
export const BAND_ORDER = Object.keys(BAND_COLORS);

export function bandColor(band) {
  return BAND_COLORS[band] ?? DEFAULT_COLOR;
}
