#!/usr/bin/env python3
"""Export the register facts shown on the generated project pages into data/register-facts-public.json.

Run this where the inputs live. The builder (scripts/build_seo_geo.py) reads ONLY the exported file, so a
clean clone of the repository rebuilds the site without any of them.

Inputs, all read-only:
  1. data/data_centre_register.json and data/grid_corridor_supplement.json: hand-entered from public reports.
     Only whitelisted fields are exported, plus the https links of the reports.
  2. The REPD release SQLite (DESNZ, Open Government Licence v3.0).
  3. The NESO TEC register CSV and the NESO Embedded Register CSV (NESO Open Data Licence v1.0).
  4. data/register-mapping.json: the explicit identifier mapping reviewed by the maintainer. A project with several
     same-name records in one register must be mapped; every record is read by its own identifier and listed
     separately, never combined, and each stated relationship is checked against the primary files.
The objects database is never opened: it also holds data derived from OpenStreetMap, from the Searchland
collection and from the owner's own enrichment, and none of that may reach the public file. Every REPD and NESO
value is read from its own primary file, and the file hashes are written to the output so the origin can be
re-checked.

Dates: no input carries the register's release date or the date the file was downloaded. Both are recorded, with
their evidence, in data/source-dates.json against the SHA-256 of the exact file they describe; the export uses them
only when the file's hash matches. For a file with no matching entry the two dates are written as "unavailable" and
the file's name date and the date the local copy was created are written as separate, labelled facts instead. The
date of this export is written as "Facts exported".

The export refuses to write if any value contains internal wording, a post-ID-sized number, an email address or a
non-https link.

Usage: python3 scripts/export_register_facts.py [--site DIR] --repd-release PATH --tec-csv PATH
                                                --embedded-csv PATH [--out PATH] [--date YYYY-MM-DD]
       (the three input options may instead be set as SEO_REPD_RELEASE, SEO_TEC_CSV and SEO_EMBEDDED_CSV)
"""
import argparse, ast, collections, csv, datetime, hashlib, json, os, re, sqlite3, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_seo_geo as sg  # noqa: E402

# No machine-specific paths are kept in the repository: give the three inputs as options or as these variables.
ENV_REPD, ENV_TEC, ENV_EMBEDDED = "SEO_REPD_RELEASE", "SEO_TEC_CSV", "SEO_EMBEDDED_CSV"
UNAVAILABLE = "unavailable"
MAPPING_REL = "data/register-mapping.json"
DATES_REL = "data/source-dates.json"
CORPORATE = re.compile(r"\b(limited|ltd|plc|llp|lp)\b", re.I)


class ExportError(Exception):
    """Inputs that cannot be exported safely; the export stops and writes nothing."""

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
    "companies_house": {
        "name": "Companies House, the UK register of companies",
        "source_url": "https://find-and-update.company-information.service.gov.uk/",
        "credit": "Company facts: Companies House public register",
        "terms_url": "https://www.gov.uk/government/publications/companies-house-accreditation-to-information-fair-traders-scheme/public-task-copyright-and-crown-copyright",
        "terms_note": "Companies House states that it imposes no rules or requirements on how the information on the public register is used (page updated 9 August 2019)",
        "checked": "2026-10-17"},
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


def iso_date(d):
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", (d or "").strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def company_facts(c):
    """Company-level facts from a hand-entered Companies House record. Only corporate controllers are ever exported."""
    if not c:
        return [], []
    missing = [k for k in ("name", "number", "status", "incorporated", "url", "checked") if not c.get(k)]
    if missing:
        raise ExportError(f"company record is missing {', '.join(missing)}")
    bad = [x for x in c.get("controllers") or [] if not CORPORATE.search(x)]
    if bad:
        raise ExportError("a controller does not look like a company name; individual names are never exported")
    facts = [fact("Company", f"{c['name']} (company number {c['number']}); {c['status']}; incorporated {c['incorporated']}",
                  "register", "companies_house")]
    if c.get("controllers"):
        facts.append(fact("Persons with significant control (corporate)", "; ".join(c["controllers"]), "register", "companies_house"))
    return facts, [c["url"]]


def public_entry(dc_row=None, corridor_row=None, repd_rows=(), neso_rows=(), mapped=None):
    """Whitelisted facts for one project. neso_rows: [{'file': 'TEC' or 'Embedded', 'status': ...}] in file order.
    mapped: {'records': [...], 'label': ...} for a project that lists its register records one by one."""
    facts, urls = [], []
    if dc_row:
        for lab, key in [("Planning reference", "application_ref"), ("Application type", "application_type"),
                         ("Status", "status_reported"), ("Developer", "developer_reported"),
                         ("Council", "council"), ("Capacity", "capacity_reported")]:
            if dc_row.get(key):
                inferred = lab == "Council" and dc_row.get("council_inferred")
                shown = "Council (inferred)" if inferred else lab
                basis = "inferred" if inferred else ("unverified" if str(dc_row[key]).lower().startswith("unverified") else "reported")
                facts.append(fact(shown, dc_row[key], basis, "reported"))
            if lab == "Developer":
                cf, cu = company_facts(dc_row.get("company"))
                facts += cf
                urls += cu
        urls += as_list(dc_row.get("sources"))
    if corridor_row:
        for lab, key in [("Consent or stage", "consent"), ("Operator", "operator"), ("Kind", "kind")]:
            if corridor_row.get(key):
                facts.append(fact(lab, corridor_row[key], "reported", "reported"))
        if corridor_row.get("source"):
            urls.append(corridor_row["source"])
    entry = {}
    if mapped is None:
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
    else:
        entry["records"] = mapped["records"]
        if mapped.get("label"):
            entry["label"] = mapped["label"]
        if mapped.get("note"):
            entry["note"] = clean(mapped["note"])
    return {"facts": facts, "sources": [u for u in dict.fromkeys(urls) if str(u).startswith("https://")], **entry}


def read_repd(path):
    """(rows by normalised name, records by REPD ref, set of linked ref pairs, source metadata) from the REPD release SQLite."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows, recs = collections.defaultdict(list), {}
        for ref, name, status, mw, upd in con.execute(
                "select p.ref_id, p.site_name_raw, ds.display_value, p.installed_capacity_mwelec, p.record_last_updated_date "
                "from repd_projects p left join development_statuses ds on ds.development_status_id = p.development_status_id order by p.rowid"):
            ref = str(ref)
            rows[sg.norm(name)].append({"ref": ref, "status": status or ""})
            recs[ref] = {"name": clean(name), "status": status or "", "mw": mw, "updated": upd, "events": {}}
        for ref, etype, edate in con.execute("select ref_id, event_type, event_date from project_status_events "
                                             "where event_date is not null order by event_date"):
            if str(ref) in recs:
                recs[str(ref)]["events"][clean(etype)] = edate
        links = {frozenset({str(a), str(b)}) for a, b in con.execute("select source_ref_id, target_ref_id from project_reference_links")}
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
    return rows, recs, links, {"dates": dates, "files": files, "data_sha256": src[2]}


def read_neso(tec_path, embedded_path):
    """(rows by normalised name, records by (register, project number), source metadata per register)."""
    rows, recs, meta = collections.defaultdict(list), {}, {}
    for key, label, path in (("neso_tec", "TEC", tec_path), ("neso_embedded", "Embedded", embedded_path)):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                number = clean(r.get("Project Number") or "")
                row = {"file": label, "register": key, "number": number, "status": clean(r.get("Project Status") or "")}
                rows[sg.norm(r["Project Name"])].append(row)
                if number in {n for (k, n) in recs if k == key}:
                    raise ExportError(f"{os.path.basename(path)}: project number {number} appears twice")
                recs[(key, number)] = {"name": clean(r["Project Name"]), "status": row["status"], "stage": clean(r.get("Stage") or ""),
                                       "conn": clean(r.get("MW Connected") or ""), "cum": clean(r.get("Cumulative Total Capacity (MW)") or ""),
                                       "eff": iso_date(r.get("MW Effective From"))}
        meta[key] = {"dates": [{"label": "Release date", "value": UNAVAILABLE},
                               {"label": "Download date", "value": UNAVAILABLE},
                               {"label": "File name date", "value": name_date(path)},
                               {"label": "Local copy created", "value": created_date(path)}],
                     "files": [{"name": os.path.basename(path), "sha256": sha256_file(path)}]}
        meta[key]["data_sha256"] = meta[key]["files"][0]["sha256"]
    return rows, recs, meta


def apply_recorded_dates(recorded, key, meta):
    """Fill 'Release date' and 'Download date' from data/source-dates.json when its entry describes exactly this file.

    Raises ExportError for an entry that is malformed. An entry for a different file (or none) leaves both dates
    'unavailable', keeps the name-date and local-copy facts, and prints a warning."""
    entry = (recorded.get("sources") or {}).get(key)
    sha = meta["data_sha256"]
    if not entry or entry.get("sha256") != sha:
        print(f"warning: {DATES_REL} has no entry for the {key} file with SHA-256 {sha[:12]}...; "
              "its release and download dates stay 'unavailable'", file=sys.stderr)
        return
    problems = [f"{DATES_REL} {key}: {k} is not an ISO date" for k in ("release_date", "download_date") if not sg.iso_date_ok(entry.get(k))]
    for k in ("release_evidence", "download_evidence"):
        text = entry.get(k)
        if not isinstance(text, str) or not text.strip():
            problems.append(f"{DATES_REL} {key}: {k} is missing")
        else:
            problems += [f"{DATES_REL} {key}: {k} has {why}" for pat, why in sg.FORBIDDEN if pat.search(text)]
    if problems:
        raise ExportError("; ".join(problems))
    values = {"Release date": entry["release_date"], "Download date": entry["download_date"]}
    meta["dates"] = [{"label": d["label"], "value": values.get(d["label"], d["value"])} for d in meta["dates"]
                     if d["label"] not in ("File name date", "Local copy created")]


def build_records(project, mapped, repd_recs, repd_links, neso_recs):
    """Read every mapped record from its primary file and check the stated basis. Raises ExportError on any mismatch."""
    entries = mapped["records"]
    ids = {(m["register"], str(m["id"])) for m in entries}
    out, problems = [], []
    for m in entries:
        reg, rid, basis = m["register"], str(m["id"]), m.get("basis")
        where = f"{project}: {reg} {rid}"
        if basis not in sg.RECORD_BASES:
            problems.append(f"{where}: unknown basis {basis!r}")
            continue
        if reg == "repd":
            r = repd_recs.get(rid)
            if not r:
                problems.append(f"{where}: not found in the REPD release")
                continue
            capacity = f"{r['mw']:g} MW" if r["mw"] is not None else "not recorded"
            ev = r["events"].get(r["status"])
            date = f"record updated {r['updated'] or 'date not recorded'}" + (f"; status event {ev}" if ev else "")
        elif reg in ("neso_tec", "neso_embedded"):
            r = neso_recs.get((reg, rid))
            if not r:
                problems.append(f"{where}: not found in the NESO file")
                continue
            capacity = f"connected {r['conn'] or '?'} MW; cumulative {r['cum'] or '?'} MW"
            date = f"MW effective from {r['eff']}" if r["eff"] else "no effective date in the file"
        else:
            problems.append(f"{where}: unknown register")
            continue
        if basis == "name_exact" and sg.norm(r["name"]) != sg.norm(project):
            problems.append(f"{where}: basis name_exact but the recorded name is {r['name']!r}")
        if basis == "register_link":
            other = str(m.get("with") or "")
            if ("repd", other) not in ids or frozenset({rid, other}) not in repd_links:
                problems.append(f"{where}: no REPD link to {other!r} among the mapped records")
        if basis == "neso_project_number" and re.sub(r"-\d+$", "", rid) != str(m.get("group")):
            problems.append(f"{where}: project number does not belong to group {m.get('group')!r}")
        out.append({"register": reg, "id": rid, "name": r["name"], "status": r["status"], "capacity": capacity,
                    "date": date, "relation": clean(m["relation"]), "basis": basis})
    if problems:
        raise ExportError("; ".join(problems))
    return out


def mapping_problem(name, exact, mapped):
    """Why a project cannot be exported, or None. exact: {(register, id)} of the records whose name equals the project name."""
    per_register = collections.Counter(reg for reg, _ in exact)
    if any(c > 1 for c in per_register.values()) and not mapped:
        return (f"{name}: {sum(per_register.values())} same-name records in {', '.join(sorted(per_register))} "
                f"and no entry in {MAPPING_REL}")
    if mapped:
        omitted = exact - {(x["register"], str(x["id"])) for x in mapped["records"]}
        if omitted:
            return f"{name}: the mapping omits exact-name record(s) {sorted(omitted)}"
    return None


def page_projects(site):
    recs = [r for r in sg.read_json(site, "data/discussions-index.json", {"records": []})["records"]
            if r["id"] not in sg.BLOCKED_POST_IDS and r.get("date") and r.get("source")]
    by = collections.Counter(r["project"] for r in recs if r.get("project"))
    return sorted(n for n, c in by.items() if c >= 2)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Export the displayed register facts to data/register-facts-public.json.")
    ap.add_argument("--site", default=sg.SITE_DEFAULT)
    ap.add_argument("--repd-release", default=os.environ.get(ENV_REPD))
    ap.add_argument("--tec-csv", default=os.environ.get(ENV_TEC))
    ap.add_argument("--embedded-csv", default=os.environ.get(ENV_EMBEDDED))
    ap.add_argument("--out", default=None)
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    a = ap.parse_args(argv)
    for rel in ("data/data_centre_register.json", "data/grid_corridor_supplement.json"):
        if not os.path.exists(os.path.join(a.site, rel)):
            sys.exit(f"error: {rel} not found; the export needs the hand-entered register files")
    for label, p, opt, env in (("REPD release", a.repd_release, "--repd-release", ENV_REPD),
                               ("TEC CSV", a.tec_csv, "--tec-csv", ENV_TEC),
                               ("Embedded Register CSV", a.embedded_csv, "--embedded-csv", ENV_EMBEDDED)):
        if not p:
            sys.exit(f"error: no {label} given; use {opt} or set {env}")
        if not os.path.exists(p):
            sys.exit(f"error: {label} not found at {p}")
    mapping = sg.read_json(a.site, MAPPING_REL, {"schema": 1, "projects": {}})
    if mapping.get("schema") != 1:
        sys.exit(f"error: {MAPPING_REL} has an unsupported schema")
    dc = {p["name"]: p for p in sg.read_json(a.site, "data/data_centre_register.json", {"projects": []})["projects"]}
    corr = {c["name"]: c for c in sg.read_json(a.site, "data/grid_corridor_supplement.json", {"corridors": []})["corridors"]}
    try:
        repd, repd_recs, repd_links, repd_meta = read_repd(a.repd_release)
        neso, neso_recs, neso_meta = read_neso(a.tec_csv, a.embedded_csv)
        sources = json.loads(json.dumps(SOURCES))
        recorded = sg.read_json(a.site, DATES_REL, {"schema": 1, "sources": {}})
        if recorded.get("schema") != 1:
            raise ExportError(f"{DATES_REL} has an unsupported schema")
        for key, meta in (("repd", repd_meta), *neso_meta.items()):
            apply_recorded_dates(recorded, key, meta)
            sources[key]["dates"] = meta["dates"] + [{"label": "Facts exported", "value": a.date}]
            sources[key]["files"] = meta["files"]
        projects, problems = {}, []
        for name in page_projects(a.site):
            n = sg.norm(name)
            exact = {("repd", r["ref"]) for r in repd.get(n, [])} | {(r["register"], r["number"]) for r in neso.get(n, [])}
            m = (mapping.get("projects") or {}).get(name)
            why = mapping_problem(name, exact, m)
            if why:
                problems.append(why)
                continue
            if m:
                mapped = {"records": build_records(name, m, repd_recs, repd_links, neso_recs), "label": m.get("label"), "note": m.get("note")}
                projects[name] = public_entry(dc.get(name), corr.get(name), mapped=mapped)
            else:
                projects[name] = public_entry(dc.get(name), corr.get(name), repd.get(n, []), neso.get(n, []))
        if problems:
            raise ExportError("; ".join(problems))
    except ExportError as e:
        sys.exit(f"error: {e}")
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
    with_facts = sum(1 for p in projects.values() if p["facts"] or p.get("records"))
    print(f"wrote {out}: {len(projects)} projects ({with_facts} with facts or records), "
          f"{sum(len(p['facts']) for p in projects.values())} facts, {sum(len(p.get('records', [])) for p in projects.values())} register records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
