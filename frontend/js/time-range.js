const STORAGE_KEY = "ha-web.time-range";

export const TIME_RANGES = [
  ["1h", "1 h"],
  ["6h", "6 h"],
  ["12h", "12 h"],
  ["1d", "1 día"],
  ["7d", "7 días"],
  ["30d", "30 días"],
  ["3m", "3 meses"],
  ["6m", "6 meses"],
  ["1y", "1 año"],
  ["forever", "Todo"],
];

const validRanges = new Set(TIME_RANGES.map(([value]) => value));

export function getSelectedRange() {
  const queryValue = new URLSearchParams(location.search).get("range");
  if (validRanges.has(queryValue)) return queryValue;

  const storedValue = localStorage.getItem(STORAGE_KEY);
  return validRanges.has(storedValue) ? storedValue : "1d";
}

export function getSelectedRangeLabel() {
  const selected = getSelectedRange();
  return TIME_RANGES.find(([value]) => value === selected)?.[1] || selected;
}

export function initTimeRangeControl() {
  const select = document.getElementById("time-range");
  if (!select) return;

  select.innerHTML = TIME_RANGES.map(([value, label]) =>
    `<option value="${value}">${label}</option>`
  ).join("");
  select.value = getSelectedRange();

  select.addEventListener("change", () => {
    localStorage.setItem(STORAGE_KEY, select.value);
    const url = new URL(location.href);
    url.searchParams.set("range", select.value);
    location.assign(url);
  });
}
