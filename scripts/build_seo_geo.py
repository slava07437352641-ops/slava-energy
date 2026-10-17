#!/usr/bin/env python3
"""Build the search and AI-readable outputs for slava.it.com from data/discussions-index.json.

Writes static files at the site root (overwritten on each run): robots.txt, sitemap.xml, llms.txt,
llms-full.txt, feed.xml, feeds/{data-centres,pylons,wind}.xml, projects/<slug>.html and .md for every project
with at least two linked posts, pylons-grid/, data-centres/ and renewables-wind/ (index.html and index.md),
<indexnow-key>.txt, and two marker blocks in index.html (JSON-LD and the follow bar). No network access.

Privacy: outputs never contain post text, post titles or author names. They contain group names, dates,
counts, theme tags, register facts (labelled as reported or register) and links to the archive entries
(?sel=<id>). Blocked post IDs are dropped everywhere.

Usage: python3 scripts/build_seo_geo.py [--dry-run] [--build-date YYYY-MM-DD] [--site DIR] [--objects-db PATH]
"""
import argparse, ast, collections, datetime, html, json, os, re, sqlite3, sys, uuid
from email.utils import format_datetime
from xml.sax.saxutils import escape as xesc

SITE_URL = "https://slava.it.com"
SITE_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBJECTS_DEFAULT = os.path.expanduser("~/dev/uk-project-post-map_v3.3/data/objects/objects.sqlite")

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
JSONLD_MARK = ("<!-- seo-geo:jsonld:start -->", "<!-- seo-geo:jsonld:end -->")
FOLLOW_MARK = ("<!-- seo-geo:follow:start -->", "<!-- seo-geo:follow:end -->")
FEED_ITEMS = 50


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


def as_list(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip().startswith("["):
        try:
            return list(ast.literal_eval(v))
        except (ValueError, SyntaxError):
            return []
    return []


def read_json(site, rel, default):
    p = os.path.join(site, rel)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def load_registers(path):
    repd, tec = collections.defaultdict(list), collections.defaultdict(list)
    if not path or not os.path.exists(path):
        return repd, tec
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    for ref, name, status, tech in con.execute("select ref_id, name, status, technology from repd_record"):
        repd[norm(name)].append({"ref": ref, "status": status, "technology": tech})
    for name, status, pref, auth in con.execute(
            "select project_name, project_status, planning_reference, planning_authority from tec_project"):
        tec[norm(name)].append({"status": status, "planning_reference": pref, "authority": auth})
    return repd, tec


def register_facts(name, dc, corr, repd, tec):
    """Facts as (label, value, basis). Basis is 'reported' for press, developer or council claims, 'register' for registers."""
    facts = []
    d = dc.get(name)
    if d:
        for lab, key in [("Planning reference", "application_ref"), ("Application type", "application_type"),
                         ("Status", "status_reported"), ("Developer", "developer_reported"),
                         ("Council", "council"), ("Capacity", "capacity_reported")]:
            if d.get(key):
                facts.append((lab, d[key], "reported"))
    c = corr.get(name)
    if c:
        for lab, key in [("Consent or stage", "consent"), ("Operator", "operator"), ("Kind", "kind")]:
            if c.get(key):
                facts.append((lab, c[key], "reported"))
    n = norm(name)
    if len(repd.get(n, [])) > 1:
        facts.append(("REPD rows with this name", str(len(repd[n])), "register"))
    if len(tec.get(n, [])) > 1:
        facts.append(("TEC rows with this name", str(len(tec[n])), "register"))
    for row in repd.get(n, [])[:1]:
        facts += [("REPD reference", row["ref"], "register"), ("REPD status", row["status"], "register")]
    for row in tec.get(n, [])[:1]:
        if row["planning_reference"]:
            facts.append(("Planning reference (TEC)", row["planning_reference"], "register"))
        if row["status"]:
            facts.append(("TEC project status", row["status"], "register"))
    return facts


def sources_for(name, dc, corr):
    urls = []
    if name in dc:
        urls += as_list(dc[name].get("sources"))
    if name in corr and corr[name].get("source"):
        urls.append(corr[name]["source"])
    return [u for u in dict.fromkeys(urls) if str(u).startswith("https://")]


def top_themes(counter, k):
    return ", ".join(f"{t} ({n})" for t, n in counter.most_common(k)) or "none tagged"


def fit(required, optional, hi=60):
    opt = list(optional)
    text = " ".join(required + opt)
    while words(text) > hi and opt:
        opt.pop()
        text = " ".join(required + opt)
    return text


def is_data_centre(name, posts, dc):
    return name in dc or sum("Data Centre" in (r.get("categories") or []) for r in posts) * 2 >= len(posts)


def is_ohl(posts):
    return sum(bool({"OHL (Pylons)", "Substation"} & set(r.get("categories") or [])) for r in posts) * 2 >= len(posts)


def vertical_of(name, posts, dc):
    if is_data_centre(name, posts, dc):
        return "AI data centre"
    return "Pylons and grid" if is_ohl(posts) else "Wind, solar and storage"


VERTICAL_PHRASE = {"AI data centre": "an AI data centre project", "Pylons and grid": "a pylons and grid project",
                   "Wind, solar and storage": "a wind, solar and storage project"}


def project_model(name, posts, dc, corr, repd, tec):
    posts = sorted(posts, key=lambda r: (r["date"], r["id"]), reverse=True)
    groups = collections.Counter(r["source"]["name"] for r in posts)
    themes = collections.Counter(t for r in posts for t in (r.get("categories") or []))
    latest, earliest = posts[0]["date"], posts[-1]["date"]
    n, g = len(posts), len(groups)
    vertical = vertical_of(name, posts, dc)
    facts = register_facts(name, dc, corr, repd, tec)
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
            "qa": qa, "sources": sources_for(name, dc, corr), "words": words(capsule)}


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


def project_html(p):
    rows = "".join(f"<tr><td>{esc(lab)}</td><td>{esc(v)}</td><td>{esc(b)}</td></tr>" for lab, v, b in p["facts"])
    facts_html = (f"<table><tr><th>Item</th><th>Value</th><th>Basis</th></tr>{rows}</table>" if rows
                  else "<p>No register facts are recorded for this project.</p>")
    src = "".join(f"<li><a href=\"{esc(u)}\">{esc(u)}</a></li>" for u in p["sources"])
    src_html = f"<h2>Sources for reported facts</h2><ul>{src}</ul>" if src else ""
    grows = "".join(f"<tr><td>{esc(g)}</td><td>{n}</td></tr>" for g, n in p["groups"].most_common())
    trows = "".join(f"<tr><td>{esc(t)}</td><td>{n}</td></tr>" for t, n in p["themes"].most_common())
    entries = "".join(
        f"<li><a href=\"{SITE_URL}/?sel={r['id']}\">{esc(r['date'])}, {esc(r['source']['name'])}</a>"
        f" · themes: {esc(', '.join(r.get('categories') or []) or 'none tagged')}</li>" for r in p["posts"])
    qa_html = "".join(f"<h2>{esc(q)}</h2><p>{esc(a)}</p>" for q, a in p["qa"])
    body = (f"<h1>{esc(p['name'])}</h1>\n<p class=\"capsule\">{esc(p['capsule'])}</p>\n"
            f"<h2>Register facts</h2>\n{facts_html}\n{src_html}\n"
            f"<h2>Source groups</h2><table><tr><th>Group</th><th>Posts</th></tr>{grows}</table>\n"
            f"<h2>Theme breakdown</h2><table><tr><th>Theme</th><th>Posts</th></tr>{trows}</table>\n"
            f"{qa_html}\n<h2>Archive entries</h2><ul>{entries}</ul>\n<p><a href=\"/\">Back to the archive</a></p>")
    url = f"{SITE_URL}/projects/{p['slug']}.html"
    ds = dataset_ld(f"Community discussion archive: {p['name']}", p["capsule"], url, p["latest"], sorted(p["themes"]))
    return page(f"{p['name']} · community discussion archive", p["capsule"][:155], url, body, [ds, faq_ld(p["qa"])])


def project_md(p):
    f = "\n".join(f"| {lab} | {v.replace('|', '/')} | {b} |" for lab, v, b in p["facts"]) or "| none recorded | | |"
    g = "\n".join(f"| {x} | {n} |" for x, n in p["groups"].most_common())
    t = "\n".join(f"| {x} | {n} |" for x, n in p["themes"].most_common())
    e = "\n".join(f"- {r['date']}, {r['source']['name']}: {SITE_URL}/?sel={r['id']} (themes: {', '.join(r.get('categories') or []) or 'none tagged'})"
                  for r in p["posts"])
    qa = "\n\n".join(f"## {q}\n\n{a}" for q, a in p["qa"])
    return (f"# {p['name']}\n\n{p['capsule']}\n\n## Register facts\n\n| Item | Value | Basis |\n|---|---|---|\n{f}\n\n"
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


def build_files(site, objects_db, build_date):
    for rel in ("data/data_centre_register.json", "data/grid_corridor_supplement.json"):
        if not os.path.exists(os.path.join(site, rel)):
            print(f"warning: {rel} not found; its register facts are omitted from the pages", file=sys.stderr)
    recs = [r for r in read_json(site, "data/discussions-index.json", {"records": []})["records"]
            if r["id"] not in BLOCKED_POST_IDS and r.get("date") and r.get("source")]
    dc = {p["name"]: p for p in read_json(site, "data/data_centre_register.json", {"projects": []})["projects"]}
    corr = {c["name"]: c for c in read_json(site, "data/grid_corridor_supplement.json", {"corridors": []})["corridors"]}
    repd, tec = load_registers(objects_db)
    by_proj = collections.defaultdict(list)
    for r in recs:
        if r.get("project"):
            by_proj[r["project"]].append(r)
    linked = sorted(by_proj)
    projects = [project_model(n, by_proj[n], dc, corr, repd, tec) for n in linked if len(by_proj[n]) >= 2]
    slugs = [p["slug"] for p in projects]
    assert len(set(slugs)) == len(slugs), "project slug collision"
    hubs = {k: hub_model(k, s, projects) for k, s in HUBS.items()}
    newest = max(r["date"] for r in recs)
    total_groups = len({r["source"]["name"] for r in recs})
    vc = collections.Counter(vertical_of(n, by_proj[n], dc) for n in linked)
    F = {}
    for p in projects:
        F[f"projects/{p['slug']}.html"] = project_html(p)
        F[f"projects/{p['slug']}.md"] = project_md(p)
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
    lines = ["# slava.it.com", "", f"> {desc}", "",
             f"Counts are generated from the discussions index on {build_date}. Projects with at least two linked posts have a page.", "",
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
    stats = {"records": len(recs), "groups": total_groups, "linked_projects": len(linked),
             "project_pages": len(projects), "verticals": dict(vc),
             "hubs": {k: len(h["members"]) for k, h in hubs.items()}, "newest": newest, "key": key,
             "capsule_words": {p["slug"]: p["words"] for p in projects},
             "stale_project_files": sorted(existing - wanted)}
    return F, stats


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build SEO and GEO outputs for slava.it.com.")
    ap.add_argument("--site", default=SITE_DEFAULT)
    ap.add_argument("--objects-db", default=os.environ.get("SEO_OBJECTS_DB", OBJECTS_DEFAULT))
    ap.add_argument("--build-date", default=datetime.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true", help="build in memory and print the checks; write nothing")
    a = ap.parse_args(argv)
    F, stats = build_files(a.site, a.objects_db, a.build_date)
    bad = {s: w for s, w in stats["capsule_words"].items() if not 40 <= w <= 60}
    print(json.dumps({k: v for k, v in stats.items() if k != "capsule_words"}, indent=1, ensure_ascii=False))
    print("capsules outside 40-60 words:", bad or "none")
    if a.dry_run:
        print("dry run: nothing written;", len(F), "files built")
        return 0
    if bad:
        print("refusing to write: fix capsule lengths first", file=sys.stderr)
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
