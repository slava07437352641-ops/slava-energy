#!/usr/bin/env node
// Regression check for the "Discussion shared in <X>, <date>" fallback title
// format: <X> must always equal the record's own source.name. Catches the
// class of bug fixed on 2026-09-26, where 235 records had a hardcoded
// "Scotland Against Spin" regardless of which group they actually came from.
//
// Usage: node scripts/check-title-source-agreement.mjs
// Exit code 0 = all agree, 1 = mismatches found (printed to stderr).

import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA_PATH = path.join(HERE, "../data/discussions-index.json");

const TITLE_PATTERN = /^Discussion shared in (.+?), \d+ \w+ \d{4}$/;

const raw = await readFile(DATA_PATH, "utf-8");
const { records } = JSON.parse(raw);

const mismatches = [];
for (const r of records) {
  const m = TITLE_PATTERN.exec(r.title);
  if (!m) continue;
  const namedInTitle = m[1];
  const actual = r.source?.name;
  if (namedInTitle !== actual) {
    mismatches.push({ id: r.id, title: r.title, "source.name": actual });
  }
}

if (mismatches.length > 0) {
  console.error(`FAIL: ${mismatches.length} record(s) have a fallback title that disagrees with source.name`);
  for (const m of mismatches.slice(0, 20)) {
    console.error(`  ${m.id}: title says "${m.title}" but source.name is "${m["source.name"]}"`);
  }
  if (mismatches.length > 20) console.error(`  ...and ${mismatches.length - 20} more`);
  process.exit(1);
}

console.log(`OK: all ${records.length} records' fallback titles (where present) agree with source.name`);
process.exit(0);
