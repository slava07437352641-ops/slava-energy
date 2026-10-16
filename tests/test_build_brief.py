"""Tests for scripts/build_brief.py and scripts/build_source_registry.py (synthetic records only)."""
import json, os, sys, tempfile, unittest

def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(obj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import build_brief as bb  # noqa: E402
import build_source_registry as br  # noqa: E402

SECRET_BODY = "Jane Doe of 12 Example Street objects to the turbine plan"
SECRET_TITLE = "Quoted headline that must not appear"


def rec(i, date, src, project="Test Wind Farm", **extra):
    r = {"id": i, "date": date, "title": SECRET_TITLE, "bodyText": SECRET_BODY, "summary": SECRET_BODY,
         "provenance": {"title": {"method": "headline"}}, "source": {"type": "facebook_group", "name": src,
         "label": "Facebook · " + src, "url": "https://www.facebook.com/groups/example/"},
         "project": project, "developer": "Example Energy", "authority": "Highland Council",
         "location": "Near Testville", "developmentStatus": "Consented",
         "categories": ["Onshore Wind"], "topics": ["Planning / process"]}
    r.update(extra)
    return r


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.recs = [rec("1", "2026-10-01", "Group A"), rec("2", "2026-10-05", "Group A"),
                     rec("3", "2026-10-07", "Group B"), rec("4", "2026-10-07", "Group C")]
        self.eligible = {"Group A", "Group B"}

    def test_only_eligible_sources_are_used(self):
        chosen, excluded = bb.select(self.recs, "Test Wind Farm", self.eligible)
        self.assertEqual({r["id"] for r in chosen}, {"1", "2", "3"})
        self.assertEqual(excluded["Group C"], 1)

    def test_blocked_post_is_left_out(self):
        blocked = next(iter(bb.BLOCKED_POST_IDS))
        recs = self.recs + [rec(blocked, "2026-10-08", "Group A")]
        chosen, _ = bb.select(recs, "Test Wind Farm", self.eligible)
        self.assertNotIn(blocked, {r["id"] for r in chosen})

    def test_output_has_no_post_text_or_title(self):
        chosen, excluded = bb.select(self.recs, "Test Wind Farm", self.eligible)
        out = bb.render("Test Wind Farm", chosen, excluded, {}, "2026-10-16")
        self.assertNotIn("Jane Doe", out)
        self.assertNotIn("Example Street", out)
        self.assertNotIn(SECRET_TITLE, out)
        self.assertNotIn("objects to the turbine", out)

    def test_output_is_noindex_and_counts_per_group(self):
        chosen, excluded = bb.select(self.recs, "Test Wind Farm", self.eligible)
        out = bb.render("Test Wind Farm", chosen, excluded, {}, "2026-10-16")
        self.assertIn('content="noindex,nofollow"', out)
        self.assertIn("<td>Group A</td><td>2</td>", out)
        self.assertIn("https://slava.it.com/?sel=1", out)

    def test_project_with_no_eligible_posts_says_so(self):
        chosen, excluded = bb.select(self.recs, "Unknown Project", self.eligible)
        out = bb.render("Unknown Project", chosen, excluded, {}, "2026-10-16")
        self.assertIn("No posts from cleared sources", out)

    def test_themes_are_tags_only(self):
        chosen, _ = bb.select(self.recs, "Test Wind Farm", self.eligible)
        tags = dict(bb.themes(chosen))
        self.assertEqual(tags.get("Onshore Wind"), 3)
        self.assertEqual(tags.get("Planning / process"), 3)


class RegistryTests(unittest.TestCase):
    def test_gate_requires_public_active_and_mapped(self):
        with tempfile.TemporaryDirectory() as d:
            disc = os.path.join(d, "disc.json"); audit = os.path.join(d, "audit.json")
            json.dump({"records": [rec("1", "2026-10-15", "Public Active Mapped"),
                                   rec("2", "2026-08-01", "Public Stale Mapped"),
                                   rec("3", "2026-10-15", "Active Unmapped", project=None),
                                   rec("4", "2026-10-15", "Public Active Mapped 2", project=None)]}, open(disc, "w"))
            json.dump({"rows": [{"group": "Public Active Mapped"}, {"group": "Public Stale Mapped"},
                                {"group": "Active Unmapped"}]}, open(audit, "w"))
            rows = {r["name"]: r for r in br.build(disc, audit)}
            self.assertTrue(rows["Public Active Mapped"]["brief_eligible"])
            self.assertFalse(rows["Public Stale Mapped"]["brief_eligible"])
            self.assertFalse(rows["Active Unmapped"]["brief_eligible"])
            self.assertFalse(rows["Public Active Mapped 2"]["brief_eligible"])


if __name__ == "__main__":
    unittest.main()
