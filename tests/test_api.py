"""API tests for Plain-Speak Forge."""
import json
import os
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

TMP = tempfile.mkdtemp()
os.environ["PLAIN_SPEAK_DB"] = os.path.join(TMP, "test.sqlite3")

import app as appmod  # noqa: E402
import db  # noqa: E402

db.init_db()
client = appmod.app.test_client()

TEXT = (
    "# Reset your password\n\n"
    "Your password reset link works once and it expires after 30 minutes.\n\n"
    "## Steps\n\n"
    "1. Open the email we sent you.\n"
    "2. Click Reset password.\n"
    "3. Type a new password with at least 12 characters.\n"
    "4. Click Save and you will be signed out on every device.\n\n"
    "If the link does not work, check your spam folder and ask your admin for help."
)


class TestApi(unittest.TestCase):
    def test_health(self):
        res = client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])

    def test_index(self):
        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Plain-Speak", res.data)

    def test_audiences(self):
        data = client.get("/api/audiences").get_json()
        self.assertGreaterEqual(len(data["audiences"]), 6)
        self.assertIn("general_public", [a["key"] for a in data["audiences"]])

    def test_samples_list(self):
        data = client.get("/api/samples").get_json()
        self.assertGreaterEqual(len(data["samples"]), 6)

    def test_sample_fetch(self):
        data = client.get("/api/sample/insurance_notice").get_json()
        self.assertIn("text", data)
        self.assertEqual(data["audience"], "consumer_notice")

    def test_sample_missing(self):
        res = client.get("/api/sample/nope")
        self.assertEqual(res.status_code, 404)

    def test_analyze(self):
        res = client.post("/api/analyze", json={"text": TEXT, "audience": "support_article", "title": "t"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertGreater(data["score"], 0)
        self.assertIn("session_id", data)

    def test_analyze_empty(self):
        res = client.post("/api/analyze", json={"text": "  "})
        self.assertEqual(res.status_code, 400)

    def test_analyze_too_short(self):
        res = client.post("/api/analyze", json={"text": "hi"})
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.get_json()["error"], "too_short")

    def test_sessions_roundtrip(self):
        res = client.post("/api/analyze", json={"text": TEXT, "title": "round trip"})
        sid = res.get_json()["session_id"]
        rows = client.get("/api/sessions").get_json()["sessions"]
        self.assertTrue(any(r["id"] == sid for r in rows))
        detail = client.get("/api/sessions/%d" % sid).get_json()
        self.assertEqual(detail["title"], "round trip")
        patched = client.patch("/api/sessions/%d" % sid, json={"self_rating": 4, "notes": "good"})
        self.assertEqual(patched.get_json()["self_rating"], 4)
        self.assertEqual(patched.get_json()["notes"], "good")
        again = client.get("/api/sessions/%d" % sid).get_json()
        self.assertEqual(again["self_rating"], 4)

    def test_session_missing(self):
        self.assertEqual(client.get("/api/sessions/99999").status_code, 404)

    def test_export_markdown(self):
        sid = client.post("/api/analyze", json={"text": TEXT, "title": "export me"}).get_json()["session_id"]
        res = client.get("/api/export/%d?fmt=md" % sid)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Plain-Speak report", res.data)
        self.assertIn("attachment", res.headers["Content-Disposition"])

    def test_export_json(self):
        sid = client.post("/api/analyze", json={"text": TEXT, "title": "export json"}).get_json()["session_id"]
        res = client.get("/api/export/%d?fmt=json" % sid)
        payload = json.loads(res.data.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertIn("findings", payload)

    def test_frontend_contract(self):
        res = client.post("/api/analyze", json={"text": TEXT, "audience": "general_public"})
        data = res.get_json()
        for key in ["score", "verdict", "verdict_label", "axes", "metrics", "levels", "stats",
                    "findings", "jargon", "acronyms", "inclusive", "structure", "hotspots",
                    "paragraph_map", "fix_plan", "rewrites", "cleaned_draft",
                    "cleaned_substitutions", "caps"]:
            self.assertIn(key, data, key)
        for axis in data["axes"].values():
            for key in ["label", "score", "weight"]:
                self.assertIn(key, axis)
        for f in data["findings"]:
            for key in ["id", "axis", "severity", "title", "why", "fix"]:
                self.assertIn(key, f)


if __name__ == "__main__":
    unittest.main(verbosity=2)
