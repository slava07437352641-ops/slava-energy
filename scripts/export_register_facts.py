#!/usr/bin/env python3
"""Export the register facts shown on the generated project pages into data/register-facts-public.json.

Run this where the inputs live. The builder (scripts/build_seo_geo.py) reads ONLY the exported file, so a
clean clone of the repository rebuilds the site without any of them.

Inputs, all read-only:
  1. data/data_centre_register.json and data/grid_corridor_supplement.json: hand-entered from public reports.
     Only whitelisted fields are exported, plus the https links of the reports.
  2. The REPD release SQLite (DESNZ, Open Government Licence v3.0).
  3. The NESO TEC register CSV and the NESO Embedded Register CSV (NESO Open Data Licence v1.0).
The objects database is never opened: it also holds data derived from OpenStreetMap, from the Searchland
collection and from the owner's own enrichment, and none of that may reach the public file. Every REPD and NESO
value is read from its own primary file, and the file hashes are written to the output so the origin can be
re-checked.

Dates: the register's own release date is not carried by any input, so it is written as "unavailable". The
download date is not recorded either; the file's name date and the date the local copy was created are written as
separate, labelled facts, and the date of this export is written as "Facts exported".

The export refuses to write if any value contains internal wording, a post-ID-sized number, an email address or a
non-https link.

Usage: python3 scripts/export_register_facts.py [--site DIR] [--repd-release PATH] [--tec-csv PATH]
                                                [--embedded-csv PATH] [--out PATH] [--date YYYY-MM-DD]
"""
import argparse, ast, collections, csv, datetime, hashlib, json, os, re, sqlite3, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_seo_geo as sg  # noqa: E402

HOME = os.path.expanduser("~")
REPD_DEFAULT = (HOME + "/Library/CloudStorage/OneDrive-Personal/2026 08 Mac Air/Projects/SpatialData.gov/db/releases/"
                "repd-q2-2026/gen-d73d1cf045d722434c22/repd_q2_2026.sqlite")
TEC_DEFAULT = HOME + "/dev/uk-project-post-map/data/registers/tec-register-2026-10-10.csv"
EMBEDDED_DEFAULT = HOME + "/dev/uk-project-post-map/data/registers/embedded-register-2026-10-10.csv"
UNAVAILABLE = "unavailable"

# Licensed sources: wording copied from the official licence and dataset pages (checked 2026-10-17).
NESO_LICENCE = {
    "licence": "NESO Open Data Licence v1.0",
    "licence_url": "https://www.neso.energy/data-portal/neso-open-licence",
    "attribution": "Supported by National Energy SO Open Data"}
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
        "source_url": "https://www.neso.energy/data-portal/transmission-entry-capacity-tec-register", **NESO_LICENCE},
    "neso_embedded": {
        "name": "Embedded Register, National Energy System Operator",
        "source_url": "https://www.neso.energy/data-portal/embedded-register", **NESO_LICENCE},
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


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def created_date(path):
    """Date the local copy was created (file system birth time), or 'unavailable'."""
    t = getattr(os.stat(path), "st_birthtime", None)
    return datetime.date.fromtimestamp(t).isoformat() if t else UNAVAILABLE


def name_date(path):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path))
    return m.group(1) if m else UNAVAILABLE


def public_entry(dc_row=None, corridor_row=None, repd_rows=(), neso_rows=()):
    """Whitelisted facts for one project. neso_rows: [{'file': 'TEC' or 'Embedded', 'status': ...}] in file order."""
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
    tec = [r for r in neso_rows if r["file"] == "TEC" and r.get("status")]
    emb = [r for r in neso_rows if r["file"] == "Embedded" and r.get("status")]
    if len(repd_rows) > 1:
        facts.append(fact("REPD rows with this name", len(repd_rows), "register", "repd"))
    if len(tec) > 1:
        facts.append(fact("TEC rows with this name", len(tec), "register", "neso_tec"))
    if len(emb) > 1:
        facts.append(fact("Embedded Register rows with this name", len(emb), "register", "neso_embedded"))
    if repd_rows:
        r = repd_rows[0]
        facts += [fact("REPD reference", r["ref"], "register", "repd"), fact("REPD status", r["status"], "register", "repd")]
    if tec:
        facts.append(fact("TEC project status", tec[0]["status"], "register", "neso_tec"))
    elif emb:
        facts.append(fact("Embedded Register project status", emb[0]["status"], "register", "neso_embedded"))
    return {"facts": facts, "sources": [u for u in dict.fromkeys(urls) if str(u).startswith("https://")]}


def read_repd(path):
    """({normalised name: [{'ref', 'status'}]}, source metadata for the credits) from the REPD release SQLite."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = collections.defaultdict(list)
        for ref, name, status in con.execute(
                "select p.ref_id, p.site_name_raw, ds.display_value from repd_projects p "
                "left join development_statuses ds on ds.development_status_id = p.development_status_id order by p.rowid"):
            rows[sg.norm(name)].append({"ref": str(ref), "status": status or ""})
        latest = con.execute("select max(record_last_updated_date) from repd_projects").fetchone()[0]
        src = con.execute("select source_path, snapshot_path, source_sha256 from source_files order by source_file_id limit 1").fetchone()
    finally:
        con.close()
    m = re.search(r"_(Q[1-4])_(\d{4})", src[0] or "")
    snapshot = os.path.join(os.path.dirname(path), src[1] or "")
    copy_made = created_date(snapshot) if os.path.exists(snapshot) else created_date(path)
    dates = [{"label": "Edition", "value": f"{m.group(1)} {m.group(2)}" if m else UNAVAILABLE},
             {"label": "Release date", "value": UNAVAILABLE},
             {"label": "Latest record update in the file", "value": latest if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(latest)) else UNAVAILABLE},
             {"label": "Download date", "value": UNAVAILABLE},
             {"label": "Local copy created", "value": copy_made}]
    files = [{"name": os.path.basename(path), "sha256": sha256_file(path)},
             {"name": os.path.basename(src[0] or ""), "sha256": src[2]}]
    return rows, {"dates": dates, "files": files}


def read_neso(tec_path, embedded_path):
    rows = collections.defaultdict(list)
    meta = {}
    for key, label, path in (("neso_tec", "TEC", tec_path), ("neso_embedded", "Embedded", embedded_path)):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rows[sg.norm(r["Project Name"])].append({"file": label, "status": clean(r.get("Project Status") or "")})
        meta[key] = {"dates": [{"label": "Release date", "value": UNAVAILABLE},
                               {"label": "Download date", "value": UNAVAILABLE},
                               {"label": "File name date", "value": name_date(path)},
                               {"label": "Local copy created", "value": created_date(path)}],
                     "files": [{"name": os.path.basename(path), "sha256": sha256_file(path)}]}
    return rows, meta


def page_projects(site):
    recs = [r for r in sg.read_json(site, "data/discussions-index.json", {"records": []})["records"]
            if r["id"] not in sg.BLOCKED_POST_IDS and r.get("date") and r.get("source")]
    by = collections.Counter(r["project"] for r in recs if r.get("project"))
    return sorted(n for n, c in by.items() if c >= 2)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Export the displayed register facts to data/register-facts-public.json.")
    ap.add_argument("--site", default=sg.SITE_DEFAULT)
    ap.add_argument("--repd-release", default=REPD_DEFAULT)
    ap.add_argument("--tec-csv", default=TEC_DEFAULT)
    ap.add_argument("--embedded-csv", default=EMBEDDED_DEFAULT)
    ap.add_argument("--out", default=None)
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    a = ap.parse_args(argv)
    for rel in ("data/data_centre_register.json", "data/grid_corridor_supplement.json"):
        if not os.path.exists(os.path.join(a.site, rel)):
            sys.exit(f"error: {rel} not found; the export needs the hand-entered register files")
    for label, p in (("REPD release", a.repd_release), ("TEC CSV", a.tec_csv), ("Embedded Register CSV", a.embedded_csv)):
        if not os.path.exists(p):
            sys.exit(f"error: {label} not found at {p}")
    dc = {p["name"]: p for p in sg.read_json(a.site, "data/data_centre_register.json", {"projects": []})["projects"]}
    corr = {c["name"]: c for c in sg.read_json(a.site, "data/grid_corridor_supplement.json", {"corridors": []})["corridors"]}
    repd, repd_meta = read_repd(a.repd_release)
    neso, neso_meta = read_neso(a.tec_csv, a.embedded_csv)
    sources = json.loads(json.dumps(SOURCES))
    for key, meta in (("repd", repd_meta), *neso_meta.items()):
        sources[key]["dates"] = meta["dates"] + [{"label": "Facts exported", "value": a.date}]
        sources[key]["files"] = meta["files"]
    projects = {}
    for name in page_projects(a.site):
        n = sg.norm(name)
        projects[name] = public_entry(dc.get(name), corr.get(name), repd.get(n, []), neso.get(n, []))
    doc = {"schema": 1, "generated": a.date,
           "purpose": "Register facts displayed on the generated project pages. Written by scripts/export_register_facts.py; "
                      "holds only the displayed facts, their public source links and the source dates and file hashes.",
           "sources": sources,
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
