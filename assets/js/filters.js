// Faceted filtering + full-text search (spec §5-§7).
// Rule: OR within a filter group, AND between different groups.
// Extensible: add a facet by adding one entry to FACETS.

// Kept in sync BY HAND with build-discussions/derive/classify-technology.mjs's
// own TECH_CATEGORIES -- this frontend copy drives only the chip list (see
// main.js's buildTechChips()); the actual filter/count logic below matches
// generically against record.categories and needs no changes when a
// category is added. A real bug (found live-verifying U4's "Data Centre"
// addition): the build-time list was updated but this one wasn't, so
// posts were correctly tagged but had no chip to filter them by.
export const TECH_CATEGORIES = ["Onshore Wind", "BESS", "OHL (Pylons)", "Substation", "Solar", "Hybrid", "Data Centre"];

// Each facet: how to get the set of values a record has for that facet.
export const FACETS = {
  tech: (r) => r.categories || [],
  topic: (r) => r.topics || [],
  council: (r) => (r.council ? [r.council] : []),
};

// Reviewed aliases for records that already carry a verified `project` field
// (10 of 3,243) -- covers real spelling variants found in the data itself,
// e.g. two records for the same project spelled "Giant's Burn Wind Farm" and
// "Giants Burn Wind Farm". Never used to attribute a project to a record
// that doesn't already have one -- see item #3 of the 2026-09-25 brief:
// "do not infer project matches; identify records whose project is unknown
// or unverified" instead.
const PROJECT_ALIASES = {
  "Giant's Burn Wind Farm": ["Giants Burn Wind Farm", "Giants Burn"],
  "Giants Burn Wind Farm": ["Giant's Burn Wind Farm", "Giant's Burn"],
};

export function tokenize(s) {
  return (s || "")
    .toLowerCase()
    .normalize("NFKC")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
}

// Build a searchable text blob from the PUBLIC indexed fields only.
export function searchBlob(r) {
  return [
    r.title,
    r.summary,
    r.bodyText,
    r.location,
    r.project,
    r.developer,
    r.council,
    r.authority,
    r.externalSource,
    ...(r.topics || []),
    ...(r.categories || []),
    ...(PROJECT_ALIASES[r.project] || []),
  ]
    .filter(Boolean)
    .join(" ");
}

export function matchesSearch(record, query) {
  const terms = tokenize(query);
  if (terms.length === 0) return true;
  const blob = tokenize(searchBlob(record)).join(" ");
  return terms.every((t) => blob.includes(t));
}

export function matchesFacets(record, active) {
  for (const [facet, getValues] of Object.entries(FACETS)) {
    const selected = active[facet] || [];
    if (selected.length === 0) continue; // group inactive
    const has = new Set(getValues(record));
    // OR within group
    if (!selected.some((v) => has.has(v))) return false; // AND between groups
  }
  return true;
}

const RANGE_DAYS = { "30d": 30, "3m": 91, "6m": 182, "1y": 365, all: Infinity };

export function withinRange(record, range, now = new Date()) {
  const days = RANGE_DAYS[range] ?? RANGE_DAYS["6m"];
  if (days === Infinity) return true;
  const d = new Date(record.date + "T00:00:00Z");
  return (now - d) / 86400000 <= days;
}

// A search must reliably cover the entire archive, not just whatever the
// date-range dropdown happens to be set to -- so once a query is active,
// filtering behaves as "all time" regardless of the dropdown's own value
// (the dropdown itself is kept in sync with this by main.js's apply()).
// Guards on tokenize().length, not state.q.trim().length, so a
// punctuation-only query (e.g. "?") -- which matchesSearch treats as no
// query at all -- doesn't spuriously widen the range too.
export function effectiveRange(state) {
  return tokenize(state.q).length > 0 ? "all" : state.range;
}

export function applyAll(records, state, now = new Date()) {
  const range = effectiveRange(state);
  return records.filter(
    (r) => withinRange(r, range, now) && matchesFacets(r, state) && matchesSearch(r, state.q)
  );
}

// Counts for each value of each facet, computed against the OTHER active
// filters (so a facet's own counts don't collapse when you pick one of its
// values) -- standard faceted-search behaviour.
export function facetCounts(records, state, now = new Date()) {
  const out = {};
  for (const facet of Object.keys(FACETS)) {
    const others = { ...state, [facet]: [] };
    const range = effectiveRange(others);
    const pool = records.filter(
      (r) => withinRange(r, range, now) && matchesFacets(r, others) && matchesSearch(r, others.q)
    );
    const counts = {};
    for (const r of pool) for (const v of FACETS[facet](r)) counts[v] = (counts[v] || 0) + 1;
    out[facet] = counts;
  }
  return out;
}
