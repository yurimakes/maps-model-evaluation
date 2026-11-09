"""Synthetic regression checks; no external accounts, real data or paid services."""
import copy
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from validate import HERE, document_issues, main, read_json, validate_bundle, validate_example
from render_html import main as render_main


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.data = read_json(HERE / "artifacts/MAPS_AI_연계예시_v0.1.json")

    def codes(self):
        return {x["code"] for x in validate_example(self.data)}

    def test_reviewed_bundle(self):
        self.assertTrue(validate_bundle(HERE / "artifacts")["passed"])

    def test_example_is_valid(self):
        self.assertEqual(validate_example(self.data), [])

    def test_no_fixed_ids_or_subject_counts(self):
        q, r = self.data["request"], self.data["response"]
        original = r["recommendations"][0]
        sid = original["subject_refs"][0]
        source = copy.deepcopy(next(s for s in q["sources"] if s["source_ref"] == sid))
        source.update(source_ref="another-subject", source_column="ANOTHER_COLUMN")
        q["sources"].append(source)
        subject = copy.deepcopy(next(s for s in r["subjects"] if s["source_ref"] == sid))
        subject.update(source_ref=source["source_ref"], source_column=source["source_column"])
        r["subjects"].append(subject)
        rec = copy.deepcopy(original)
        rec.update(recommendation_id="another-recommendation", subject_refs=[source["source_ref"]])
        r["recommendations"].append(rec)
        for key in ["input_subjects", "processed_subjects", "recommendations"]:
            r["counts"][key] += 1
        r["counts"]["by_disposition"][rec["disposition"]] += 1
        self.assertEqual(validate_example(self.data), [])

    def test_multiple_recommendations_are_not_subject_count(self):
        r = self.data["response"]
        rec = copy.deepcopy(r["recommendations"][0])
        rec["recommendation_id"] = "alternative-recommendation"
        r["recommendations"].append(rec)
        r["counts"]["recommendations"] += 1
        r["counts"]["by_disposition"][rec["disposition"]] += 1
        self.assertEqual(validate_example(self.data), [])

    def test_dangling_subject(self):
        self.data["response"]["recommendations"][0]["subject_refs"] = ["missing"]
        self.assertIn("UNRESOLVED_REF", self.codes())

    def test_dangling_evidence(self):
        self.data["response"]["recommendations"][0]["evidence_refs"].append("missing")
        self.assertIn("UNRESOLVED_REF", self.codes())

    def test_duplicate_recommendation(self):
        r = self.data["response"]["recommendations"]
        r[1]["recommendation_id"] = r[0]["recommendation_id"]
        self.assertIn("DUPLICATE_ID", self.codes())

    def test_cross_scope_evidence(self):
        self.data["response"]["evidence"][0]["scope_id"] = "different-scope"
        self.assertIn("MISMATCH", self.codes())

    def test_response_composite_key_mismatch(self):
        self.data["response"]["subjects"][0]["source_table"] = "different-table"
        self.assertIn("MISMATCH", self.codes())

    def test_entry_cannot_belong_to_another_asset(self):
        ref = self.data["response"]["recommendations"][0]["candidates"][0]["asset_ref"]
        ref["id"] = "demo-public-reference"
        self.assertIn("UNRESOLVED_ENTRY", self.codes())

    def test_snapshot_does_not_use_schema_version(self):
        d = self.data
        ev = next(x for x in d["response"]["evidence"] if x["kind"] == "input_metadata")
        ev["asset_ref"]["version"] = d["request"]["source_schema_version"]
        self.assertIn("UNRESOLVED_ASSET", self.codes())

    def test_incorrect_counts_and_boolean_count(self):
        self.data["response"]["counts"]["recommendations"] = True
        self.assertIn("COUNT", self.codes())
        self.data["response"]["counts"]["recommendations"] = 100
        self.assertIn("MISMATCH", self.codes())

    def test_wrong_disposition_totals(self):
        self.data["response"]["counts"]["by_disposition"] = {}
        self.assertIn("MISMATCH", self.codes())

    def test_missing_type_outcome(self):
        self.data["request"]["sources"][0]["requested_recommendation_types"].append("mapping")
        self.assertIn("MISMATCH", self.codes())

    def test_unrequested_type(self):
        self.data["response"]["recommendations"][0]["recommendation_type"] = "not-requested"
        self.assertIn("UNREQUESTED_TYPE", self.codes())

    def test_contradictory_failure(self):
        r = self.data["response"]
        r["failures"][0]["subject_refs"] = r["recommendations"][0]["subject_refs"]
        self.assertIn("CONTRADICTORY_OUTCOME", self.codes())

    def test_success_cannot_hide_failures(self):
        self.data["response"]["run_status"] = "completed"
        self.assertIn("PARTIAL_SUCCESS", self.codes())

    def test_naive_or_reversed_time(self):
        self.data["response"]["started_at"] = "2026-11-05T10:00:01"
        self.assertIn("TIMESTAMP", self.codes())
        self.data["response"]["started_at"] = "2026-11-05T11:00:01+09:00"
        self.assertIn("TIME_ORDER", self.codes())

    def test_final_value_is_not_ai_proposal(self):
        rec = next(x for x in self.data["response"]["recommendations"] if x["recommendation_type"] == "mapping")
        rec["migration_apply"] = True
        self.assertIn("FINAL_IN_AI_RESPONSE", self.codes())

    def test_exclude_proposal_needs_reason(self):
        rec = next(x for x in self.data["response"]["recommendations"] if x["recommendation_type"] == "mapping")
        rec.update(disposition="exclude_candidate", ai_migration_apply=False, ai_exclude_reason=None)
        self.assertIn("IDENTIFIER", self.codes())

    def test_nonmapping_has_no_migration_decision(self):
        self.data["response"]["recommendations"][0]["migration_apply"] = None
        self.assertIn("NOT_APPLICABLE", self.codes())

    def test_confidence_requires_range_and_method(self):
        conf = self.data["response"]["recommendations"][0]["confidence"]
        conf["value"] = 2
        self.assertIn("CONFIDENCE_RANGE", self.codes())
        conf["value"] = 0.5
        self.assertIn("IDENTIFIER", self.codes())

    def test_usage_must_cover_offered_assets(self):
        self.data["response"]["reference_asset_usage"].pop()
        self.assertIn("MISMATCH", self.codes())

    def test_unused_asset_cannot_own_evidence(self):
        r = self.data["response"]
        owner = r["evidence"][0]["asset_ref"]["id"]
        next(x for x in r["reference_asset_usage"] if x["id"] == owner)["usage"] = "not_used"
        r["versions"]["reference_assets"] = [x for x in r["versions"]["reference_assets"] if x["id"] != owner]
        self.assertIn("ASSET_USAGE", self.codes())

    def test_policy_version_mismatch(self):
        self.data["response"]["versions"]["policy_refs"][0]["version"] = "other-version"
        self.assertIn("MISMATCH", self.codes())

    def test_invalid_shapes_return_issues(self):
        self.assertTrue(validate_example({"request": [], "response": []}))
        self.data["response"]["recommendations"][0]["subject_refs"] = [{}]
        self.assertIn("IDENTIFIER", self.codes())

    def test_heading_and_actual_content_changes_are_detected(self):
        md = "# Example\n\nv0.1\n\n## 1. Section\n\nText.\n"
        ht = "<title>Example v0.1</title><article><h1>Example</h1><p>v0.1</p><h2>1. Section</h2><p>Text.</p></article>"
        self.assertEqual(document_issues(md, ht, "0.1"), [])
        self.assertIn("DOCUMENT_MISMATCH", {i["code"] for i in document_issues(md, ht.replace("Text.", "Changed."), "0.1")})

    def test_section_reference(self):
        issues = document_issues("# v0.1\n\n## 1. Section\n\n9.9절\n", "<title>v0.1</title><article></article>", "0.1")
        self.assertIn("SECTION_REF", {i["code"] for i in issues})

    def test_header_version_is_not_masked_by_later_text(self):
        issues = document_issues("# Example\n\nv0.2\n\nprevious v0.1\n", "<title>Example v0.2</title><article></article>", "0.1")
        self.assertEqual(sum(x["code"] == "DOCUMENT_VERSION" for x in issues), 2)

    def test_issue_locations_do_not_echo_subject_ids(self):
        q, r = self.data["request"], self.data["response"]
        old = q["sources"][0]["source_ref"]
        sensitive_id = "value-that-must-not-appear-in-report"
        q["sources"][0]["source_ref"] = sensitive_id
        q["sources"][0]["observed_type"]["observed_record_count"] = -1
        for subject in r["subjects"]:
            if subject["source_ref"] == old:
                subject["source_ref"] = sensitive_id
        for rec in r["recommendations"]:
            rec["subject_refs"] = [sensitive_id if sid == old else sid for sid in rec["subject_refs"]]
        issues = validate_example(self.data)
        self.assertTrue(issues)
        self.assertNotIn(sensitive_id, json.dumps(issues))

    def test_strict_json(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "bad.json"
            for text in ['{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}']:
                p.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_json(p)

    def test_reports_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            output = Path(folder) / "run"
            self.assertEqual(main(["--out", str(output)]), 0)
            original = (output / "validation.json").read_bytes()
            self.assertEqual(main(["--out", str(output)]), 2)
            self.assertEqual(original, (output / "validation.json").read_bytes())

    def test_invalid_input_exit_code_and_report(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            root = Path(folder)
            invalid = root / "invalid.json"
            invalid.write_text('{"request":', encoding="utf-8")
            output = root / "run"
            self.assertEqual(main(["--example", str(invalid), "--out", str(output)]), 1)
            self.assertFalse(json.loads((output / "validation.json").read_text(encoding="utf-8"))["passed"])

    def test_render_updated_markdown_and_validate(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            root = Path(folder)
            for source in (HERE / "artifacts").iterdir():
                (root / source.name).write_bytes(source.read_bytes())
            manifest = read_json(root / "bundle.json")
            markdown = root / manifest["markdown"]
            markdown.write_text(markdown.read_text(encoding="utf-8") + "\n추가된 **합성 검토 문장**.\n", encoding="utf-8")
            self.assertFalse(validate_bundle(root)["passed"])
            self.assertEqual(render_main(["--bundle", str(root)]), 0)
            self.assertTrue(validate_bundle(root)["passed"])
            first = (root / manifest["html"]).read_bytes()
            self.assertEqual(render_main(["--bundle", str(root)]), 0)
            self.assertEqual(first, (root / manifest["html"]).read_bytes())


if __name__ == "__main__":
    unittest.main()
