"""Build data/source-registry.json: one row per source with the Option A audit gate.

A source may feed a Community Intelligence Brief only when it is
public (checked in reports/source-audit-*.json), active (a record dated within
14 days of the build date) and mapped (at least one record carries a project).
The live site feed is not filtered by this file; it gates briefs only.
"""
import ast, datetime, json, os, sys

def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(obj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISC = os.path.join(ROOT, "data", "discussions-index.json")
AUDIT = os.path.join(ROOT, "reports", "source-audit-2026-10-16.json")
OUT = os.path.join(ROOT, "data", "source-registry.json")
BUILD_DATE = datetime.date(2026, 10, 16)
ACTIVE_DAYS = 14
TIER_B = {"WisWIN"}


def source_name(rec):
    s = rec.get("source")
    if isinstance(s, dict):
        return s.get("name") or "", s
    try:
        d = ast.literal_eval(s)
        return d.get("name") or "", d
    except Exception:
        return str(s), {}


def has_project(rec):
    p = rec.get("project")
    return bool(p) and str(p) not in ("None", "{}", "[]")


def build(disc_path=DISC, audit_path=AUDIT):
    recs = _read_json(disc_path)["records"]
    audit_rows = {}
    if os.path.exists(audit_path):
        for row in _read_json(audit_path)["rows"]:
            audit_rows[row["group"]] = row
    by = {}
    for r in recs:
        name, meta = source_name(r)
        e = by.setdefault(name, {"name": name, "label": meta.get("label") or name,
                                  "url": meta.get("url") or "", "records": 0, "project_linked": 0,
                                  "last_date": ""})
        e["records"] += 1
        e["project_linked"] += has_project(r)
        e["last_date"] = max(e["last_date"], r.get("date") or "")
    out = []
    for name in sorted(by):
        e = by[name]
        last = datetime.date.fromisoformat(e["last_date"]) if e["last_date"] else None
        active = bool(last) and (BUILD_DATE - last).days <= ACTIVE_DAYS
        public = name in audit_rows  # all audited groups were checked public on 16 Oct
        mapped = e["project_linked"] > 0
        out.append({
            "name": name, "label": e["label"], "url": e["url"],
            "tier": "B" if name in TIER_B else "A",
            "site_records": e["records"], "project_linked_records": e["project_linked"],
            "last_post_date": e["last_date"],
            "audit": {"public": public, "active": active, "mapped": mapped},
            "brief_eligible": public and active and mapped,
        })
    return out


if __name__ == "__main__":
    rows = build()
    json.dump({"build_date": BUILD_DATE.isoformat(), "active_window_days": ACTIVE_DAYS,
               "gate": "brief_eligible = public AND active AND mapped (Option A)",
               "sources": rows}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("sources", len(rows), "brief_eligible", [r["name"] for r in rows if r["brief_eligible"]])
    sys.exit(0)
