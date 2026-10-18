"""Tests for scripts/build_seo_geo.py on the real site data. Builds in memory and writes nothing.
Run: python3 -m pytest -q tests/test_build_seo_geo.py"""
import html as htmllib, json, os, re, sys, xml.etree.ElementTree as ET
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import build_seo_geo as sg  # noqa: E402
import export_register_facts as ex  # noqa: E402
import shutil  # noqa: E402

_CACHE = {}
# Later than every date recorded in data/page-dates.json, so only changed content takes this date.
BUILD_DATE = "2026-10-20"


def built():
    if "v" not in _CACHE:
        _CACHE["v"] = sg.build_files(ROOT, BUILD_DATE)
    return _CACHE["v"]


def norm_text(s):
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip().lower()


def test_no_blocked_ids_in_any_output():
    F, _ = built()
    blob = "\n".join(F.values())
    for pid in sg.BLOCKED_POST_IDS:
        assert pid not in blob, pid


def test_no_post_text_in_any_output():
    F, _ = built()
    blob = norm_text("\n".join(F.values()))
    idx = json.load(open(os.path.join(ROOT, "data", "discussions-index.json"), encoding="utf-8"))
    checked = 0
    for r in idx["records"]:
        body = norm_text(r.get("bodyText") or "")
        if len(body) < 40 or r["id"] in sg.BLOCKED_POST_IDS:
            continue
        checked += 1
        assert body[:40] not in blob, f"post text leaked from record {r['id']}"
    assert checked > 2000  # records with a 40+ character body; the check must run over the archive


def test_robots_allows_bots_and_disallows_briefs():
    F, _ = built()
    txt = F["robots.txt"]
    for bot in sg.BOTS:
        assert f"User-agent: {bot}\nAllow: /\nDisallow: /briefs/" in txt, bot
    assert "Sitemap: https://slava.it.com/sitemap.xml" in txt


def test_sitemap_is_valid_xml_with_lastmod_dates():
    F, stats = built()
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = ET.fromstring(F["sitemap.xml"]).findall("s:url", ns)
    assert len(urls) == 1 + len(sg.HUBS) + stats["project_pages"]
    for u in urls:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", u.find("s:lastmod", ns).text)
    assert urls[0].find("s:loc", ns).text == "https://slava.it.com/"
    assert urls[0].find("s:lastmod", ns).text >= stats["newest"]  # the home page changes when a newer post arrives, never before


def test_capsules_are_40_to_60_words():
    _, stats = built()
    assert stats["capsule_words"]
    for slug, n in stats["capsule_words"].items():
        assert 40 <= n <= 60, (slug, n)


def test_every_jsonld_block_parses_and_has_a_type():
    F, stats = built()
    count = 0
    for path, text in F.items():
        if not path.endswith(".html"):
            continue
        for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, flags=re.S):
            obj = json.loads(block.replace("<\\/", "</"))
            assert obj["@type"] in ("WebSite", "Dataset", "FAQPage"), path
            count += 1
    pages = stats["project_pages"] + len(sg.HUBS)
    assert count == 2 * pages + 2  # Dataset + FAQPage per project and hub page; WebSite + Dataset on the index


class _Balance(HTMLParser):
    TRACK = {"html", "head", "body", "main", "nav", "footer", "aside", "table", "tr", "ul", "li", "p",
             "h1", "h2", "a", "th", "td"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.TRACK:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.TRACK:
            if self.stack and self.stack[-1] == tag:
                self.stack.pop()
            else:
                self.errors.append((tag, self.stack[-3:]))


def test_html_tags_are_balanced_and_pages_have_metadata():
    F, _ = built()
    for path, text in F.items():
        if not path.endswith(".html") or path == "index.html":
            continue
        p = _Balance()
        p.feed(text)
        p.close()
        assert not p.errors, (path, p.errors[:3])
        assert not p.stack, (path, p.stack)
        assert "<title>" in text and 'rel="canonical"' in text and 'name="description"' in text, path


def test_llms_txt_follows_the_spec_shape():
    F, stats = built()
    txt = F["llms.txt"]
    assert txt.startswith("# slava.it.com\n")
    assert "\n> " in txt
    for section in ("## Hubs", "## Projects", "## Feeds"):
        assert f"\n{section}\n" in txt, section
    assert txt.count("](https://slava.it.com/projects/") == stats["project_pages"]


def test_feeds_are_valid_and_capped():
    F, _ = built()
    for path in ["feed.xml", "feeds/data-centres.xml", "feeds/pylons.xml", "feeds/wind.xml"]:
        items = ET.fromstring(F[path]).findall("./channel/item")
        assert 1 <= len(items) <= sg.FEED_ITEMS, path
        for it in items:
            assert it.find("link").text.startswith("https://slava.it.com/?sel=")


def test_index_markers_are_single_and_in_place():
    F, _ = built()
    idx = F["index.html"]
    assert idx.count(sg.JSONLD_MARK[0]) == 1 and idx.count(sg.FOLLOW_MARK[0]) == 1
    assert idx.index(sg.JSONLD_MARK[0]) < idx.index("</head>")
    assert idx.index(sg.FOLLOW_MARK[0]) < idx.index("</body>")


def test_register_facts_are_labelled_by_basis():
    F, _ = built()
    cx = F.get("projects/chapelcross-data-centre-campus-cx-tech.html")
    if cx is None:
        return  # project not in the archive on this run
    assert "<td>Planning reference</td><td>26/1649/PIP</td><td>reported</td>" in cx


def test_no_public_output_links_to_briefs():
    F, _ = built()
    for path, text in F.items():
        if path != "robots.txt":
            assert "/briefs/" not in text, path


# ---- reproducible build: the builder reads only files inside the repository -------------------------------

def _mini_site(tmp_path, with_facts=True, drop_project=None, edit=None):
    """A copy of the inputs the builder needs, with no register files and no database."""
    (tmp_path / "data").mkdir()
    for rel in ("data/discussions-index.json", "data/indexnow.json", sg.DATES_REL, "index.html"):
        shutil.copy(os.path.join(ROOT, rel), tmp_path / rel)
    if with_facts:
        doc = json.load(open(os.path.join(ROOT, sg.FACTS_REL), encoding="utf-8"))
        if drop_project:
            del doc["projects"][drop_project]
        if edit:
            edit(doc)
        (tmp_path / sg.FACTS_REL).write_text(json.dumps(doc), encoding="utf-8")
    return str(tmp_path)


def test_builder_fails_clearly_when_facts_file_is_missing(tmp_path, capsys):
    site = _mini_site(tmp_path, with_facts=False)
    assert sg.main(["--site", site, "--build-date", BUILD_DATE]) == 2
    err = capsys.readouterr().err
    assert "data/register-facts-public.json is missing" in err and "export_register_facts.py" in err
    assert not (tmp_path / "projects").exists()  # nothing written


def test_builder_fails_when_a_page_project_has_no_entry(tmp_path, capsys):
    site = _mini_site(tmp_path, drop_project="Whitelee")
    assert sg.main(["--site", site, "--build-date", BUILD_DATE]) == 2
    err = capsys.readouterr().err
    assert "no entry for 1 project page(s): Whitelee" in err
    assert not (tmp_path / "projects").exists()


def test_builder_rejects_internal_wording_and_bad_links(tmp_path):
    def edit(doc):
        e = doc["projects"]["Chapelcross data centre campus (CX Tech)"]
        e["facts"][0]["value"] = "decided by the user on 12345678901234"
        e["sources"].append("http://example.org/not-https")
    site = _mini_site(tmp_path, edit=edit)
    try:
        sg.build_files(site, BUILD_DATE)
    except sg.BuildError as e:
        msg = str(e)
        assert "internal wording 'user'" in msg and "post-ID-sized number" in msg and "non-Facebook https link" in msg
    else:
        raise AssertionError("invalid facts file was accepted")


def test_public_facts_file_holds_no_internal_content():
    raw = open(os.path.join(ROOT, sg.FACTS_REL), encoding="utf-8").read()
    for pat in (r"\buser\b", r"alias", r"\d{13,}", r"facebook\.com", r"[\w.+-]+@[\w-]+\.[\w.]+",
                r"returned by search", r"/Users/", r"objects\.sqlite", r"(?i)searchland|vitreous|openstreetmap"):
        assert not re.search(pat, raw), pat
    doc = json.loads(raw)
    assert all(u.startswith("https://") for p in doc["projects"].values() for u in p["sources"])


def test_exporter_whitelists_fields_and_drops_internal_notes():
    dc_row = {"id": "dc-x", "name": "X", "aliases": ["X campus"], "alias_note": "decided by the user, post 1234567890123",
              "groups": ["Some group"], "location": "Somewhere", "tec_cross_reference": None, "status_verified": False,
              "application_ref": "26/0001/PIP", "status_reported": "Validated", "developer_reported": "Dev Ltd",
              "council": "A Council", "capacity_reported": "1 GW",
              "sources": ["https://example.org/a", "http://example.org/not-https"]}
    corridor = {"name": "C", "aliases": ["c to d"], "status": "internal status", "consent": "S37 submitted",
                "operator": "Grid Co", "kind": "grid corridor", "source": "https://example.org/c",
                "reported_sources_not_confirmed": ["https://example.org/unconfirmed"]}
    e = ex.public_entry(dc_row, corridor, [{"ref": "R1", "status": "Operational"}] * 2, [{"file": "TEC", "status": "Built"}])
    blob = json.dumps(e)
    for forbidden in ("alias", "decided by the user", "1234567890123", "Some group", "Somewhere", "internal status",
                      "unconfirmed", "not-https", "dc-x"):
        assert forbidden not in blob, forbidden
    labels = [f["label"] for f in e["facts"]]
    assert "Planning reference (TEC)" not in labels and "REPD rows with this name" in labels
    assert e["sources"] == ["https://example.org/a", "https://example.org/c"]


def test_licence_credits_appear_only_where_licensed_facts_are_shown():
    F, _ = built()
    wl = F["projects/whitelee.html"]
    assert "Contains public sector information licensed under the Open Government Licence v3.0." in wl
    assert "Supported by National Energy SO Open Data" in wl
    assert "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/" in wl
    cx = F["projects/chapelcross-data-centre-campus-cx-tech.html"]
    assert "Data credits" not in cx  # only reported facts: they link to their own sources
    for path, text in F.items():
        if path.startswith("projects/") and path.endswith(".md") and "| register |" in text:
            assert "## Data credits" in text, path


def test_llms_txt_explains_why_the_page_count_is_one_lower():
    F, stats = built()
    gap = stats["index_records"] - stats["records"]
    assert gap == 1
    note = (f"The discussions index holds {stats['index_records']:,} records; these pages cover "
            f"{stats['records']:,} because 1 record is excluded from them.")
    assert note in F["llms.txt"]
    assert not re.search(r"\d{13,}", F["llms.txt"])  # the excluded record is not identified


# ---- provenance and source dates ---------------------------------------------------------------------------

def test_exporter_reads_primary_files_and_never_opens_the_objects_database():
    src = open(os.path.join(ROOT, "scripts", "export_register_facts.py"), encoding="utf-8").read()
    for forbidden in ("objects.sqlite", "tec_project", "repd_record", "OBJECTS_DEFAULT", "site_source", "searchland_assets"):
        assert forbidden not in src, forbidden
    assert src.count("sqlite3.connect(") == 1  # only the REPD release is opened
    assert "repd_projects" in src and "source_files" in src and '"Project Status"' in src
    assert "SEO_REPD_RELEASE" in src and "SEO_TEC_CSV" in src and "SEO_EMBEDDED_CSV" in src


def test_embedded_register_status_has_its_own_label_and_source():
    only_emb = ex.public_entry(None, None, [], [{"file": "Embedded", "status": "Built"}])
    assert [(f["label"], f["source"]) for f in only_emb["facts"]] == [("Embedded Register project status", "neso_embedded")]
    both = ex.public_entry(None, None, [], [{"file": "Embedded", "status": "Scoping"}, {"file": "TEC", "status": "Built"}])
    assert [(f["label"], f["value"], f["source"]) for f in both["facts"]] == [("TEC project status", "Built", "neso_tec")]
    two = ex.public_entry(None, None, [], [{"file": "Embedded", "status": "A"}, {"file": "Embedded", "status": "B"}])
    assert ("Embedded Register rows with this name", "2") in [(f["label"], f["value"]) for f in two["facts"]]


def test_public_file_dates_are_iso_or_unavailable_and_hashes_are_present():
    doc = json.load(open(os.path.join(ROOT, sg.FACTS_REL), encoding="utf-8"))
    for sid, meta in doc["sources"].items():
        if "licence" not in meta:
            continue
        labels = {d["label"] for d in meta["dates"]}
        assert {"Release date", "Download date", "Facts exported"} <= labels, sid
        for d in meta["dates"]:
            assert d["label"] == "Edition" or d["value"] == "unavailable" or re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["value"]), (sid, d)
        assert meta["files"] and all(re.fullmatch(r"[0-9a-f]{64}", f["sha256"]) for f in meta["files"]), sid


def test_credits_show_every_source_date_for_the_sources_used():
    F, _ = built()
    doc = json.load(open(os.path.join(ROOT, sg.FACTS_REL), encoding="utf-8"))
    page = F["projects/whitelee.md"]
    for sid in ("repd", "neso_tec"):
        line = "Source dates: " + "; ".join(f"{d['label']}: {d['value']}" for d in doc["sources"][sid]["dates"]) + "."
        assert line in page, sid
    assert "Release date: 2026-08-03" in page and "Download date: 2026-08-25" in page  # REPD
    assert "Release date: 2026-10-10" in page and "Download date: 2026-10-13" in page  # NESO TEC
    assert "unavailable" not in page and "File name date" not in page and "Local copy created" not in page
    assert "Embedded Register" not in page  # Whitelee takes nothing from it
    golt = F["projects/golticlay-wind-farm.md"]
    assert "Data: Embedded Register, National Energy System Operator." in golt


def test_builder_rejects_a_missing_or_invalid_source_date(tmp_path):
    def drop_release(doc):
        doc["sources"]["repd"]["dates"] = [d for d in doc["sources"]["repd"]["dates"] if d["label"] != "Release date"]
    (tmp_path / "a").mkdir()
    site = _mini_site(tmp_path / "a", edit=drop_release)
    try:
        sg.build_files(site, BUILD_DATE)
    except sg.BuildError as e:
        assert "date 'Release date' missing" in str(e)
    else:
        raise AssertionError("missing date accepted")

    def bad_value(doc):
        for d in doc["sources"]["neso_tec"]["dates"]:
            if d["label"] == "Download date":
                d["value"] = "10 October 2026"
    (tmp_path / "b").mkdir()
    site = _mini_site(tmp_path / "b", edit=bad_value)
    try:
        sg.build_files(site, BUILD_DATE)
    except sg.BuildError as e:
        assert "'Download date' must be an ISO date or 'unavailable'" in str(e)
    else:
        raise AssertionError("invalid date accepted")


def test_exporter_keeps_no_machine_paths_and_asks_for_its_inputs(tmp_path, monkeypatch):
    src = open(os.path.join(ROOT, "scripts", "export_register_facts.py"), encoding="utf-8").read()
    for forbidden in ("/Users/", "CloudStorage", "OneDrive", "expanduser", "gen-d73d"):
        assert forbidden not in src, forbidden
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "data_centre_register.json").write_text('{"projects": []}')
    (tmp_path / "data" / "grid_corridor_supplement.json").write_text('{"corridors": []}')
    for env in (ex.ENV_REPD, ex.ENV_TEC, ex.ENV_EMBEDDED):
        monkeypatch.delenv(env, raising=False)
    try:
        ex.main(["--site", str(tmp_path)])
    except SystemExit as e:
        assert "no REPD release given; use --repd-release or set SEO_REPD_RELEASE" in str(e.code)
    else:
        raise AssertionError("exporter ran without its inputs")


# ---- register records, identifier mapping, visible label, Rufus clean-up ---------------------------------------

MAPPED = ("Whitelee", "Arecleoch", "Golticlay Wind Farm", "Mochrum Fell Wind Farm", "Leithenwater Wind Energy Hub - Wind Farm",
          "Newlands Hill Wind Energy Hub", "Scoop Hill Wind Farm", "Shinness Wind Farm", "Sanquhar II Wind Farm")


def _records(name):
    doc = json.load(open(os.path.join(ROOT, sg.FACTS_REL), encoding="utf-8"))
    return doc["projects"][name]["records"]


def test_every_multi_row_page_is_mapped_and_lists_each_record_once():
    mapping = json.load(open(os.path.join(ROOT, ex.MAPPING_REL), encoding="utf-8"))["projects"]
    assert set(mapping) == set(MAPPED)
    for name in MAPPED:
        recs = _records(name)
        assert [(r["register"], r["id"]) for r in recs] == [(m["register"], str(m["id"])) for m in mapping[name]["records"]]
        assert len({(r["register"], r["id"]) for r in recs}) == len(recs)
        for r in recs:
            assert r["relation"].strip() and r["basis"] in sg.RECORD_BASES


def test_record_tables_render_every_identifier_and_never_combine_statuses():
    F, _ = built()
    for name in MAPPED:
        slug = sg.slugify(name)
        page, md = F[f"projects/{slug}.html"], F[f"projects/{slug}.md"]
        assert "<h2>Register records</h2>" in page and "## Register records" in md
        for r in _records(name):
            assert f'<td data-label="Identifier"><span style="white-space:nowrap">{r["id"]}</span></td>' in page and f"| {r['id']} |" in md, (name, r["id"])
        assert "REPD reference" not in md and "REPD status" not in md  # no single first-row status for these pages
    wl = F["projects/whitelee.md"]
    assert "13 register records are listed (8 REPD, 5 NESO TEC)" in wl
    assert "Their statuses differ, so no single status is given" in wl
    assert "No single status applies." in wl


def test_unverified_relationships_are_labelled_as_such():
    F, _ = built()
    assert "relation to REPD 3258 is unverified" in F["projects/arecleoch.md"]
    assert "the relation is unverified" in F["projects/arecleoch.md"]
    assert "so the link is unverified" in F["projects/golticlay-wind-farm.md"]


def test_arecleoch_has_a_visible_label_but_keeps_its_address():
    F, _ = built()
    page = F["projects/arecleoch.html"]
    assert "<h1>Arecleoch Wind Farm and extension</h1>" in page
    assert "projects/arecleoch.html" in F["sitemap.xml"]
    assert "[Arecleoch Wind Farm and extension](https://slava.it.com/projects/arecleoch.md)" in F["llms.txt"]
    assert "Arecleoch Wind Farm and extension" in F["renewables-wind/index.html"]


def test_exporter_rejects_unmapped_or_incomplete_multi_row_pages():
    exact = {("repd", "1"), ("repd", "2")}
    assert "no entry in data/register-mapping.json" in ex.mapping_problem("P", exact, None)
    assert "omits exact-name record" in ex.mapping_problem("P", exact, {"records": [{"register": "repd", "id": "1"}]})
    assert ex.mapping_problem("P", exact, {"records": [{"register": "repd", "id": 1}, {"register": "repd", "id": "2"}]}) is None
    assert ex.mapping_problem("P", {("repd", "1")}, None) is None  # a single record needs no mapping


def _primary():
    repd = {"10": {"name": "Alpha Wind Farm", "status": "Operational", "mw": 50.0, "updated": "2020-01-02", "events": {"Operational": "2019-05-06"}},
            "11": {"name": "Alpha Wind Farm Battery", "status": "Planning Permission Granted", "mw": None, "updated": None, "events": {}}}
    links = {frozenset({"10", "11"})}
    neso = {("neso_tec", "PRO-1-1"): {"name": "Alpha Wind Farm", "status": "Built", "stage": "1", "conn": "50", "cum": "50", "eff": None},
            ("neso_tec", "PRO-1-2"): {"name": "Alpha Wind Farm", "status": "Scoping", "stage": "2", "conn": "0", "cum": "80", "eff": "2031-01-02"}}
    return repd, links, neso


def _mapped(*records):
    return {"records": [dict(r) for r in records]}


def test_build_records_reads_primary_values_and_checks_each_basis():
    repd, links, neso = _primary()
    ok = _mapped({"register": "repd", "id": "10", "basis": "name_exact", "relation": "Exact."},
                 {"register": "repd", "id": "11", "basis": "register_link", "with": "10", "relation": "Linked."},
                 {"register": "neso_tec", "id": "PRO-1-1", "basis": "neso_project_number", "group": "PRO-1", "relation": "Stage 1."},
                 {"register": "neso_tec", "id": "PRO-1-2", "basis": "unverified", "relation": "Unverified."})
    out = ex.build_records("Alpha Wind Farm", ok, repd, links, neso)
    assert [r["id"] for r in out] == ["10", "11", "PRO-1-1", "PRO-1-2"]
    assert out[0]["capacity"] == "50 MW" and out[0]["date"] == "record updated 2020-01-02; status event 2019-05-06"
    assert out[1]["capacity"] == "not recorded" and out[1]["date"] == "record updated date not recorded"
    assert out[3]["capacity"] == "connected 0 MW; cumulative 80 MW" and out[3]["date"] == "MW effective from 2031-01-02"
    for bad, why in [({"register": "repd", "id": "99", "basis": "name_exact", "relation": "x"}, "not found"),
                     ({"register": "repd", "id": "11", "basis": "name_exact", "relation": "x"}, "basis name_exact"),
                     ({"register": "repd", "id": "10", "basis": "register_link", "with": "12", "relation": "x"}, "no REPD link"),
                     ({"register": "neso_tec", "id": "PRO-1-1", "basis": "neso_project_number", "group": "PRO-9", "relation": "x"}, "does not belong"),
                     ({"register": "repd", "id": "10", "basis": "made_up", "relation": "x"}, "unknown basis")]:
        try:
            ex.build_records("Alpha Wind Farm", _mapped(bad, {"register": "repd", "id": "11", "basis": "register_link", "with": "10", "relation": "x"}), repd, links, neso)
        except ex.ExportError as e:
            assert why in str(e), (why, str(e))
        else:
            raise AssertionError(f"accepted: {why}")


def test_builder_rejects_malformed_records_and_credit_sources(tmp_path):
    def break_record(doc):
        doc["projects"]["Whitelee"]["records"][0]["basis"] = "guess"
        doc["projects"]["Whitelee"]["records"][1]["register"] = "reported"
        doc["sources"]["companies_house"].pop("checked")
    site = _mini_site(tmp_path, edit=break_record)
    try:
        sg.build_files(site, BUILD_DATE)
    except sg.BuildError as e:
        msg = str(e)
        assert "unknown basis 'guess'" in msg and "is not a licensed source" in msg and "source companies_house: checked missing" in msg
    else:
        raise AssertionError("malformed records accepted")


def test_rufus_has_no_directory_derived_claims_and_marks_the_unverified_ones():
    F, _ = built()
    raw = open(os.path.join(ROOT, sg.FACTS_REL), encoding="utf-8").read()
    page = F["projects/rufus-data-centre-campus-hurlford.md"]
    entry = json.dumps(json.loads(raw)["projects"]["Rufus data centre campus (Hurlford)"])
    for blob in (raw, page, F["data-centres/index.md"], F["llms-full.txt"]):
        for banned in ("baxtel", "theconstructionindex", "540 MW", "aggregator"):
            assert banned not in blob, banned
    for blob in (entry, page, F["projects/rufus-data-centre-campus-hurlford.html"]):
        assert "ILI Group" not in blob  # the directory-derived developer name; the Cato project's own name is a different page
    assert "| Capacity | Unverified: no primary source found | unverified |" in page
    assert "| Council (inferred) | East Ayrshire Council, inferred from the site's location in Hurlford; not confirmed by a planning register | inferred |" in page
    assert "| Council |" not in page
    assert "| Status | Unverified: no primary source has been confirmed for display here, so check the council's public planning register | unverified |" in page
    assert "ILI RUFUS LIMITED (company number SC825440); Active; incorporated 2024-10-10" in page
    assert "Intelligent Land Investments Group Plc" in page


def test_companies_house_credit_carries_its_terms_note_and_check_date():
    F, _ = built()
    page = F["projects/rufus-data-centre-campus-hurlford.html"]
    assert "Data credits" in page and "Companies House" in page
    assert "imposes no rules or requirements on how the information on the public register is used (page updated 9 August 2019)" in page
    assert "Source dates: Terms checked: 2026-10-17." in re.sub(r"<[^>]+>", "", page)  # the date sits in a no-break span
    assert "does not imply endorsement" in page


def test_whitelee_states_that_records_describe_registered_assets_only():
    F, _ = built()
    note = ("The records listed describe the registered assets. Several archived posts discuss a repowering proposal; "
            "a search of the registers by name did not establish that proposal's register status, so none is shown here.")
    for ext in ("md", "html"):
        assert note in F[f"projects/whitelee.{ext}"], ext
    assert note in F["projects/whitelee.md"].split("## What is the planning status of Whitelee?")[1].split("## What are the main")[0]
    assert "repowering proposal" not in F["projects/arecleoch.md"]  # the note is Whitelee's own


def test_builder_rejects_a_note_without_records_or_with_internal_wording(tmp_path):
    def bad_notes(doc):
        doc["projects"]["Whitelee"]["note"] = "decided by the user"
        doc["projects"]["Chapelcross data centre campus (CX Tech)"]["note"] = "a note without records"
    site = _mini_site(tmp_path, edit=bad_notes)
    try:
        sg.build_files(site, BUILD_DATE)
    except sg.BuildError as e:
        assert "Whitelee: invalid note" in str(e) and "a note needs register records" in str(e)
    else:
        raise AssertionError("bad notes accepted")


def test_record_tables_stack_into_labelled_cards_on_narrow_screens():
    F, _ = built()
    for name in MAPPED:
        page = F[f"projects/{sg.slugify(name)}.html"]
        i = page.index("<h2>Register records</h2>")
        assert '<div style="overflow-x:auto"><table class="records"><thead>' in page[i:i + 1200], name
        assert page.count("</table></div>") == 1, name
        assert "@media (max-width:640px)" in page[:page.index("</style>")], name
        for label in sg.RECORD_HEAD:
            assert f'data-label="{label}"' in page, (name, label)
        assert page.count('data-label="Relationship"') == len(_records(name)), name  # every record shows its relationship label
    for other in ("chapelcross-data-centre-campus-cx-tech", "rufus-data-centre-campus-hurlford"):
        assert "records" not in F[f"projects/{other}.html"][:F[f"projects/{other}.html"].index("</style>")]  # other pages are unchanged


def test_long_links_wrap_so_phone_screens_do_not_widen():
    F, _ = built()
    checked = 0
    for path, text in F.items():
        if not path.endswith(".html") or path == "index.html":
            continue
        body = text[text.index("<body>"):]
        for m in re.finditer(r"<li([^>]*)>(.*?)</li>", body, flags=re.S):
            visible = htmllib.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
            if any(len(tok) > 38 for tok in visible.split()):
                checked += 1
                assert "overflow-wrap:anywhere" in m.group(1), (path, visible[:60])
    assert checked > 40  # the rule was exercised on the credit and source lists of the project pages


def test_exporter_labels_inferred_and_unverified_facts_by_their_own_basis():
    e = ex.public_entry({"status_reported": "Unverified: nothing found", "capacity_reported": "Unverified: no source",
                         "council": "A Council, from the location", "council_inferred": True, "developer_reported": "Dev Ltd"})
    basis = {f["label"]: f["basis"] for f in e["facts"]}
    assert basis == {"Status": "unverified", "Developer": "reported", "Council (inferred)": "inferred", "Capacity": "unverified"}


def test_unverified_status_is_not_repeated_in_the_capsule():
    F, _ = built()
    cap = F["projects/rufus-data-centre-campus-hurlford.md"].split("\n")[2]
    assert "Status: Unverified: no primary source has been confirmed for display here, so check the council's public planning register." in cap
    assert "(unverified)" not in cap and "(reported)" not in cap


def test_dates_and_identifiers_do_not_break_at_hyphens_but_the_text_is_unchanged():
    F, _ = built()
    page = F["projects/whitelee.html"]
    assert '<span style="white-space:nowrap">2010-05-20</span>' in page
    plain = re.sub(r"<[^>]+>", "", page)
    assert "record updated 2010-05-20; status event 2007-12-14" in plain  # wrapping changes markup only, not the words or the copied text
    assert "record updated 2010-05-20; status event 2007-12-14" in F["projects/whitelee.md"]


# ---- correction contact, content-change dates and recorded source dates -------------------------------------

CONTACT = "slava@atlasglobal.energy"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
CHAPELCROSS = "Chapelcross data centre campus (CX Tech)"
CHAPELCROSS_URL = "https://slava.it.com/projects/chapelcross-data-centre-campus-cx-tech.html"


def _lastmod(sitemap_xml):
    return {u.find("s:loc", NS).text: u.find("s:lastmod", NS).text for u in ET.fromstring(sitemap_xml).findall("s:url", NS)}


def _edit_chapelcross(doc):
    doc["projects"][CHAPELCROSS]["facts"][0]["value"] = "Validated and open for comment"


def test_every_project_page_shows_the_correction_contact_and_no_other_address_appears():
    F, stats = built()
    sentence = "For correction, privacy or removal requests:"
    pages = [p for p in F if p.startswith("projects/")]
    assert len([p for p in pages if p.endswith(".html")]) == stats["project_pages"] == 36
    for path in pages:
        if path.endswith(".html"):
            footer = F[path][F[path].index("<footer>"):F[path].index("</footer>")]
            assert f'{sentence} <a href="mailto:{CONTACT}">{CONTACT}</a>.' in footer, path
        else:
            assert f"{sentence} {CONTACT}." in F[path], path
    found = {m.rstrip(".") for text in F.values() for m in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)}  # a sentence may end in a full stop
    assert found == {CONTACT}, found


def test_committed_pages_are_what_the_builder_produces_and_keep_their_recorded_dates():
    F, stats = built()
    assert stats["changed_pages"] == [], "pages are out of date: run python3 scripts/build_seo_geo.py and commit the result"
    for path, text in F.items():
        if path in ("llms.txt", "feed.xml") or path.startswith("feeds/"):
            continue  # these carry the build date
        assert open(os.path.join(ROOT, path), encoding="utf-8").read() == text, path
    state = json.load(open(os.path.join(ROOT, sg.DATES_REL), encoding="utf-8"))["pages"]
    assert _lastmod(F["sitemap.xml"]) == {u: e["modified"] for u, e in state.items()}
    assert max(state[u]["modified"] for u in state) < BUILD_DATE


def test_dateModified_in_each_page_matches_its_sitemap_lastmod():
    F, _ = built()
    lastmod = _lastmod(F["sitemap.xml"])
    checked = 0
    for path, text in F.items():
        if not path.endswith(".html"):
            continue
        url = ("https://slava.it.com/" if path == "index.html"
               else f"https://slava.it.com/{path[:-len('index.html')]}" if path.endswith("/index.html")
               else f"https://slava.it.com/{path}")
        assert re.findall(r'"dateModified": "([\d-]+)"', text) == [lastmod[url]], path
        checked += 1
    assert checked == len(lastmod) == 40


def test_page_hash_ignores_dateModified_and_nothing_else():
    a = '<script>{"dateModified": "2026-10-01", "x": 1}</script>'
    assert sg.page_hash([a]) == sg.page_hash([a.replace("2026-10-01", "2026-12-31")])
    assert sg.page_hash([a]) != sg.page_hash([a.replace('"x": 1', '"x": 2')])
    assert sg.page_hash([a, "b"]) != sg.page_hash([a + "b"])  # the files of a page keep their boundaries


def test_a_content_change_sets_only_that_pages_lastmod_and_a_later_rebuild_is_stable(tmp_path):
    site = _mini_site(tmp_path, edit=_edit_chapelcross)
    F, stats = sg.build_files(site, "2026-10-25")
    assert stats["changed_pages"] == [CHAPELCROSS_URL]
    lastmod = _lastmod(F["sitemap.xml"])
    assert lastmod[CHAPELCROSS_URL] == "2026-10-25"
    assert all(d != "2026-10-25" for u, d in lastmod.items() if u != CHAPELCROSS_URL)
    assert '"dateModified": "2026-10-25"' in F["projects/chapelcross-data-centre-campus-cx-tech.html"]
    (tmp_path / sg.DATES_REL).write_text(F[sg.DATES_REL], encoding="utf-8")
    F2, stats2 = sg.build_files(site, "2026-10-30")
    assert stats2["changed_pages"] == []
    for path in ("sitemap.xml", sg.DATES_REL, "projects/chapelcross-data-centre-campus-cx-tech.html", "index.html"):
        assert F2[path] == F[path], path


def test_a_new_page_takes_the_build_date(tmp_path):
    site = _mini_site(tmp_path)
    state = json.load(open(tmp_path / sg.DATES_REL, encoding="utf-8"))
    del state["pages"][CHAPELCROSS_URL]
    (tmp_path / sg.DATES_REL).write_text(json.dumps(state), encoding="utf-8")
    F, stats = sg.build_files(site, "2026-10-25")
    assert stats["changed_pages"] == [CHAPELCROSS_URL] and _lastmod(F["sitemap.xml"])[CHAPELCROSS_URL] == "2026-10-25"


def test_builder_needs_the_page_dates_baseline(tmp_path, capsys):
    site = _mini_site(tmp_path)
    os.remove(tmp_path / sg.DATES_REL)
    assert sg.main(["--site", site, "--build-date", BUILD_DATE]) == 2
    err = capsys.readouterr().err
    assert "data/page-dates.json is missing" in err and "--seed-page-dates" in err
    assert not (tmp_path / "projects").exists()


def test_a_changed_page_cannot_take_a_date_before_its_recorded_change(tmp_path):
    site = _mini_site(tmp_path, edit=_edit_chapelcross)
    try:
        sg.build_files(site, "2026-09-01")
    except sg.BuildError as e:
        assert "earlier than its recorded change date" in str(e)
    else:
        raise AssertionError("a changed page was given a date before its recorded change")


def test_seeding_from_the_committed_pages_reproduces_the_committed_dates(tmp_path):
    state = json.load(open(os.path.join(ROOT, sg.DATES_REL), encoding="utf-8"))["pages"]
    for rel in ["sitemap.xml"] + [f for u in state for f in sg.url_files(u)]:
        os.makedirs(os.path.dirname(tmp_path / rel), exist_ok=True)
        shutil.copy(os.path.join(ROOT, rel), tmp_path / rel)
    assert sg.seed_page_dates(str(tmp_path)) == open(os.path.join(ROOT, sg.DATES_REL), encoding="utf-8").read()
    assert sg.main(["--site", str(tmp_path), "--seed-page-dates"]) == 0
    assert sg.main(["--site", str(tmp_path), "--seed-page-dates"]) == 2  # written once; never overwritten


def test_recorded_source_dates_describe_the_exact_files_and_fill_the_credit_lines():
    rec = json.load(open(os.path.join(ROOT, ex.DATES_REL), encoding="utf-8"))
    facts = json.load(open(os.path.join(ROOT, sg.FACTS_REL), encoding="utf-8"))
    assert rec["schema"] == 1 and set(rec["sources"]) == {"repd", "neso_tec", "neso_embedded"}
    for sid, e in rec["sources"].items():
        assert e["sha256"] in {f["sha256"] for f in facts["sources"][sid]["files"]}, sid
        dates = {d["label"]: d["value"] for d in facts["sources"][sid]["dates"]}
        assert dates["Release date"] == e["release_date"] and dates["Download date"] == e["download_date"], sid
        assert "File name date" not in dates and "Local copy created" not in dates, sid
        assert e["release_date"] <= e["download_date"] <= facts["generated"], sid
        assert e["release_evidence"].strip() and e["download_evidence"].strip(), sid
    raw = open(os.path.join(ROOT, ex.DATES_REL), encoding="utf-8").read()
    for pat in (r"\buser\b", r"\d{13,}", r"[\w.+-]+@[\w-]+\.[\w.]+", r"/Users/", r"facebook\.com"):
        assert not re.search(pat, raw), pat


def _dates_meta(sha):
    return {"data_sha256": sha, "dates": [{"label": "Release date", "value": "unavailable"},
                                          {"label": "Download date", "value": "unavailable"},
                                          {"label": "File name date", "value": "2026-10-10"},
                                          {"label": "Local copy created", "value": "2026-10-13"}]}


def test_recorded_dates_apply_only_to_the_file_they_describe(capsys):
    sha = "a" * 64
    rec = {"schema": 1, "sources": {"neso_tec": {"sha256": sha, "release_date": "2026-10-10", "release_evidence": "file name",
                                                 "download_date": "2026-10-13", "download_evidence": "notes"}}}
    m = _dates_meta(sha)
    ex.apply_recorded_dates(rec, "neso_tec", m)
    assert m["dates"] == [{"label": "Release date", "value": "2026-10-10"}, {"label": "Download date", "value": "2026-10-13"}]
    other = _dates_meta("b" * 64)  # a refreshed file: the old entry must not describe it
    ex.apply_recorded_dates(rec, "neso_tec", other)
    assert [d["value"] for d in other["dates"]] == ["unavailable", "unavailable", "2026-10-10", "2026-10-13"]
    assert "no entry for the neso_tec file" in capsys.readouterr().err
    for field, value, why in (("release_date", "10 October 2026", "release_date is not an ISO date"),
                              ("download_evidence", "", "download_evidence is missing"),
                              ("release_evidence", "decided by the user", "release_evidence has internal wording 'user'")):
        bad = json.loads(json.dumps(rec))
        bad["sources"]["neso_tec"][field] = value
        try:
            ex.apply_recorded_dates(bad, "neso_tec", _dates_meta(sha))
        except ex.ExportError as e:
            assert why in str(e), (field, str(e))
        else:
            raise AssertionError(f"{field} {value!r} was accepted")


def test_credit_line_dates_do_not_break_at_hyphens_but_the_text_is_unchanged():
    F, _ = built()
    page = F["projects/whitelee.html"]
    assert '<span style="white-space:nowrap">2026-08-03</span>' in page and '<span style="white-space:nowrap">2026-10-13</span>' in page
    plain = re.sub(r"<[^>]+>", "", page)
    assert "Release date: 2026-08-03; Latest record update in the file: 2026-07-24; Download date: 2026-08-25" in plain
    assert "Release date: 2026-08-03; Latest record update in the file: 2026-07-24; Download date: 2026-08-25" in F["projects/whitelee.md"]


def test_meta_descriptions_end_at_a_sentence_never_mid_date():
    F, _ = built()
    checked = 0
    for path, text in F.items():
        if not path.endswith(".html") or path == "index.html":
            continue
        d = htmllib.unescape(re.search(r'<meta name="description" content="([^"]*)"', text).group(1))
        assert 40 <= len(d) <= 160 and d.endswith("."), (path, d)  # whole sentences only, so no date is cut short
        checked += 1
    assert checked == 39  # 36 project pages and 3 hubs


def test_meta_description_cuts_a_very_long_first_sentence_at_a_word():
    long_first = "word " * 60 + "end."
    d = sg.meta_description(long_first, 160)
    assert len(d) <= 160 and d.endswith("…") and " " not in d[-3:] and not d[:-1].endswith("wor")
    assert sg.meta_description("One. Two sentences fit. Three is too long to add here at all", 25) == "One. Two sentences fit."


# ---- reader-trust wording: footer, key, heading, hubs -------------------------------------------------------

def _footer(text):
    return text[text.index("<footer>"):text.index("</footer>")]


def test_every_project_and_hub_page_says_posts_are_not_independently_verified_and_gives_the_contact():
    F, _ = built()
    sentence = "Facebook group posts are archived public posts and are not independently verified. Post text is not reproduced."
    pages = [p for p in F if (p.startswith("projects/") or p.endswith("/index.html") or p.endswith("/index.md")) and p != "index.html"]
    assert len(pages) == 2 * (36 + 3)
    for path in pages:
        text = F[path]
        if path.endswith(".html"):
            foot = _footer(text)
            assert sentence in foot and f'mailto:{CONTACT}' in foot, path
        else:
            assert sentence in text and f"{CONTACT}." in text, path
        assert "labelled as reported or register" not in text, path


def test_facts_heading_is_neutral_and_the_key_defines_only_the_labels_the_page_uses():
    F, _ = built()
    doc = json.load(open(os.path.join(ROOT, sg.FACTS_REL), encoding="utf-8"))
    seen = set()
    for path, text in F.items():
        if not (path.startswith("projects/") and path.endswith(".html")):
            continue
        assert "<h2>Register facts</h2>" not in text and "<h2>Facts and where they come from</h2>" in text, path
        head = text[text.index("<h2>Facts and where they come from</h2>"):]
        key = re.search(r'<p class="key">Basis: (.*?)</p>', head)
        used = set(re.findall(r"</td><td>(register|reported|inferred|unverified)</td></tr>", text))
        assert key and head.index(key.group(0)) < head.index("<table"), path  # the key sits above the table
        defined = set(re.findall(r"(register|reported|inferred|unverified) = ", key.group(1)))
        assert defined == used, (path, defined, used)
        seen |= used
    assert seen == set(sg.FACT_BASES)  # all four labels occur somewhere on the site, each defined where used
    md = F["projects/rufus-data-centre-campus-hurlford.md"]
    assert "## Facts and where they come from" in md and "Basis: register = " in md and "unverified = no source we could rely on was found." in md
    assert "Controlling company (person with significant control)" in md and "Persons with significant control" not in md
    assert not any("Persons with significant control" in json.dumps(p) for p in doc["projects"].values())


def test_abbreviations_are_defined_on_the_pages_that_use_them_and_only_there():
    F, _ = built()
    wl, cx = F["projects/whitelee.html"], F["projects/chapelcross-data-centre-campus-cx-tech.html"]
    assert ('Abbreviations: REPD = Renewable Energy Planning Database; TEC = Transmission Entry Capacity register; '
            'NESO = National Energy System Operator.') in wl
    assert "Abbreviations:" not in cx and "REPD" not in cx and "TEC" not in re.sub(r"[^A-Za-z ]", " ", cx).split()
    for path, text in F.items():
        if path.startswith("projects/") and path.endswith(".html"):
            body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S)
            uses = bool(re.search(r"\bREPD\b", re.sub(r'<p class="key">Abbreviations:.*?</p>', "", body)))
            assert uses == ("REPD = Renewable Energy Planning Database" in body), path
