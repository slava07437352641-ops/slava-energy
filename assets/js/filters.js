// Faceted filtering + full-text search (spec §5-§7).
// Rule: OR within a filter group, AND between different groups.
// Extensible: add a facet by adding one entry to FACETS.

import { CANONICAL_BY_RAW, projectSearchTerms } from "./project-aliases.js";

// Kept in sync BY HAND with build-discussions/derive/classify-technology.mjs's
// own TECH_CATEGORIES -- this frontend copy drives only the chip list (see
// main.js's buildTechChips()); the actual filter/count logic below matches
// generically against record.categories and needs no changes when a
// category is added. A real bug (found live-verifying U4's "Data Centre"
// addition): the build-time list was updated but this one wasn't, so
// posts were correctly tagged but had no chip to filter them by.
export const TECH_CATEGORIES = ["Onshore Wind", "BESS", "OHL (Pylons)", "Substation", "Solar", "Hybrid", "Data Centre"];

// Each facet: how to get the set of values a record has for that facet.
// project's values are normalised through CANONICAL_BY_RAW so spelling
// variants of an already-reviewed project (e.g. "Giants Burn Wind Farm" vs
// "Giant's Burn Wind Farm") count as the same filter option.
export const FACETS = {
  tech: (r) => r.categories || [],
  topic: (r) => r.topics || [],
  council: (r) => (r.council ? [r.council] : []),
  project: (r) => (r.project ? [CANONICAL_BY_RAW[r.project] || r.project] : []),
};

function tokenize(s) {
  return (s || "")
    .toLowerCase()
    .normalize("NFKC")
    .replace(/['’]/g, "") // drop apostrophes first so "Giant's" and "Giants" tokenize the same
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
}

// Build a searchable text blob from the PUBLIC indexed fields only.
// Includes bodyText (the captured post text) and, for records with a
// reviewed project match, that project's known aliases -- so a search for
// "berwick bank" also matches a record whose project field is stored as the
// full canonical "Berwick Bank Offshore Wind Farm". This never infers a
// project for a record that doesn't already have one; it only widens the
// terms that match an existing, already-verified project value.
export function searchBlob(r) {
  return [
    r.title,
    r.summary,
    r.bodyText,
    r.location,
    r.developer,
    r.council,
    r.authority,
    r.externalSource,
    ...(r.topics || []),
    ...(r.categories || []),
    ...projectSearchTerms(r.project),
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

export function applyAll(records, state, now = new Date()) {
  return records.filter(
    (r) => withinRange(r, state.range, now) && matchesFacets(r, state) && matchesSearch(r, state.q)
  );
}

// Counts for each value of each facet, computed against the OTHER active
// filters (so a facet's own counts don't collapse when you pick one of its
// values) -- standard faceted-search behaviour.
export function facetCounts(records, state, now = new Date()) {
  const out = {};
  for (const facet of Object.keys(FACETS)) {
    const others = { ...state, [facet]: [] };
    const pool = records.filter(
      (r) => withinRange(r, others.range, now) && matchesFacets(r, others) && matchesSearch(r, others.q)
    );
    const counts = {};
    for (const r of pool) for (const v of FACETS[facet](r)) counts[v] = (counts[v] || 0) + 1;
    out[facet] = counts;
  }
  return out;
}
