// Shareable, human-readable URL <-> app state (spec §30).
// Only compact keys; never serialise datasets.

const KEYS = {
  q: "q", // search text
  tech: "tech", // csv of technology categories
  topic: "topic", // csv of topics
  council: "council", // csv of councils
  range: "range", // 30d | 3m | 6m | 1y | all
  sel: "sel", // selected discussion id
};

export function readState() {
  const p = new URLSearchParams(location.search);
  const csv = (k) => (p.get(k) ? p.get(k).split(",").map((s) => s.trim()).filter(Boolean) : []);
  return {
    q: p.get(KEYS.q) || "",
    tech: csv(KEYS.tech),
    topic: csv(KEYS.topic),
    council: csv(KEYS.council),
    range: p.get(KEYS.range) || "6m",
    sel: p.get(KEYS.sel) || null,
  };
}

export function writeState(state, { replace = true } = {}) {
  const p = new URLSearchParams();
  if (state.q) p.set(KEYS.q, state.q);
  if (state.tech?.length) p.set(KEYS.tech, state.tech.join(","));
  if (state.topic?.length) p.set(KEYS.topic, state.topic.join(","));
  if (state.council?.length) p.set(KEYS.council, state.council.join(","));
  if (state.range && state.range !== "6m") p.set(KEYS.range, state.range);
  if (state.sel) p.set(KEYS.sel, state.sel);
  const url = `${location.pathname}${p.toString() ? "?" + p.toString() : ""}`;
  history[replace ? "replaceState" : "pushState"](null, "", url);
}
