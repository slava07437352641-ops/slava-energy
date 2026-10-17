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


def built():
    if "v" not in _CACHE:
        _CACHE["v"] = sg.build_files(ROOT, "2026-10-17")
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
    assert urls[0].find("s:lastmod", ns).text == stats["newest"]


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
    for rel in ("data/discussions-index.json", "data/indexnow.json", "index.html"):
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
    assert sg.main(["--site", site, "--build-date", "2026-10-17"]) == 2
    err = capsys.readouterr().err
    assert "data/register-facts-public.json is missing" in err and "export_register_facts.py" in err
    assert not (tmp_path / "projects").exists()  # nothing written


def test_builder_fails_when_a_page_project_has_no_entry(tmp_path, capsys):
    site = _mini_site(tmp_path, drop_project="Whitelee")
    assert sg.main(["--site", site, "--build-date", "2026-10-17"]) == 2
    err = capsys.readouterr().err
    assert "no entry for 1 project page(s): Whitelee" in err
    assert not (tmp_path / "projects").exists()


def test_builder_rejects_internal_wording_and_bad_links(tmp_path):
    def edit(doc):
        e = doc["projects"]["Whitelee"]
        e["facts"][0]["value"] = "decided by the user on 12345678901234"
        e["sources"].append("http://example.org/not-https")
    site = _mini_site(tmp_path, edit=edit)
    try:
        sg.build_files(site, "2026-10-17")
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
    assert "Release date: unavailable" in page and "Download date: unavailable" in page
    assert "Embedded Register" not in page  # Whitelee takes nothing from it
    golt = F["projects/golticlay-wind-farm.md"]
    assert "Data: Embedded Register, National Energy System Operator." in golt


def test_builder_rejects_a_missing_or_invalid_source_date(tmp_path):
    def drop_release(doc):
        doc["sources"]["repd"]["dates"] = [d for d in doc["sources"]["repd"]["dates"] if d["label"] != "Release date"]
    (tmp_path / "a").mkdir()
    site = _mini_site(tmp_path / "a", edit=drop_release)
    try:
        sg.build_files(site, "2026-10-17")
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
        sg.build_files(site, "2026-10-17")
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
