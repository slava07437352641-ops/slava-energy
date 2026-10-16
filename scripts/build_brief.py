"""Build a Community Intelligence Brief for one project (prototype, Option A).

Output: briefs/<slug>.html, noindex, not linked from index.html.
The brief reads only: project metadata (project, developer, authority, location,
developmentStatus), group names, dates, counts, theme tags (categories, topics)
and the on-site permalink of each post. It never reads bodyText, title,
summary, provenance or externalSource, so no post text or personal name can reach it.
A source is used only when data/source-registry.json marks it brief_eligible.
"""
import argparse, html, json, os, re, sys, collections

def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(obj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISC = os.path.join(ROOT, "data", "discussions-index.json")
REG = os.path.join(ROOT, "data", "source-registry.json")
OUTDIR = os.path.join(ROOT, "briefs")
SITE = "https://slava.it.com"
# Post ids the user ordered removed: never included (see memory: slava.energy blocked posts).
BLOCKED_POST_IDS = {"29510992631836418", "1814323132941267", "1814270869613160",
                    "1098654185897696", "1813753316331582", "29488742940728054",
                    "1828353354871578"}  # removed from slava.it.com 16 Oct (private landowner dispute)
META_FIELDS = ("project", "developer", "authority", "location", "developmentStatus")


def load(path):
    return _read_json(path)


def source_name(rec):
    import ast
    s = rec.get("source")
    if isinstance(s, dict):
        return s.get("name") or ""
    try:
        return (ast.literal_eval(s) or {}).get("name") or ""
    except Exception:
        return str(s)


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"


def projects(records):
    """Project names as stored, with post counts, for choosing a brief."""
    c = collections.Counter(str(r["project"]) for r in records if r.get("project") and str(r["project"]) not in ("None", "{}", "[]"))
    return c.most_common()


def select(records, project, eligible):
    """Records for this project from eligible sources only; returns (chosen, excluded_by_source)."""
    chosen, excluded = [], collections.Counter()
    for r in records:
        if str(r.get("project") or "") != project:
            continue
        if r.get("id") in BLOCKED_POST_IDS:
            continue
        src = source_name(r)
        if src not in eligible:
            excluded[src or "(no source)"] += 1
            continue
        chosen.append(r)
    chosen.sort(key=lambda r: r.get("date") or "", reverse=True)
    return chosen, excluded


def group_rows(chosen):
    g = collections.OrderedDict()
    for r in chosen:
        src = source_name(r)
        d = r.get("date") or ""
        row = g.setdefault(src, {"posts": 0, "first": d, "last": d})
        row["posts"] += 1
        row["first"] = min(row["first"], d) if row["first"] else d
        row["last"] = max(row["last"], d)
    return g


def themes(chosen):
    t = collections.Counter()
    for r in chosen:
        for key in ("categories", "topics"):
            v = r.get(key)
            if isinstance(v, str):
                try:
                    import ast
                    v = ast.literal_eval(v)
                except Exception:
                    v = [v]
            for tag in v or []:
                t[str(tag)] += 1
    return t.most_common()


def render(project, chosen, excluded, reg_by_name, generated):
    esc = html.escape
    meta = {k: (chosen[0].get(k) if chosen else None) for k in META_FIELDS}
    rows = group_rows(chosen)
    parts = []
    parts.append('<!doctype html><html lang="en-GB"><head><meta charset="utf-8">'
                 '<meta name="viewport" content="width=device-width,initial-scale=1">'
                 '<meta name="robots" content="noindex,nofollow">'
                 f'<title>Community brief: {esc(project)}</title>'
                 '<style>:root{--ink:#1d1b18;--muted:#6b655c;--line:#d9d2c3;--bg:#faf7f0;--accent:#c85a32}'
                 '@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--ink:#f1ece0;--muted:#a79f91;--line:#3a362f;--bg:#161513;--accent:#e07a52}}'
                 'body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}'
                 'main{max-width:760px;margin:0 auto;padding:24px 16px}h1{font-size:1.5rem;margin:0 0 4px}'
                 'h2{font-size:1.05rem;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}'
                 'table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:6px 4px;border-bottom:1px solid var(--line)}'
                 '.muted{color:var(--muted)}.chip{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:2px 10px;margin:2px 4px 2px 0;font-size:.9rem}'
                 'a{color:var(--accent)}</style></head><body><main>')
    parts.append(f'<h1>{esc(project)}</h1>')
    facts = [("Developer", meta.get("developer")), ("Authority", meta.get("authority")),
             ("Location", meta.get("location")), ("Status", meta.get("developmentStatus"))]
    parts.append('<p class="muted">' + " · ".join(f"{k}: {esc(str(v))}" for k, v in facts if v) + '</p>')
    if not chosen:
        parts.append('<h2>Community discussion</h2><p>No posts from cleared sources are linked to this project yet.</p>')
    else:
        parts.append('<h2>Groups</h2><table><tr><th>Group</th><th>Posts</th><th>First</th><th>Last</th></tr>')
        for src, row in rows.items():
            parts.append(f'<tr><td>{esc(src)}</td><td>{row["posts"]}</td><td>{esc(row["first"])}</td><td>{esc(row["last"])}</td></tr>')
        parts.append('</table>')
        th = themes(chosen)
        if th:
            parts.append('<h2>Themes</h2><p>' + "".join(f'<span class="chip">{esc(t)} · {n}</span>' for t, n in th) + '</p>')
        parts.append('<h2>Posts</h2><ul>')
        for r in chosen:
            parts.append(f'<li>{esc(r.get("date") or "")} · {esc(source_name(r))} · <a href="{SITE}/?sel={esc(str(r["id"]))}">view on slava.it.com</a></li>')
        parts.append('</ul>')
    if excluded:
        parts.append('<h2>Not included</h2><p class="muted">' + "; ".join(f'{esc(s)}: {n} post(s) from sources not yet cleared' for s, n in excluded.items()) + '</p>')
    parts.append(f'<p class="muted">Built {esc(generated)} from public posts. Counts, dates, tags and links only: '
                 'no post text and no personal names. Not for public navigation.</p>')
    parts.append('</main></body></html>')
    return "".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", help="project name as stored in the records")
    ap.add_argument("--list", action="store_true", help="list projects with linked posts")
    ap.add_argument("--date", default="2026-10-16", help="build date shown on the brief")
    a = ap.parse_args(argv)
    recs = load(DISC)["records"]
    if a.list:
        for name, n in projects(recs):
            print(f"{n:4d}  {name}")
        return 0
    if not a.project:
        ap.error("--project is required (or use --list)")
    reg = load(REG)
    eligible = {s["name"] for s in reg["sources"] if s["brief_eligible"]}
    chosen, excluded = select(recs, a.project, eligible)
    os.makedirs(OUTDIR, exist_ok=True)
    out = os.path.join(OUTDIR, slugify(a.project) + ".html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(a.project, chosen, excluded, {s["name"]: s for s in reg["sources"]}, a.date))
    print(f"brief: {out} | posts used {len(chosen)} | excluded {sum(excluded.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
