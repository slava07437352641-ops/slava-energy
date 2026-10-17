#!/usr/bin/env python3
"""Send new and modified URLs from sitemap.xml to IndexNow (api.indexnow.org).

Default is a dry run: it lists the URLs that would be sent and contacts nothing.
Sending needs BOTH --send and --confirmed-main-publish (use it only after the push to main is live).
A URL counts as new or modified when its sitemap lastmod differs from the value recorded in
data/indexnow-state.json. The state file is written only after IndexNow accepts the batch.

Usage:
  python3 scripts/ping_indexnow.py                                  # dry run
  python3 scripts/ping_indexnow.py --send --confirmed-main-publish  # after main is confirmed live
"""
import argparse, json, os, sys, urllib.error, urllib.request
import xml.etree.ElementTree as ET

HOST = "slava.it.com"
ENDPOINT = "https://api.indexnow.org/indexnow"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_BATCH = 10000


def load_sitemap(root):
    urls = {}
    for u in ET.parse(os.path.join(root, "sitemap.xml")).getroot().findall("s:url", NS):
        urls[u.find("s:loc", NS).text] = u.find("s:lastmod", NS).text
    return urls


def pending(urls, state):
    return sorted(u for u, d in urls.items() if state.get(u) != d)


def main(argv=None):
    ap = argparse.ArgumentParser(description="IndexNow ping for new and modified slava.it.com URLs.")
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--confirmed-main-publish", action="store_true",
                    help="required with --send: confirms the push to main is live")
    a = ap.parse_args(argv)
    urls = load_sitemap(a.root)
    state_path = os.path.join(a.root, "data", "indexnow-state.json")
    state = json.load(open(state_path, encoding="utf-8")) if os.path.exists(state_path) else {}
    key = json.load(open(os.path.join(a.root, "data", "indexnow.json"), encoding="utf-8"))["key"]
    todo = pending(urls, state)[:MAX_BATCH]
    print(f"sitemap URLs: {len(urls)}; new or modified: {len(todo)}")
    for u in todo[:15]:
        print("  ", u, urls[u])
    if len(todo) > 15:
        print("   ...")
    if not (a.send and a.confirmed_main_publish):
        print("dry run: nothing sent. Add --send --confirmed-main-publish after the main publish is live.")
        return 0
    if not todo:
        print("nothing to send")
        return 0
    body = json.dumps({"host": HOST, "key": key, "keyLocation": f"https://{HOST}/{key}.txt", "urlList": todo}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        print("IndexNow refused the batch:", e.code, e.reason, file=sys.stderr)
        return 1
    if status not in (200, 202):
        print("unexpected status", status, file=sys.stderr)
        return 1
    state.update({u: urls[u] for u in todo})
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
    print("sent", len(todo), "URLs; status", status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
