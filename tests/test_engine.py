"""Engine tests for Plain-Speak Forge."""
import json
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import engine  # noqa: E402

SAMPLES = os.path.join(BASE, "samples")

CLEAN = """\n# Reset your password\n\nYour password reset link works once. It expires 30 minutes after we send it.\n\n## Steps\n\n1. Open the email we sent you.\n2. Click Reset password.\n3. Type a new password. Use at least 12 characters.\n4. Click Save.\n\nYou will be signed out on every device when the password changes.\n\n## If the link does not work\n\nCheck your spam folder. If the email is not there, request a new link from the sign-in page.\n\nIf you still cannot sign in, ask your workspace admin to reset it for you.\n"""

LEGAL = """\n# Important Notice\n\nPursuant to Section 7(b) of the Agreement, the Company shall notify the insured of the\ncommencement of the implementation of the utilization of revised premium rates, as the same\nmay be amended from time to time at the sole discretion of the Company without prejudice to\nany other rights, remedies, or obligations available under the terms of this policy,\nnotwithstanding anything to the contrary set forth herein.\n"""


def load_sample(key):
    with open(os.path.join(SAMPLES, key + ".md"), encoding="utf-8") as fh:
        return fh.read()


class TestSyllables(unittest.TestCase):
    def test_short_words(self):
        self.assertEqual(engine.count_syllables("cat"), 1)
        self.assertEqual(engine.count_syllables("apple"), 2)
        self.assertEqual(engine.count_syllables("banana"), 3)

    def test_silent_e(self):
        self.assertEqual(engine.count_syllables("table"), 2)
        self.assertEqual(engine.count_syllables("make"), 1)

    def test_empty(self):
        self.assertEqual(engine.count_syllables(""), 0)


class TestSentenceSplit(unittest.TestCase):
    def test_basic(self):
        out = engine.split_sentences("One. Two. Three.")
        self.assertEqual(len(out), 3)

    def test_abbreviation(self):
        out = engine.split_sentences("Dr. Smith went home. He slept.")
        self.assertEqual(len(out), 2)
        self.assertIn("Dr. Smith went home", out[0])

    def test_decimal(self):
        out = engine.split_sentences("It costs 3.50 dollars today.")
        self.assertEqual(len(out), 1)

    def test_ends_without_period(self):
        out = engine.split_sentences("No terminal punctuation here")
        self.assertEqual(len(out), 1)


class TestBlocks(unittest.TestCase):
    def test_headings_lists_paragraphs(self):
        blocks = engine.parse_blocks("# Title\n\nPara one here.\n\n- a\n- b")
        kinds = [b["kind"] for b in blocks]
        self.assertIn("heading", kinds)
        self.assertIn("paragraph", kinds)
        self.assertIn("list_item", kinds)

    def test_setext_heading(self):
        blocks = engine.parse_blocks("Title\n=====\n\nBody text.")
        self.assertEqual(blocks[0]["kind"], "heading")
        self.assertEqual(blocks[0]["level"], 1)

    def test_code_block_skipped_from_prose(self):
        blocks = engine.parse_blocks("Text here.\n\n" + chr(96) * 3 + "\ncode line\n" + chr(96) * 3)
        self.assertTrue(any(b["kind"] == "code" for b in blocks))


class TestAnalyze(unittest.TestCase):
    def test_too_short(self):
        r = engine.analyze("Too short.")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "too_short")

    def test_clean_document_scores_high(self):
        r = engine.analyze(CLEAN, "support_article", "clean")
        self.assertTrue(r["ok"])
        self.assertGreaterEqual(r["score"], 85)
        self.assertEqual(r["verdict"], "plain_language_ready")

    def test_legalese_scores_low(self):
        r = engine.analyze(LEGAL, "consumer_notice", "legal")
        self.assertTrue(r["ok"])
        self.assertLess(r["score"], 60)
        self.assertIn(r["verdict"], ("hard_to_read", "needs_rework"))

    def test_audience_changes_the_score(self):
        general = engine.analyze(LEGAL, "general_public", "x")
        tech = engine.analyze(LEGAL, "technical_docs", "x")
        self.assertGreater(tech["score"], general["score"])

    def test_axes_present(self):
        r = engine.analyze(CLEAN, "support_article")
        for axis in engine.AXIS_ORDER:
            self.assertIn(axis, r["axes"])
            self.assertGreaterEqual(r["axes"][axis]["score"], 0)
            self.assertLessEqual(r["axes"][axis]["score"], 100)

    def test_findings_carry_evidence_and_fix(self):
        r = engine.analyze(LEGAL, "consumer_notice")
        self.assertTrue(r["findings"])
        for f in r["findings"]:
            self.assertIn(f["axis"], engine.AXIS_ORDER)
            self.assertIn(f["severity"], ("critical", "high", "medium", "low"))
            self.assertTrue(f["fix"])
            self.assertTrue(f["why"])

    def test_fix_plan_is_ordered(self):
        r = engine.analyze(LEGAL, "consumer_notice")
        prios = [p["priority"] for p in r["fix_plan"]]
        self.assertEqual(prios, sorted(prios))
        self.assertEqual(prios[0], 1)

    def test_stats(self):
        r = engine.analyze(CLEAN, "support_article")
        self.assertGreater(r["stats"]["words"], 40)
        self.assertGreater(r["stats"]["sentences"], 3)
        self.assertEqual(r["stats"]["headings"], 3)

    def test_caps_applied_for_big_grade_gap(self):
        r = engine.analyze(LEGAL, "general_public")
        self.assertTrue(r["caps"])

    def test_rewrites_change_text(self):
        r = engine.analyze(LEGAL, "consumer_notice")
        self.assertTrue(r["rewrites"])
        for w in r["rewrites"]:
            self.assertNotEqual(w["original"], w["suggested"])

    def test_hotspots_ordered(self):
        r = engine.analyze(LEGAL, "consumer_notice")
        scores = [h["score"] for h in r["hotspots"]]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestDetection(unittest.TestCase):
    def test_jargon_found(self):
        text = ("The patient was diagnosed with hypertension and the clinician adjusted the "
                "dosage of the medication accordingly for the next thirty days of treatment, and the clinician will review the response at the next scheduled appointment visit.")
        r = engine.analyze(text, "general_public")
        terms = [t["term"] for t in r["jargon"]]
        self.assertIn("hypertension", terms)
        self.assertIn("dosage", terms)

    def test_jargon_has_plain_alternative(self):
        text = ("A determination was made regarding the indemnification of the counterparty "
                "under the agreement and the parties will commence performance of the work immediately without any further delay to the schedule that was agreed.")
        r = engine.analyze(text, "consumer_notice")
        for t in r["jargon"]:
            self.assertTrue(t["plain"])

    def test_undefined_acronym_flagged(self):
        text = ("The JVM will send the TLS handshake to the CDN over the network. The JVM is configured by the "
                "operator before traffic reaches the CDN edge node in any region at all times, and the same JVM handles every request that arrives on that node.")
        r = engine.analyze(text, "technical_docs")
        acrs = [a["acronym"] for a in r["acronyms"]]
        self.assertIn("JVM", acrs)

    def test_defined_acronym_not_flagged(self):
        text = ("The Java Virtual Machine (JVM) sends the request to the service. The JVM is configured by the "
                "operator before the traffic reaches the edge node in any region at all times, and the same JVM handles every request that arrives on that node.")
        r = engine.analyze(text, "technical_docs")
        acrs = [a["acronym"] for a in r["acronyms"]]
        self.assertNotIn("JVM", acrs)

    def test_inclusive_language(self):
        text = ("This is a crazy design and we should do a sanity check on the manpower plan "
                "before we tell the chairman about the crazy timeline for the rollout of this.")
        r = engine.analyze(text, "internal_team")
        terms = [i["term"] for i in r["inclusive"]]
        self.assertIn("crazy", terms)
        self.assertIn("sanity check", terms)
        self.assertIn("manpower", terms)
        high = [f for f in r["findings"] if f["axis"] == "inclusivity" and f["severity"] == "high"]
        self.assertTrue(high)

    def test_passive_voice(self):
        text = ("The report was written by the committee. The decision was made in March and "
                "the budget was approved without any changes to the original proposal that was "
                "circulated to every member of the board last year.")
        r = engine.analyze(text, "internal_team")
        self.assertGreaterEqual(r["stats"]["passive_sentences"], 2)

    def test_long_sentence(self):
        text = ("The committee reviewed the proposal that the team had prepared in response to "
                "the request from the customer and then they recommended that the board approve "
                "the plan that would deliver the outcome described in the appendix to the report.")
        r = engine.analyze(text, "general_public")
        self.assertGreaterEqual(r["stats"]["long_sentences"], 1)

    def test_nominalization(self):
        text = ("The implementation of the configuration requires the utilization of the "
                "documentation and the evaluation of the normalization of every delivery that "
                "the organization completes during the administration of its operation.")
        r = engine.analyze(text, "internal_team")
        self.assertGreaterEqual(r["stats"]["words"], 25)
        nom = [f for f in r["findings"] if f["id"] == "craft.nominalizations"]
        self.assertTrue(nom)


class TestStructure(unittest.TestCase):
    def test_no_headings_flagged(self):
        body = ("This is a paragraph of prose without any heading at all in the document. " * 12)
        r = engine.analyze(body, "general_public")
        ids = [f["id"] for f in r["findings"]]
        self.assertIn("structure.no_headings", ids)

    def test_headings_parsed(self):
        r = engine.analyze(CLEAN, "support_article")
        self.assertEqual(len(r["structure"]["headings"]), 3)
        self.assertEqual(r["structure"]["headings"][0]["text"], "Reset your password")

    def test_lists_detected(self):
        r = engine.analyze(CLEAN, "support_article")
        self.assertEqual(r["structure"]["list_item_count"], 4)


class TestRewriting(unittest.TestCase):
    def test_jargon_substitution(self):
        out, subs = engine.apply_replacements("We must utilize the cache for every request.")
        self.assertIn("use", out)
        self.assertTrue(subs)

    def test_hyphen_variants(self):
        a, _ = engine.apply_replacements("This is man-made material.")
        b, _ = engine.apply_replacements("This is man made material.")
        self.assertIn("artificial", a)
        self.assertIn("artificial", b)

    def test_article_agreement(self):
        out, _ = engine.apply_replacements("We saw a an example earlier.")
        self.assertNotIn("a an", out)

    def test_code_block_untouched(self):
        text = "Prose here with utilize.\n\n" + chr(96) * 3 + "\nutilize(x)\n" + chr(96) * 3
        cleaned, count, _ = engine.clean_text(text)
        self.assertIn("utilize(x)", cleaned)
        self.assertIn("use.", cleaned)

    def test_cleaned_draft_substitutions_counted(self):
        text = "We must utilize the cache and comply with the indemnification clause."
        cleaned, count, applied = engine.clean_text(text)
        self.assertGreaterEqual(count, 2)
        self.assertNotEqual(cleaned, text)


class TestMarkdown(unittest.TestCase):
    def test_sections_present(self):
        r = engine.analyze(CLEAN, "support_article", "My doc")
        md = engine.render_markdown(r)
        for section in ["# Plain-Speak report", "## Scorecard", "## Readability metrics",
                        "## Findings", "## Fix plan", "## Cleaned draft"]:
            self.assertIn(section, md)

    def test_error_markdown(self):
        md = engine.render_markdown({"ok": False, "message": "nope"})
        self.assertIn("nope", md)


class TestSamples(unittest.TestCase):
    def test_all_samples_analyse(self):
        with open(os.path.join(SAMPLES, "manifest.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertGreaterEqual(len(manifest), 6)
        for entry in manifest:
            text = load_sample(entry["key"])
            r = engine.analyze(text, entry["audience"], entry["title"])
            self.assertTrue(r["ok"], entry["key"])
            self.assertGreater(r["score"], 0)
            self.assertIn(r["verdict"], ("plain_language_ready", "mostly_readable",
                                          "needs_edits", "hard_to_read", "needs_rework"))

    def test_control_sample_beats_worst_sample(self):
        clean = engine.analyze(load_sample("password_reset"), "support_article")
        worst = engine.analyze(load_sample("insurance_notice"), "consumer_notice")
        self.assertGreater(clean["score"], worst["score"] + 30)

    def test_launch_email_is_flagged_for_vagueness(self):
        r = engine.analyze(load_sample("launch_email"), "marketing_web")
        ids = [f["id"] for f in r["findings"]]
        self.assertTrue("craft.vague" in ids or "jargon.density" in ids)


class TestLexicon(unittest.TestCase):
    def test_entries_well_formed(self):
        from lexicon import INCLUSIVE, JARGON
        for term, value in JARGON.items():
            self.assertIsInstance(value, tuple)
            self.assertEqual(len(value), 2, term)
            self.assertTrue(value[1].strip(), term)
        for term, value in INCLUSIVE.items():
            self.assertEqual(len(value), 3, term)
            self.assertIn(value[2], ("high", "medium", "low"))

    def test_audience_profiles_complete(self):
        for key, prof in engine.AUD_PROFILES.items():
            self.assertIn("label", prof)
            self.assertIn("target_grade", prof)
            self.assertAlmostEqual(sum(prof["weights"].values()), 1.0, places=6, msg=key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
