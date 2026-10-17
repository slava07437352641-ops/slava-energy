#!/usr/bin/env python3
"""Export the register facts shown on the generated project pages into data/register-facts-public.json.

Run this where the private inputs live (the data-centre register, the grid corridor supplement and the
REPD/TEC database). The builder (scripts/build_seo_geo.py) reads ONLY the exported file, so a clean clone
of the repository rebuilds the site without any of those inputs.

Only facts the pages display are written: a fixed list of labelled fields per project, the https source
links of reported facts, and the credit text of the licensed registers. Aliases, internal notes, post IDs,
group lists, unconfirmed source links and the rest of the database are never read into the output. The
export refuses to write if any value contains internal wording, a post-ID-sized number, an email address
or a non-https link.

Usage: python3 scripts/export_register_facts.py [--site DIR] [--objects-db PATH] [--out PATH] [--date YYYY-MM-DD]
"""
import argparse, ast, collections, datetime, json, os, re, sqlite3, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_seo_geo as sg  # noqa: E402

OBJECTS_DEFAULT = os.path.expanduser("~/dev/uk-project-post-map_v3.3/data/objects/objects.sqlite")

# Licensed sources: wording copied from the official licence pages (checked 2026-10-17).
SOURCES = {
    "repd": {
        "name": "Renewable Energy Planning Database (REPD), Department for Energy Security and Net Zero",
        "licence": "Open Government Licence v3.0",
        "licence_url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
        "attribution": "Contains public sector information licensed under the Open Government Licence v3.0.",
        "source_url": "https://www.gov.uk/government/publications/renewable-energy-planning-database-monthly-extract",
        "copyright": "Crown copyright"},
    "neso_tec": {
        "name": "Transmission Entry Capacity (TEC) register, National Energy System Operator",
        "licence": "NESO Open Data Licence v1.0",
        "licence_url": "https://www.neso.energy/data-portal/neso-open-licence",
        "attribution": "Supported by National Energy SO Open Data",
        "source_url": "https://www.neso.energy/data-portal/transmission-entry-capacity-tec-register"},
    "reported": {
        "name": "Press, developer and council reports",
        "note": "Reported facts link to their public sources on each page and are not independently verified."},
}


def as_list(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip().startswith("["):
        try:
            return list(ast.literal_eval(v))
        except (ValueError, SyntaxError):
            return []
    return []


def clean(v):
    return re.sub(r"\s+", " ", str(v)).strip()


def fact(label, value, basis, source):
    return {"label": label, "value": clean(value), "basis": basis, "source": source}


def public_entry(dc_row=None, corridor_row=None, repd_rows=(), tec_rows=()):
    """Whitelisted facts for one project. Field order matches the labels the pages have always shown."""
    facts, urls = [], []
    if dc_row:
        for lab, key in [("Planning reference", "application_ref"), ("Application type", "application_type"),
                         ("Status", "status_reported"), ("Developer", "developer_reported"),
                         ("Council", "council"), ("Capacity", "capacity_reported")]:
            if dc_row.get(key):
                facts.append(fact(lab, dc_row[key], "reported", "reported"))
        urls += as_list(dc_row.get("sources"))
    if corridor_row:
        for lab, key in [("Consent or stage", "consent"), ("Operator", "operator"), ("Kind", "kind")]:
            if corridor_row.get(key):
                facts.append(fact(lab, corridor_row[key], "reported", "reported"))
        if corridor_row.get("source"):
            urls.append(corridor_row["source"])
    # "Planning reference (TEC)" is deliberately not exported: it may come from project enrichment, not the NESO register
    if len(repd_rows) > 1:
        facts.append(fact("REPD rows with this name", len(repd_rows), "register", "repd"))
    if len(tec_rows) > 1:
        facts.append(fact("TEC rows with this name", len(tec_rows), "register", "neso_tec"))
    if repd_rows:
        r = repd_rows[0]
        facts += [fact("REPD reference", r["ref"], "register", "repd"), fact("REPD status", r["status"], "register", "repd")]
    if tec_rows and tec_rows[0].get("status"):
        facts.append(fact("TEC project status", tec_rows[0]["status"], "register", "neso_tec"))
    return {"facts": facts, "sources": [u for u in dict.fromkeys(urls) if str(u).startswith("https://")]}


def load_registers(path):
    repd, tec = collections.defaultdict(list), collections.defaultdict(list)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    for ref, name, status in con.execute("select ref_id, name, status from repd_record"):
        repd[sg.norm(name)].append({"ref": ref, "status": status})
    for name, status in con.execute("select project_name, project_status from tec_project"):
        tec[sg.norm(name)].append({"status": status})
    return repd, tec


def page_projects(site):
    recs = [r for r in sg.read_json(site, "data/discussions-index.json", {"records": []})["records"]
            if r["id"] not in sg.BLOCKED_POST_IDS and r.get("date") and r.get("source")]
    by = collections.Counter(r["project"] for r in recs if r.get("project"))
    return sorted(n for n, c in by.items() if c >= 2)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Export the displayed register facts to data/register-facts-public.json.")
    ap.add_argument("--site", default=sg.SITE_DEFAULT)
    ap.add_argument("--objects-db", default=os.environ.get("SEO_OBJECTS_DB", OBJECTS_DEFAULT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    a = ap.parse_args(argv)
    for rel in ("data/data_centre_register.json", "data/grid_corridor_supplement.json"):
        if not os.path.exists(os.path.join(a.site, rel)):
            sys.exit(f"error: {rel} not found; the export needs the private register files")
    if not os.path.exists(a.objects_db):
        sys.exit(f"error: REPD/TEC database not found at {a.objects_db}")
    dc = {p["name"]: p for p in sg.read_json(a.site, "data/data_centre_register.json", {"projects": []})["projects"]}
    corr = {c["name"]: c for c in sg.read_json(a.site, "data/grid_corridor_supplement.json", {"corridors": []})["corridors"]}
    repd, tec = load_registers(a.objects_db)
    projects = {}
    for name in page_projects(a.site):
        n = sg.norm(name)
        projects[name] = public_entry(dc.get(name), corr.get(name), repd.get(n, []), tec.get(n, []))
    doc = {"schema": 1, "generated": a.date,
           "purpose": "Register facts displayed on the generated project pages. Written by scripts/export_register_facts.py; "
                      "holds only the displayed facts and their public source links.",
           "sources": SOURCES,
           "data_centre_projects": sorted(dc),
           "projects": projects}
    try:
        sg.validate_facts_doc(doc)
    except sg.BuildError as e:
        sys.exit(f"error: refusing to write: {e}")
    out = a.out or os.path.join(a.site, sg.FACTS_REL)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    with_facts = sum(1 for p in projects.values() if p["facts"])
    print(f"wrote {out}: {len(projects)} projects ({with_facts} with facts), "
          f"{sum(len(p['facts']) for p in projects.values())} facts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
