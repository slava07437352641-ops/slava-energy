#!/usr/bin/env python3
"""Build the search and AI-readable outputs for slava.it.com from data/discussions-index.json.

Writes static files at the site root (overwritten on each run): robots.txt, sitemap.xml, llms.txt,
llms-full.txt, feed.xml, feeds/{data-centres,pylons,wind}.xml, projects/<slug>.html and .md for every project
with at least two linked posts, pylons-grid/, data-centres/ and renewables-wind/ (index.html and index.md),
<indexnow-key>.txt, and two marker blocks in index.html (JSON-LD and the follow bar). No network access.

Inputs are inside the repository only: data/discussions-index.json, data/register-facts-public.json (written by
scripts/export_register_facts.py), data/indexnow.json and index.html. A clean clone rebuilds the same files.
The build stops with an error, and writes nothing, if the facts file is missing or invalid, or if a project
page has no entry in it.

Privacy: outputs never contain post text, post titles or author names. They contain group names, dates,
counts, theme tags, register facts (labelled as reported or register, with the licence credits of the
registers) and links to the archive entries (?sel=<id>). Blocked post IDs are dropped everywhere.

Usage: python3 scripts/build_seo_geo.py [--dry-run] [--build-date YYYY-MM-DD] [--site DIR]
"""
import argparse, collections, datetime, html, json, os, re, sys, uuid
from email.utils import format_datetime
from xml.sax.saxutils import escape as xesc

SITE_URL = "https://slava.it.com"
SITE_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACTS_REL = "data/register-facts-public.json"
EXPORT_HINT = "Run scripts/export_register_facts.py where the registers are kept, then commit the file."

# Withheld from every generated output. The first six are the user's deletion orders (project memory);
# 29488742940728054 is withheld from these pages until the user decides (it is not on the deletion list).
BLOCKED_POST_IDS = frozenset({
    "29510992631836418", "1814323132941267", "1814270869613160", "1098654185897696", "1813753316331582",
    "1828353354871578", "29488742940728054"})
BOTS = ["Googlebot", "Bingbot", "OAI-SearchBot", "ChatGPT-User", "GPTBot", "ClaudeBot", "Claude-Web",
        "PerplexityBot", "Google-Extended", "Applebot-Extended"]
HUBS = {
    "pylons-grid": {"name": "Pylons and grid transmission", "cats": {"OHL (Pylons)", "Substation"},
                    "feed": "pylons"},
    "data-centres": {"name": "AI and data centres", "cats": {"Data Centre"}, "feed": "data-centres"},
    "renewables-wind": {"name": "Wind, solar and storage", "cats": {"Onshore Wind", "Solar", "BESS", "Hybrid"},
                        "feed": "wind"},
}
VERTICAL_PHRASE = {"AI data centre": "an AI data centre project", "Pylons and grid": "a pylons and grid project",
                   "Wind, solar and storage": "a wind, solar and storage project"}
JSONLD_MARK = ("<!-- seo-geo:jsonld:start -->", "<!-- seo-geo:jsonld:end -->")
FOLLOW_MARK = ("<!-- seo-geo:follow:start -->", "<!-- seo-geo:follow:end -->")
FEED_ITEMS = 50

# Wording that must never appear in a public fact: internal notes, post-ID-sized numbers, email addresses.
FORBIDDEN = [(re.compile(r"\buser\b", re.I), "internal wording 'user'"),
             (re.compile(r"returned by search|not in search|search did not|reported by the user", re.I), "internal search wording"),
             (re.compile(r"\d{13,}"), "post-ID-sized number"),
             (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "email address")]


class BuildError(Exception):
    """A problem with the inputs. The build stops and writes nothing."""


def norm(s):
    s = str(s or "").lower().replace("’", "").replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


def esc(s):
    return html.escape(str(s), quote=True)


def words(s):
    return len(s.split())


def jsonld(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def rfc822(date):
    return format_datetime(datetime.datetime.fromisoformat(date).replace(tzinfo=datetime.timezone.utc))


def read_json(site, rel, default):
    p = os.path.join(site, rel)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def validate_facts_doc(doc):
    """Check the public facts document. Raises BuildError listing every problem found (first 20)."""
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        raise BuildError(f"{FACTS_REL}: unsupported or missing schema (expected 1). {EXPORT_HINT}")
    problems = []
    srcs = doc.get("sources")
    if not isinstance(srcs, dict) or not srcs:
        raise BuildError(f"{FACTS_REL}: 'sources' is missing. {EXPORT_HINT}")
    for sid, meta in srcs.items():
        if not isinstance(meta, dict) or not meta.get("name"):
            problems.append(f"source {sid}: name missing")
            continue
        if "licence" in meta:
            for k in ("licence_url", "attribution", "source_url"):
                if not meta.get(k):
                    problems.append(f"source {sid}: {k} missing")
                elif k.endswith("_url") and not str(meta[k]).startswith("https://"):
                    problems.append(f"source {sid}: {k} is not an https link")
    if not isinstance(doc.get("data_centre_projects"), list):
        problems.append("'data_centre_projects' list missing")
    projects = doc.get("projects")
    if not isinstance(projects, dict):
        problems.append("'projects' missing")
        projects = {}
    for name, e in projects.items():
        if not isinstance(e, dict) or not isinstance(e.get("facts"), list) or not isinstance(e.get("sources"), list):
            problems.append(f"{name}: needs 'facts' and 'sources' lists")
            continue
        for i, f in enumerate(e["facts"]):
            if not isinstance(f, dict) or set(f) != {"label", "value", "basis", "source"}:
                problems.append(f"{name} fact {i}: fields must be label, value, basis, source")
                continue
            if not str(f["label"]).strip() or not str(f["value"]).strip():
                problems.append(f"{name} fact {i}: empty label or value")
            if f["basis"] not in ("register", "reported"):
                problems.append(f"{name} fact '{f['label']}': basis must be register or reported")
            if f["source"] not in srcs:
                problems.append(f"{name} fact '{f['label']}': unknown source '{f['source']}'")
            for pat, why in FORBIDDEN:
                if pat.search(f"{f['label']} {f['value']}"):
                    problems.append(f"{name} fact '{f['label']}': {why}")
        for u in e["sources"]:
            if not str(u).startswith("https://") or "facebook.com" in str(u):
                problems.append(f"{name}: source link must be a non-Facebook https link: {u}")
    if problems:
        extra = f"\n  ... and {len(problems) - 20} more" if len(problems) > 20 else ""
        raise BuildError(f"{FACTS_REL} is invalid:\n  " + "\n  ".join(problems[:20]) + extra)


def load_public_facts(site):
    path = os.path.join(site, FACTS_REL)
    if not os.path.exists(path):
        raise BuildError(f"{FACTS_REL} is missing. {EXPORT_HINT}")
    try:
        doc = json.load(open(path, encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise BuildError(f"{FACTS_REL} is not valid JSON: {e}")
    validate_facts_doc(doc)
    return doc


def top_themes(counter, k):
    return ", ".join(f"{t} ({n})" for t, n in counter.most_common(k)) or "none tagged"


def fit(required, optional, hi=60):
    opt = list(optional)
    text = " ".join(required + opt)
    while words(text) > hi and opt:
        opt.pop()
        text = " ".join(required + opt)
    return text


def is_data_centre(name, posts, dc_names):
    return name in dc_names or sum("Data Centre" in (r.get("categories") or []) for r in posts) * 2 >= len(posts)


def is_ohl(posts):
    return sum(bool({"OHL (Pylons)", "Substation"} & set(r.get("categories") or [])) for r in posts) * 2 >= len(posts)


def vertical_of(name, posts, dc_names):
    if is_data_centre(name, posts, dc_names):
        return "AI data centre"
    return "Pylons and grid" if is_ohl(posts) else "Wind, solar and storage"


def project_model(name, posts, entry, dc_names):
    posts = sorted(posts, key=lambda r: (r["date"], r["id"]), reverse=True)
    groups = collections.Counter(r["source"]["name"] for r in posts)
    themes = collections.Counter(t for r in posts for t in (r.get("categories") or []))
    latest, earliest = posts[0]["date"], posts[-1]["date"]
    n, g = len(posts), len(groups)
    vertical = vertical_of(name, posts, dc_names)
    facts = [(f["label"], f["value"], f["basis"]) for f in entry["facts"]]
    credits = list(dict.fromkeys(f["source"] for f in entry["facts"]))
    ref = next((f"{lab}: {v} ({b})" for lab, v, b in facts if lab in ("Planning reference", "REPD reference", "Planning reference (TEC)")), None)
    status = next((f"{lab}: {v} ({b})" for lab, v, b in facts if lab in ("Status", "REPD status", "TEC project status", "Consent or stage")), None)
    req = [f"{name} is {VERTICAL_PHRASE[vertical]} tracked on slava.it.com.",
           f"The archive holds {n} community post{'s' if n != 1 else ''} from {g} group{'s' if g != 1 else ''}, latest {latest}.",
           f"{ref}." if ref else "No planning reference is recorded in the registers used.",
           f"{status}." if status else "No status is recorded in the registers used.",
           f"Top recurring themes: {top_themes(themes, 2)}."]
    opt = ["Posts are archived public group posts and are not independently verified."]
    capsule = fit(req, opt)
    if words(capsule) > 60:
        req[-1] = f"Top recurring theme: {top_themes(themes, 1)}."
        capsule = fit(req, opt)
    planning_bits = [f"{lab}: {v} ({b})" for lab, v, b in facts if lab in
                     ("Planning reference", "Application type", "Status", "Consent or stage", "REPD status", "TEC project status")]
    qa = [(f"What is the planning status of {name}?",
           ("Recorded: " + "; ".join(planning_bits) + ".") if planning_bits else
           "No planning status is recorded in the registers used for this page."),
          (f"What are the main community discussions around {name}?",
           f"{n} archived public post{'s' if n != 1 else ''} from {g} group{'s' if g != 1 else ''}, dated {earliest} to {latest}. "
           f"The most frequent theme tags are {top_themes(themes, 3)}. Post text is not reproduced here; each archive entry links to the post.")]
    return {"name": name, "slug": slugify(name), "vertical": vertical, "posts": posts, "groups": groups,
            "themes": themes, "latest": latest, "earliest": earliest, "facts": facts, "capsule": capsule,
            "qa": qa, "sources": entry["sources"], "credits": credits, "words": words(capsule)}


def hub_model(key, spec, projects):
    members = [p for p in projects if any(set(r.get("categories") or []) & spec["cats"] for r in p["posts"])]
    posts = list({r["id"]: r for p in members for r in p["posts"]
                  if set(r.get("categories") or []) & spec["cats"]}.values())
    groups = collections.Counter(r["source"]["name"] for r in posts)
    themes = collections.Counter(t for r in posts for t in (r.get("categories") or []))
    latest = max((r["date"] for r in posts), default="")
    k, n, g = len(members), len(posts), len(groups)
    req = [f"The {spec['name']} hub lists {k} project{'s' if k != 1 else ''} with at least two linked community posts,",
           f"covering {n} posts from {g} group{'s' if g != 1 else ''}, latest {latest}.",
           f"Top recurring themes: {top_themes(themes, 2)}.",
           "Each project page gives register facts and links to the archive entries."]
    capsule = fit(req, [])
    qa = [("Which projects are in this hub?",
           "; ".join(p["name"] for p in members) + "." if members else "No project in this hub has at least two linked posts."),
          ("What are the main community themes in this hub?",
           f"The most frequent theme tags are {top_themes(themes, 3)}, from {n} archived public posts.")]
    return {"key": key, "spec": spec, "members": members, "posts": posts, "groups": groups, "themes": themes,
            "latest": latest, "capsule": capsule, "qa": qa, "words": words(capsule)}


def faq_ld(qa):
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in qa]}


def dataset_ld(name, desc, url, date, keywords):
    return {"@context": "https://schema.org", "@type": "Dataset", "name": name, "description": desc,
            "url": url, "dateModified": date, "keywords": keywords, "isAccessibleForFree": True,
            "creator": {"@type": "Organization", "name": "slava.it.com", "url": SITE_URL}}


def nav_html():
    return ('<nav><a href="/">Archive</a> · <a href="/pylons-grid/">Pylons and grid</a> · '
            '<a href="/data-centres/">Data centres</a> · <a href="/renewables-wind/">Wind, solar and storage</a></nav>')


def follow_html():
    return (f"{FOLLOW_MARK[0]}\n<aside class=\"seo-follow\" style=\"margin:1.5rem 0 0;font-size:.95em\" aria-label=\"Follow updates\"><p>Follow UK infrastructure updates: "
            f"<a href=\"/feed.xml\">RSS feed (newest {FEED_ITEMS} posts)</a> · <a href=\"/feeds/data-centres.xml\">data centres</a> · "
            "<a href=\"/feeds/pylons.xml\">pylons</a> · <a href=\"/feeds/wind.xml\">wind, solar and storage</a></p></aside>\n"
            f"{FOLLOW_MARK[1]}")


def credit_lines(p, srcs):
    """Credit entries for the licensed registers whose facts appear on the page: (text, licence, licence_url, source_url)."""
    out = []
    for sid in p["credits"]:
        m = srcs[sid]
        if "licence" not in m:
            continue
        copyright_ = f" (© {m['copyright']})" if m.get("copyright") else ""
        out.append((f"{m['attribution'].rstrip('.')}. Data: {m['name']}{copyright_}.", m["licence"], m["licence_url"], m["source_url"]))
    return out


def page(title, desc, canonical, body, lds):
    ld = "\n".join(f'<script type="application/ld+json">{jsonld(x)}</script>' for x in lds)
    return (
        '<!doctype html>\n<html lang="en-GB">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n<meta name=\"description\" content=\"{esc(desc)}\">\n"
        f"<link rel=\"canonical\" href=\"{esc(canonical)}\">\n"
        f"<link rel=\"alternate\" type=\"application/rss+xml\" title=\"slava.it.com\" href=\"{SITE_URL}/feed.xml\">\n"
        f"{ld}\n"
        "<style>body{font-family:system-ui,sans-serif;max-width:46rem;margin:0 auto;padding:1rem;line-height:1.5;color:#222;background:#faf7f2}"
        "table{border-collapse:collapse;width:100%;margin:.5rem 0}th,td{border:1px solid #d8cfc0;padding:.35rem .5rem;text-align:left;vertical-align:top}"
        "a{color:#a2421f}.seo-follow{margin:2rem 0 1rem;padding:.75rem 1rem;border:1px solid #d8cfc0;border-radius:6px}</style>\n"
        f"</head>\n<body>\n{nav_html()}\n<main>\n{body}\n</main>\n"
        "<footer><p>Facebook group posts are archived public posts. Register facts are labelled as reported or register. "
        "Post text is not reproduced.</p></footer>\n"
        f"{follow_html()}\n</body>\n</html>\n")


def project_html(p, srcs):
    rows = "".join(f"<tr><td>{esc(lab)}</td><td>{esc(v)}</td><td>{esc(b)}</td></tr>" for lab, v, b in p["facts"])
    facts_html = (f"<table><tr><th>Item</th><th>Value</th><th>Basis</th></tr>{rows}</table>" if rows
                  else "<p>No register facts are recorded for this project.</p>")
    src = "".join(f"<li><a href=\"{esc(u)}\">{esc(u)}</a></li>" for u in p["sources"])
    src_html = f"<h2>Sources for reported facts</h2><ul>{src}</ul>" if src else ""
    cl = credit_lines(p, srcs)
    credit_html = ""
    if cl:
        items = "".join(f"<li>{esc(t)} Licence: <a href=\"{esc(lu)}\">{esc(l)}</a>. Source: <a href=\"{esc(su)}\">{esc(su)}</a>.</li>"
                        for t, l, lu, su in cl)
        credit_html = (f"<h2>Data credits</h2><ul>{items}<li>Use of these registers does not imply endorsement "
                       "by their publishers.</li></ul>\n")
    grows = "".join(f"<tr><td>{esc(g)}</td><td>{n}</td></tr>" for g, n in p["groups"].most_common())
    trows = "".join(f"<tr><td>{esc(t)}</td><td>{n}</td></tr>" for t, n in p["themes"].most_common())
    entries = "".join(
        f"<li><a href=\"{SITE_URL}/?sel={r['id']}\">{esc(r['date'])}, {esc(r['source']['name'])}</a>"
        f" · themes: {esc(', '.join(r.get('categories') or []) or 'none tagged')}</li>" for r in p["posts"])
    qa_html = "".join(f"<h2>{esc(q)}</h2><p>{esc(a)}</p>" for q, a in p["qa"])
    body = (f"<h1>{esc(p['name'])}</h1>\n<p class=\"capsule\">{esc(p['capsule'])}</p>\n"
            f"<h2>Register facts</h2>\n{facts_html}\n{src_html}\n{credit_html}"
            f"<h2>Source groups</h2><table><tr><th>Group</th><th>Posts</th></tr>{grows}</table>\n"
            f"<h2>Theme breakdown</h2><table><tr><th>Theme</th><th>Posts</th></tr>{trows}</table>\n"
            f"{qa_html}\n<h2>Archive entries</h2><ul>{entries}</ul>\n<p><a href=\"/\">Back to the archive</a></p>")
    url = f"{SITE_URL}/projects/{p['slug']}.html"
    ds = dataset_ld(f"Community discussion archive: {p['name']}", p["capsule"], url, p["latest"], sorted(p["themes"]))
    return page(f"{p['name']} · community discussion archive", p["capsule"][:155], url, body, [ds, faq_ld(p["qa"])])


def project_md(p, srcs):
    f = "\n".join(f"| {lab} | {v.replace('|', '/')} | {b} |" for lab, v, b in p["facts"]) or "| none recorded | | |"
    g = "\n".join(f"| {x} | {n} |" for x, n in p["groups"].most_common())
    t = "\n".join(f"| {x} | {n} |" for x, n in p["themes"].most_common())
    e = "\n".join(f"- {r['date']}, {r['source']['name']}: {SITE_URL}/?sel={r['id']} (themes: {', '.join(r.get('categories') or []) or 'none tagged'})"
                  for r in p["posts"])
    qa = "\n\n".join(f"## {q}\n\n{a}" for q, a in p["qa"])
    cl = credit_lines(p, srcs)
    credit_md = ""
    if cl:
        credit_md = ("## Data credits\n\n" + "\n".join(f"- {t} Licence: [{l}]({lu}). Source: {su}." for t, l, lu, su in cl)
                     + "\n- Use of these registers does not imply endorsement by their publishers.\n\n")
    return (f"# {p['name']}\n\n{p['capsule']}\n\n## Register facts\n\n| Item | Value | Basis |\n|---|---|---|\n{f}\n\n"
            f"{credit_md}"
            f"## Source groups\n\n| Group | Posts |\n|---|---|\n{g}\n\n## Theme breakdown\n\n| Theme | Posts |\n|---|---|\n{t}\n\n"
            f"{qa}\n\n## Archive entries\n\n{e}\n\n---\nHTML version: {SITE_URL}/projects/{p['slug']}.html\n"
            "Archived public Facebook group posts; not independently verified. Post text is not reproduced.\n")


def hub_html(h):
    rows = "".join(
        f"<tr><td><a href=\"/projects/{p['slug']}.html\">{esc(p['name'])}</a></td><td>{len(p['posts'])}</td>"
        f"<td>{esc(p['latest'])}</td></tr>" for p in h["members"])
    trows = "".join(f"<tr><td>{esc(t)}</td><td>{n}</td></tr>" for t, n in h["themes"].most_common())
    qa_html = "".join(f"<h2>{esc(q)}</h2><p>{esc(a)}</p>" for q, a in h["qa"])
    body = (f"<h1>{esc(h['spec']['name'])}</h1>\n<p class=\"capsule\">{esc(h['capsule'])}</p>\n"
            f"<h2>Projects</h2><table><tr><th>Project</th><th>Posts</th><th>Latest</th></tr>{rows}</table>\n"
            f"<h2>Theme breakdown</h2><table><tr><th>Theme</th><th>Posts</th></tr>{trows}</table>\n{qa_html}")
    url = f"{SITE_URL}/{h['key']}/"
    return page(f"{h['spec']['name']} · community discussion archive", h["capsule"][:155], url, body,
                [dataset_ld(f"Community discussion archive: {h['spec']['name']}", h["capsule"], url, h["latest"],
                            sorted(h["themes"])), faq_ld(h["qa"])])


def hub_md(h):
    rows = "\n".join(f"- [{p['name']}]({SITE_URL}/projects/{p['slug']}.md): {len(p['posts'])} posts; latest {p['latest']}"
                     for p in h["members"])
    qa = "\n\n".join(f"## {q}\n\n{a}" for q, a in h["qa"])
    return f"# {h['spec']['name']}\n\n{h['capsule']}\n\n## Projects\n\n{rows}\n\n{qa}\n\nHTML version: {SITE_URL}/{h['key']}/\n"


def feed_xml(title, items, path, build_date):
    body = "".join(
        f"<item><title>{xesc(r['source']['name'])} post, {r['date']}</title>"
        f"<link>{SITE_URL}/?sel={r['id']}</link><guid isPermaLink=\"true\">{SITE_URL}/?sel={r['id']}</guid>"
        f"<pubDate>{rfc822(r['date'])}</pubDate>"
        f"<description>{xesc('Themes: ' + (', '.join(r.get('categories') or []) or 'none tagged') + '. Project: ' + (r.get('project') or 'not linked') + '. Post text is not reproduced.')}</description></item>\n"
        for r in items)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>\n'
            f"<title>{xesc(title)}</title><link>{SITE_URL}/</link>"
            "<description>Archived public UK infrastructure community posts (no post text).</description>\n"
            f"<lastBuildDate>{rfc822(build_date)}</lastBuildDate>\n"
            f'<atom:link href="{SITE_URL}/{path}" rel="self" type="application/rss+xml"/>\n{body}</channel>\n</rss>\n')


def build_files(site, build_date):
    all_recs = read_json(site, "data/discussions-index.json", {"records": []})["records"]
    recs = [r for r in all_recs if r["id"] not in BLOCKED_POST_IDS and r.get("date") and r.get("source")]
    facts_doc = load_public_facts(site)
    srcs, dc_names = facts_doc["sources"], set(facts_doc["data_centre_projects"])
    by_proj = collections.defaultdict(list)
    for r in recs:
        if r.get("project"):
            by_proj[r["project"]].append(r)
    linked = sorted(by_proj)
    page_names = [n for n in linked if len(by_proj[n]) >= 2]
    missing = [n for n in page_names if n not in facts_doc["projects"]]
    if missing:
        raise BuildError(f"{FACTS_REL} has no entry for {len(missing)} project page(s): " + "; ".join(missing[:10])
                         + (" ..." if len(missing) > 10 else "") + f". {EXPORT_HINT}")
    projects = [project_model(n, by_proj[n], facts_doc["projects"][n], dc_names) for n in page_names]
    slugs = [p["slug"] for p in projects]
    assert len(set(slugs)) == len(slugs), "project slug collision"
    hubs = {k: hub_model(k, s, projects) for k, s in HUBS.items()}
    newest = max(r["date"] for r in recs)
    total_groups = len({r["source"]["name"] for r in recs})
    vc = collections.Counter(vertical_of(n, by_proj[n], dc_names) for n in linked)
    F = {}
    for p in projects:
        F[f"projects/{p['slug']}.html"] = project_html(p, srcs)
        F[f"projects/{p['slug']}.md"] = project_md(p, srcs)
    for k, h in hubs.items():
        F[f"{k}/index.html"] = hub_html(h)
        F[f"{k}/index.md"] = hub_md(h)
    urls = [(f"{SITE_URL}/", newest)] + [(f"{SITE_URL}/{k}/", h["latest"]) for k, h in hubs.items()] + \
           [(f"{SITE_URL}/projects/{p['slug']}.html", p["latest"]) for p in projects]
    F["sitemap.xml"] = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                        + "".join(f"<url><loc>{xesc(u)}</loc><lastmod>{d}</lastmod></url>\n" for u, d in urls) + "</urlset>\n")
    F["robots.txt"] = ("".join(f"User-agent: {b}\nAllow: /\nDisallow: /briefs/\n\n" for b in BOTS)
                       + "User-agent: *\nAllow: /\nDisallow: /briefs/\n\n" + f"Sitemap: {SITE_URL}/sitemap.xml\n")
    desc = (f"{len(recs)} tracked public community posts from {total_groups} Facebook groups, linked to {len(linked)} UK projects "
            f"({vc['Wind, solar and storage']} wind, solar and storage; {vc['Pylons and grid']} pylons and grid; "
            f"{vc['AI data centre']} AI data centres). Posts are archived public group posts, not independently verified.")
    withheld = len(all_recs) - len(recs)
    note = ""
    if withheld:
        note = (f" The discussions index holds {len(all_recs):,} records; these pages cover {len(recs):,} because "
                f"{withheld} record{' is' if withheld == 1 else 's are'} excluded from them.")
    lines = ["# slava.it.com", "", f"> {desc}", "",
             f"Counts are generated from the discussions index on {build_date}. Projects with at least two linked posts have a page.{note}", "",
             "## Hubs"]
    for k, h in hubs.items():
        lines.append(f"- [{h['spec']['name']}]({SITE_URL}/{k}/index.md): {len(h['members'])} projects, {len(h['posts'])} posts; latest {h['latest']}")
    lines += ["", "## Projects"]
    for p in projects:
        lines.append(f"- [{p['name']}]({SITE_URL}/projects/{p['slug']}.md): {len(p['posts'])} posts from {len(p['groups'])} groups; "
                     f"latest {p['latest']}; {p['vertical'].lower()}.")
    lines += ["", "## Feeds", f"- [All posts feed]({SITE_URL}/feed.xml): newest {FEED_ITEMS} posts", "",
              "## Optional", f"- [Full text of hub and project pages]({SITE_URL}/llms-full.txt)", ""]
    F["llms.txt"] = "\n".join(lines)
    F["llms-full.txt"] = "\n\n---\n\n".join([F[f"projects/{p['slug']}.md"] for p in projects]
                                           + [F[f"{k}/index.md"] for k in hubs]) + "\n"
    ordered = sorted(recs, key=lambda r: (r["date"], r["id"]), reverse=True)
    F["feed.xml"] = feed_xml("slava.it.com: UK infrastructure community posts", ordered[:FEED_ITEMS], "feed.xml", build_date)
    for k, h in hubs.items():
        items = [r for r in ordered if set(r.get("categories") or []) & HUBS[k]["cats"]][:FEED_ITEMS]
        path = f"feeds/{HUBS[k]['feed']}.xml"
        F[path] = feed_xml(f"slava.it.com: {h['spec']['name']}", items, path, build_date)
    idx_html = open(os.path.join(site, "index.html"), encoding="utf-8").read()
    for a, b in (JSONLD_MARK, FOLLOW_MARK):
        idx_html = re.sub(re.escape(a) + r".*?" + re.escape(b) + r"\n?", "", idx_html, flags=re.S)
    site_ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": "slava.it.com", "url": f"{SITE_URL}/",
                "description": desc},
               dataset_ld("UK infrastructure community discussion archive", desc, f"{SITE_URL}/", build_date,
                          sorted({t for r in recs for t in (r.get("categories") or [])}))]
    jl = (f"{JSONLD_MARK[0]}\n" + "\n".join(f'<script type="application/ld+json">{jsonld(x)}</script>' for x in site_ld)
          + f"\n{JSONLD_MARK[1]}\n")
    idx_html = idx_html.replace("</head>", jl + "</head>", 1)
    # the follow bar sits inside the existing footer so it inherits the site's type and margins
    idx_html = idx_html.replace("</footer>", follow_html() + "\n</footer>", 1) if "</footer>" in idx_html \
        else idx_html.replace("</body>", follow_html() + "\n</body>", 1)
    F["index.html"] = idx_html
    key = read_json(site, "data/indexnow.json", {}).get("key") or uuid.uuid4().hex
    F[f"{key}.txt"] = key + "\n"
    F["data/indexnow.json"] = json.dumps({"key": key}, indent=1) + "\n"
    projects_dir = os.path.join(site, "projects")
    existing = set(os.listdir(projects_dir)) if os.path.isdir(projects_dir) else set()
    wanted = {f"{p['slug']}{ext}" for p in projects for ext in (".html", ".md")}
    stats = {"records": len(recs), "index_records": len(all_recs), "groups": total_groups, "linked_projects": len(linked),
             "project_pages": len(projects), "verticals": dict(vc),
             "hubs": {k: len(h["members"]) for k, h in hubs.items()}, "newest": newest, "key": key,
             "capsule_words": {p["slug"]: p["words"] for p in projects},
             "stale_project_files": sorted(existing - wanted)}
    return F, stats


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build SEO and GEO outputs for slava.it.com.")
    ap.add_argument("--site", default=SITE_DEFAULT)
    ap.add_argument("--build-date", default=datetime.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true", help="build in memory and print the checks; write nothing")
    a = ap.parse_args(argv)
    try:
        F, stats = build_files(a.site, a.build_date)
    except BuildError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    bad = {s: w for s, w in stats["capsule_words"].items() if not 40 <= w <= 60}
    print(json.dumps({k: v for k, v in stats.items() if k != "capsule_words"}, indent=1, ensure_ascii=False))
    print("capsules outside 40-60 words:", bad or "none")
    if a.dry_run:
        print("dry run: nothing written;", len(F), "files built")
        return 0
    if bad:
        print("error: refusing to write: fix capsule lengths first", file=sys.stderr)
        return 1
    for rel, text in F.items():
        path = os.path.join(a.site, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    for stale in stats["stale_project_files"]:
        os.remove(os.path.join(a.site, "projects", stale))
    print("wrote", len(F), "files; removed", len(stats["stale_project_files"]), "stale project files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
