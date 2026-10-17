"""Tests for scripts/build_seo_geo.py on the real site data. Builds in memory and writes nothing.
Run: python3 -m pytest -q tests/test_build_seo_geo.py"""
import html as htmllib, json, os, re, sys, xml.etree.ElementTree as ET
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import build_seo_geo as sg  # noqa: E402

OBJECTS = os.environ.get("SEO_OBJECTS_DB", sg.OBJECTS_DEFAULT)
_CACHE = {}


def built():
    if "v" not in _CACHE:
        _CACHE["v"] = sg.build_files(ROOT, OBJECTS, "2026-10-17")
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
