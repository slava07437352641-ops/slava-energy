// Reviewed project names, derived only from records whose project field was
// already verified during enrichment (provenance.project.confidence ===
// "corroborated" / "corroborated_council" -- see data/discussions-index.json).
// This file never infers a project for a record; it only normalises spelling
// variants of names that were already confirmed, so the project filter and
// search treat "Giant's Burn Wind Farm" / "Giants Burn Wind Farm" as one
// project instead of two.

export const KNOWN_PROJECTS = [
  { canonical: "Berwick Bank Offshore Wind Farm", aliases: ["Berwick Bank"] },
  { canonical: "Carn Fearna Wind Farm", aliases: ["Carn Fearna"] },
  { canonical: "Chirmorie Wind Farm", aliases: ["Chirmorie"] },
  { canonical: "Dun Law Wind Farm", aliases: ["Dun Law"] },
  {
    canonical: "Giant's Burn Wind Farm",
    aliases: ["Giants Burn Wind Farm", "Giant's Burn", "Giants Burn"],
  },
  { canonical: "Shinness Wind Farm", aliases: ["Shinness"] },
  { canonical: "Spiorad na Mara", aliases: [] },
];

// Maps any stored spelling variant (including the canonical form itself) to
// the canonical name, so a record's raw r.project can be normalised in one
// lookup: CANONICAL_BY_RAW[r.project] ?? r.project.
export const CANONICAL_BY_RAW = Object.fromEntries(
  KNOWN_PROJECTS.flatMap((p) => [[p.canonical, p.canonical], ...p.aliases.map((a) => [a, p.canonical])])
);

// Extra search terms to append for a record with a known project, so a query
// for an alias ("berwick bank") matches even if the record's stored project
// string is the full canonical form, and vice versa.
export function projectSearchTerms(rawProject) {
  if (!rawProject) return [];
  const canonical = CANONICAL_BY_RAW[rawProject];
  if (!canonical) return [rawProject];
  const entry = KNOWN_PROJECTS.find((p) => p.canonical === canonical);
  return [canonical, ...(entry?.aliases || [])];
}
