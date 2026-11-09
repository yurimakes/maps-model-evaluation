"""Offline checks for the draft AI exchange example and its Markdown/HTML bundle.

This checks the documented exchange shape, not Fabric, authentication or model quality.
Only the Python standard library is used. No input values are included in reports.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SUBJECT_KEY = (
    "scope_id", "source_system", "source_table", "source_column",
    "source_batch_id", "source_schema_version",
)


def read_json(path: Path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON object key")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("Non-finite JSON number")

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Non-finite JSON number")
        return result

    with path.open(encoding="utf-8-sig") as stream:
        return json.load(stream, object_pairs_hook=pairs, parse_constant=nonfinite, parse_float=finite_float)


def validate_example(data) -> list[dict]:
    """Return issues for any exchange using this draft shape, without fixed IDs/counts."""
    issues = []

    def check(condition, code, path, message):
        if not condition:
            issues.append(dict(code=code, path=path, message=message))
        return bool(condition)

    def obj(value, path):
        return value if check(isinstance(value, dict), "OBJECT", path, "Object required") else {}

    def rows(value, path):
        if not check(isinstance(value, list), "ARRAY", path, "Array required"):
            return []
        result = []
        for i, item in enumerate(value):
            if check(isinstance(item, dict), "OBJECT", f"{path}/{i}", "Object required"):
                result.append(item)
        return result

    def label(value, path):
        return check(isinstance(value, str) and bool(value.strip()), "IDENTIFIER", path, "Non-empty identifier required")

    def index(items, field, path):
        result = {}
        for i, item in enumerate(items):
            key = item.get(field)
            if label(key, f"{path}/{i}/{field}"):
                check(key not in result, "DUPLICATE_ID", f"{path}/{i}/{field}", "Identifier must be unique")
                result[key] = item
        return result

    def refs(value, available, path, nonempty=False):
        if not check(isinstance(value, list), "ARRAY", path, "Reference array required"):
            return []
        if nonempty:
            check(bool(value), "EMPTY_REFS", path, "At least one reference required")
        valid = []
        for i, ref in enumerate(value):
            if label(ref, f"{path}/{i}"):
                check(ref in available, "UNRESOLVED_REF", f"{path}/{i}", "Reference does not resolve")
                valid.append(ref)
        check(len(valid) == len(set(valid)), "DUPLICATE_REF", path, "Repeated reference")
        return valid

    def same(a, b, path):
        check(a == b, "MISMATCH", path, "Linked values must match")

    def notes(value, path):
        for i, note in enumerate(rows(value, path)):
            for key in ["code", "message"]:
                label(note.get(key), f"{path}/{i}/{key}")

    def int_count(value, path):
        return check(type(value) is int and value >= 0, "COUNT", path, "Non-negative integer required")

    data = obj(data, "/")
    q, r = obj(data.get("request"), "/request"), obj(data.get("response"), "/response")
    for key in ["contract_version", "request_id", "scope_id", "input_snapshot_id", "input_snapshot_version"]:
        label(q.get(key), f"/request/{key}")
        same(q.get(key), r.get(key), f"/response/{key}")
    label(r.get("run_id"), "/response/run_id")
    times = []
    for key in ["requested_at", "started_at", "completed_at"]:
        value = r.get(key)
        if value is None:
            check(key != "requested_at", "TIMESTAMP", f"/response/{key}", "Request time required")
            times.append(None)
            continue
        try:
            time = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if time.tzinfo is None:
                raise ValueError()
            times.append(time)
        except (ValueError, AttributeError, TypeError):
            check(False, "TIMESTAMP", f"/response/{key}", "Timestamp must include a timezone")
            times.append(None)
    same(q.get("requested_at"), r.get("requested_at"), "/response/requested_at")
    valid_times = [t for t in times if t is not None]
    check(valid_times == sorted(valid_times), "TIME_ORDER", "/response", "Execution times out of order")
    check(not (times[2] is not None and times[1] is None), "TIME_ORDER", "/response/started_at", "Completed execution needs a start time")

    sources = index(rows(q.get("sources"), "/request/sources"), "source_ref", "/request/sources")
    subjects = index(rows(r.get("subjects"), "/response/subjects"), "source_ref", "/response/subjects")
    subject_positions = {sid: i for i, sid in enumerate(subjects)}
    same(set(sources), set(subjects), "/response/subjects")
    profiles = index(rows(q.get("profiling_assets", []), "/request/profiling_assets"), "ref", "/request/profiling_assets")
    schemas = index(rows(q.get("schema_assets", []), "/request/schema_assets"), "ref", "/request/schema_assets")
    types = q.get("recommendation_types")
    check(isinstance(types, list) and bool(types) and all(isinstance(t, str) for t in types), "REQUEST_TYPES", "/request/recommendation_types", "Recommendation types required")
    types = types if isinstance(types, list) and all(isinstance(t, str) for t in types) else []
    check(len(types) == len(set(types)), "REQUEST_TYPES", "/request/recommendation_types", "Repeated requested type")
    expected_pairs = set()
    for i, (sid, source) in enumerate(sources.items()):
        path = f"/request/sources/{i}"
        requested = source.get("requested_recommendation_types", types)
        if check(isinstance(requested, list) and bool(requested) and all(isinstance(t, str) and t in types for t in requested), "REQUEST_TYPES", path, "Subject types must come from the request"):
            expected_pairs.update((sid, t) for t in requested)
        for key in SUBJECT_KEY:
            label(source.get(key), path + "/" + key)
            same(source.get(key), subjects.get(sid, {}).get(key), f"/response/subjects/{subject_positions.get(sid, 'missing')}/{key}")
        same(source.get("scope_id"), q.get("scope_id"), path + "/scope_id")
        observed = obj(source.get("observed_type"), path + "/observed_type")
        check(observed.get("observation_scope") in ["sample", "population"], "OBSERVATION_SCOPE", path + "/observed_type", "Identify sample versus population")
        int_count(observed.get("observed_record_count"), path + "/observed_type/observed_record_count")
        basis = observed.get("basis_ref")
        if label(basis, path + "/observed_type/basis_ref"):
            check(basis in profiles, "UNRESOLVED_REF", path + "/observed_type/basis_ref", "Profiling basis is missing")
        same(basis, source.get("profiling_run_ref"), path + "/profiling_run_ref")
        if isinstance(basis, str) and basis in profiles:
            for key in ["scope_id", "source_system", "source_table", "source_batch_id"]:
                same(source.get(key), profiles[basis].get(key), path + "/profiling_run_ref/" + key)
        declared = obj(source.get("declared_type"), path + "/declared_type")
        if declared.get("value") is not None:
            check(isinstance(declared.get("basis_ref"), str) and declared["basis_ref"] in schemas, "DECLARED_TYPE_BASIS", path + "/declared_type", "Provided declaration needs a schema basis")

    # Bind entry IDs to their own asset and version, not a global union of entry IDs.
    assets = {}
    offered = rows(q.get("reference_assets"), "/request/reference_assets")
    for i, a in enumerate(offered):
        path = f"/request/reference_assets/{i}"
        if label(a.get("id"), path + "/id") and label(a.get("version"), path + "/version"):
            key = (a["id"], a["version"])
            check(key not in assets, "DUPLICATE_ASSET", path, "Repeated asset version")
            assets[key] = a
            if "scope_id" in a:
                same(a["scope_id"], q.get("scope_id"), path + "/scope_id")
    entries = set()
    for name in ["dictionary_entries", "candidate_word_entries"]:
        for i, entry in enumerate(rows(q.get(name, []), "/request/" + name)):
            key = (entry.get("asset_id"), entry.get("version"), entry.get("entry_id"))
            if all(isinstance(v, str) for v in key):
                check(key[:2] in assets, "UNRESOLVED_ASSET", f"/request/{name}/{i}", "Entry owner is not offered")
                entries.add(key)
            else:
                check(False, "ENTRY_IDENTITY", f"/request/{name}/{i}", "Entry needs owner, version and ID")
    for i, asset in enumerate(rows(q.get("target_assets", []), "/request/target_assets")):
        for table in rows(asset.get("tables"), f"/request/target_assets/{i}/tables"):
            for col in rows(table.get("columns"), f"/request/target_assets/{i}/columns"):
                key = (asset.get("id"), asset.get("version"), col.get("column_id"))
                if all(isinstance(v, str) for v in key):
                    entries.add(key)
                else:
                    check(False, "ENTRY_IDENTITY", f"/request/target_assets/{i}", "Target column identity is incomplete")
    snapshot = (q.get("input_snapshot_id"), q.get("input_snapshot_version"))

    def asset_ref(ref, path, nullable=False):
        if ref is None and nullable:
            return
        ref = obj(ref, path)
        key = (ref.get("id"), ref.get("version"))
        if not all(isinstance(v, str) for v in key):
            check(False, "ASSET_IDENTITY", path, "Asset ID and version required")
            return
        check(key in assets or key == snapshot, "UNRESOLVED_ASSET", path, "Asset version does not resolve")
        if ref.get("entry_id") is not None:
            if label(ref["entry_id"], path + "/entry_id"):
                check((*key, ref["entry_id"]) in entries, "UNRESOLVED_ENTRY", path, "Entry does not belong to this asset version")

    evidence = index(rows(r.get("evidence"), "/response/evidence"), "evidence_id", "/response/evidence")
    for i, (eid, entry) in enumerate(evidence.items()):
        path = f"/response/evidence/{i}"
        same(entry.get("scope_id"), q.get("scope_id"), path + "/scope_id")
        same(entry.get("input_snapshot_id"), q.get("input_snapshot_id"), path + "/input_snapshot_id")
        asset_ref(entry.get("asset_ref"), path + "/asset_ref")
        label(entry.get("locator"), path + "/locator")

    recommendations = rows(r.get("recommendations"), "/response/recommendations")
    index(recommendations, "recommendation_id", "/response/recommendations")
    processed, failed, used_evidence = set(), set(), set()
    processed_pairs, failed_pairs = set(), set()
    dispositions = Counter()
    for i, rec in enumerate(recommendations):
        path = f"/response/recommendations/{i}"
        rec_type = rec.get("recommendation_type")
        check(rec_type in types, "UNREQUESTED_TYPE", path + "/recommendation_type", "Type was not requested")
        subject_refs = refs(rec.get("subject_refs"), sources, path + "/subject_refs", nonempty=True)
        processed.update(subject_refs)
        if isinstance(rec_type, str):
            processed_pairs.update((sid, rec_type) for sid in subject_refs)
        for sid in subject_refs:
            requested = sources.get(sid, {}).get("requested_recommendation_types", types)
            check(isinstance(requested, list) and rec_type in requested, "UNREQUESTED_TYPE", path + "/subject_refs", "Type was not requested for subject")
        disposition = rec.get("disposition")
        if label(disposition, path + "/disposition"):
            dispositions[disposition] += 1
        used_evidence.update(refs(rec.get("evidence_refs"), evidence, path + "/evidence_refs"))
        int_count(rec.get("revision"), path + "/revision")
        if rec_type == "mapping":
            check("ai_migration_apply" in rec and (rec.get("ai_migration_apply") is None or type(rec.get("ai_migration_apply")) is bool), "AI_APPLY", path, "AI proposal must be boolean or null")
            if disposition == "apply_candidate":
                check(rec.get("ai_migration_apply") is True, "AI_APPLY", path, "Apply candidate needs an apply proposal")
            if disposition == "exclude_candidate" or rec.get("ai_migration_apply") is False:
                check(disposition == "exclude_candidate" and rec.get("ai_migration_apply") is False, "AI_APPLY", path, "Exclude proposal and disposition must agree")
                label(rec.get("ai_exclude_reason"), path + "/ai_exclude_reason")
            if disposition == "hold":
                check(rec.get("ai_migration_apply") is None, "AI_APPLY", path, "Hold must not decide apply/exclude")
            check("migration_apply" in rec and rec["migration_apply"] is None, "FINAL_IN_AI_RESPONSE", path, "AI exchange cannot supply a human final value")
        else:
            check(not any(k in rec for k in ["migration_apply", "ai_migration_apply", "ai_exclude_reason", "exclude_reason"]), "NOT_APPLICABLE", path, "Migration decision fields do not apply to this type")
        check(str(rec.get("review_status", "")).upper() in ["PENDING", "IN_REVIEW"], "FINAL_IN_AI_RESPONSE", path + "/review_status", "AI exchange must not issue approval")
        for j, candidate in enumerate(rows(rec.get("candidates"), path + "/candidates")):
            cp = f"{path}/candidates/{j}"
            asset_ref(candidate.get("asset_ref"), cp + "/asset_ref", nullable=True)
            for name in ["word_refs", "dependency_refs"]:
                for k, ref in enumerate(rows(candidate.get(name, []), cp + "/" + name)):
                    asset_ref(ref, f"{cp}/{name}/{k}")
            if rec_type == "mapping" and disposition == "apply_candidate":
                asset_ref(q.get("approved_target_model_ref"), "/request/approved_target_model_ref")
                target = q.get("approved_target_model_ref")
                target = target if isinstance(target, dict) else {}
                ref = candidate.get("asset_ref")
                ref = ref if isinstance(ref, dict) else {}
                same((ref.get("id"), ref.get("version")), (target.get("id"), target.get("version")), cp + "/asset_ref")
        for j, item in enumerate(rows(rec.get("checks"), path + "/checks")):
            used_evidence.update(refs(item.get("evidence_refs"), evidence, f"{path}/checks/{j}/evidence_refs"))
        confidence = obj(rec.get("confidence"), path + "/confidence")
        value = confidence.get("value")
        if value is not None:
            check(type(value) in [int, float] and math.isfinite(value) and 0 <= value <= 1, "CONFIDENCE_RANGE", path + "/confidence/value", "Normalized confidence must be between 0 and 1")
            label(confidence.get("method_id"), path + "/confidence/method_id")
            label(confidence.get("method_version"), path + "/confidence/method_version")
        else:
            label(confidence.get("reason"), path + "/confidence/reason")
            check(confidence.get("level") is None, "CONFIDENCE_LEVEL", path + "/confidence/level", "Uncomputed confidence cannot have a level")
        for name in ["warnings", "missing_requirements"]:
            notes(rec.get(name, []), path + "/" + name)
    same(used_evidence, set(evidence), "/response/evidence/usage")

    failures = rows(r.get("failures", []), "/response/failures")
    for i, item in enumerate(failures):
        path = f"/response/failures/{i}"
        failure_refs = refs(item.get("subject_refs"), sources, path + "/subject_refs", nonempty=True)
        failed.update(failure_refs)
        if isinstance(item.get("recommendation_type"), str):
            failed_pairs.update((sid, item["recommendation_type"]) for sid in failure_refs)
        check(item.get("recommendation_type") in types, "UNREQUESTED_TYPE", path, "Failure type was not requested")
        for name in ["code", "message", "stage"]:
            label(item.get(name), path + "/" + name)
        check(type(item.get("retryable")) is bool, "BOOLEAN", path + "/retryable", "Boolean required")
    # A subject may have several requested recommendation types. Partial type failure is valid.
    same(processed | failed, set(sources), "/response/subject_coverage")
    same(processed_pairs | failed_pairs, expected_pairs, "/response/subject_type_coverage")
    check(not processed_pairs.intersection(failed_pairs), "CONTRADICTORY_OUTCOME", "/response", "Same subject/type cannot both fail and have a recommendation")
    counts = obj(r.get("counts"), "/response/counts")
    expected = dict(input_subjects=len(sources), processed_subjects=len(processed), failed_subjects=len(failed), recommendations=len(recommendations))
    for key, value in expected.items():
        if int_count(counts.get(key), "/response/counts/" + key):
            same(counts[key], value, "/response/counts/" + key)
    by_disposition = obj(counts.get("by_disposition"), "/response/counts/by_disposition")
    for key, value in by_disposition.items():
        int_count(value, "/response/counts/by_disposition")
    same(by_disposition, dict(dispositions), "/response/counts/by_disposition")
    if failures:
        check(str(r.get("run_status", "")).lower() not in ["completed", "success", "succeeded"], "PARTIAL_SUCCESS", "/response/run_status", "Failure must not be reported as total success")

    versions = obj(r.get("versions"), "/response/versions")
    policies = rows(q.get("policy_refs", []), "/request/policy_refs")
    if "policy_ref" in q:
        policies.append(obj(q["policy_ref"], "/request/policy_ref"))
    policy_keys = []
    for i, policy in enumerate(policies):
        if label(policy.get("id"), f"/request/policies/{i}/id") and label(policy.get("version"), f"/request/policies/{i}/version"):
            policy_keys.append((policy["id"], policy["version"]))
    actual_policies = []
    for i, policy in enumerate(rows(versions.get("policy_refs"), "/response/versions/policy_refs")):
        if label(policy.get("id"), f"/response/versions/policy_refs/{i}/id") and label(policy.get("version"), f"/response/versions/policy_refs/{i}/version"):
            actual_policies.append((policy["id"], policy["version"]))
    same(Counter(actual_policies), Counter(policy_keys), "/response/versions/policy_refs")
    if "reference_manifest_id" in q:
        same(versions.get("reference_manifest_id"), q["reference_manifest_id"], "/response/versions/reference_manifest_id")
    snapshot_ref = obj(versions.get("input_snapshot_ref"), "/response/versions/input_snapshot_ref")
    same((snapshot_ref.get("id"), snapshot_ref.get("version")), snapshot, "/response/versions/input_snapshot_ref")
    schema_ref = obj(versions.get("input_schema_ref"), "/response/versions/input_schema_ref")
    same(schema_ref.get("version"), q.get("source_schema_version"), "/response/versions/input_schema_ref")
    usage = {}
    for i, a in enumerate(rows(r.get("reference_asset_usage"), "/response/reference_asset_usage")):
        path = f"/response/reference_asset_usage/{i}"
        asset_ref(a, path)
        key = (a.get("id"), a.get("version"))
        if all(isinstance(v, str) for v in key):
            check(key not in usage, "DUPLICATE_ASSET", path, "Repeated usage record")
            usage[key] = a
        check(a.get("usage") in ["used", "not_used"], "ASSET_USAGE", path, "Explicit asset usage required")
        label(a.get("reason"), path + "/reason")
    same(set(usage), set(assets), "/response/reference_asset_usage")
    used_assets = set()
    for i, a in enumerate(rows(versions.get("reference_assets"), "/response/versions/reference_assets")):
        asset_ref(a, f"/response/versions/reference_assets/{i}")
        key = (a.get("id"), a.get("version"))
        if all(isinstance(v, str) for v in key):
            check(key not in used_assets, "DUPLICATE_ASSET", "/response/versions/reference_assets", "Repeated version record")
            used_assets.add(key)
    same(used_assets, {k for k, a in usage.items() if a.get("usage") == "used"}, "/response/versions/reference_assets")
    for i, (eid, entry) in enumerate(evidence.items()):
        ref = entry.get("asset_ref")
        if isinstance(ref, dict):
            key = (ref.get("id"), ref.get("version"))
            if all(isinstance(v, str) for v in key) and key != snapshot:
                check(key in used_assets, "ASSET_USAGE", f"/response/evidence/{i}", "Evidence owner must be recorded as used")
    notes(r.get("warnings", []), "/response/warnings")
    return issues


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.article = self.nav = self.skip = self.count = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == "article":
            self.article += 1
            self.count += 1
        if tag == "nav":
            self.nav += 1
        if tag in ["script", "style"]:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag == "article":
            self.article -= 1
        if tag == "nav":
            self.nav -= 1
        if tag in ["script", "style"]:
            self.skip -= 1

    def handle_data(self, value):
        if self.article and not self.nav and not self.skip:
            self.text.append(value)


def markdown_text(markdown: str) -> str:
    """Extract this bundle's headings, paragraphs, simple tables and ordered lists."""
    plain = []
    for line in markdown.splitlines():
        if re.fullmatch(r"\s*\|[\s:|\-]+\|\s*", line):
            continue
        if line.startswith("|"):
            line = "".join(c.strip() for c in line.strip().strip("|").split("|"))
        if re.match(r"^#{1,6}\s+", line):
            line = re.sub(r"^#{1,6}\s+", "", line)
        else:
            line = re.sub(r"^\d+\.\s+", "", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        plain.append(line)
    return "".join(plain)


def document_issues(markdown: str, html: str, version: str) -> list[dict]:
    issues = []

    def fail(code, path, message):
        issues.append(dict(code=code, path=path, message=message))

    parser = ArticleText()
    parser.feed(html)
    compact = lambda s: re.sub(r"\s+", "", s)
    if parser.count != 1 or compact(markdown_text(markdown)) != compact("".join(parser.text)):
        fail("DOCUMENT_MISMATCH", "/documents", "Markdown and HTML article text differ")
    for name, content in [("markdown", markdown), ("html", html)]:
        # Other source standards have their own versions. Check the document header, not all mentions.
        head = content.split("\n## ", 1)[0] if name == "markdown" else "".join(re.findall(r"<title>(.*?)</title>", content, re.S))
        first_version = re.search(r"\bv(\d+\.\d+)\b", head)
        if not first_version or first_version[1] != version:
            fail("DOCUMENT_VERSION", "/documents/" + name, "Document header version differs from bundle")
        if re.search(r"[A-Za-z]:[\\/]Users[\\/]|file://", content):
            fail("LOCAL_PATH", "/documents/" + name, "User-specific local path in shared artifact")
    headings = re.findall(r"^#{2,3}\s+(\d+(?:\.\d+)*)\s", markdown, re.M)
    if len(headings) != len(set(headings)):
        fail("DUPLICATE_SECTION", "/documents/markdown", "Repeated section number")
    for reference in re.findall(r"(?<![\d.])(\d+\.\d+)절", markdown):
        if reference not in headings:
            fail("SECTION_REF", "/documents/markdown", "Section reference does not resolve")
    return issues


def validate_bundle(bundle_dir: Path, example_path: Path | None = None) -> dict:
    issues, hashes = [], {}
    manifest_path = bundle_dir / "bundle.json"
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("Bundle manifest must be an object")
    files = {}
    for key in ["markdown", "html", "example"]:
        name = manifest.get(key)
        if not isinstance(name, str):
            raise ValueError("Missing artifact filename in bundle manifest")
        path = (bundle_dir / name).resolve()
        if not path.is_relative_to(bundle_dir.resolve()):
            raise ValueError("Bundle artifact path must stay in bundle directory")
        files[key] = path
    if example_path:
        files["example"] = example_path.resolve()
    data = read_json(files["example"])
    issues.extend(validate_example(data))
    for key in ["request", "response"]:
        if isinstance(data, dict) and isinstance(data.get(key), dict) and data[key].get("contract_version") != manifest.get("contract_version"):
            issues.append(dict(code="CONTRACT_VERSION", path=f"/{key}/contract_version", message="Contract version differs from bundle"))
    issues.extend(document_issues(files["markdown"].read_text(encoding="utf-8-sig"), files["html"].read_text(encoding="utf-8-sig"), str(manifest.get("document_version"))))
    for key, path in {**files, "manifest": manifest_path}.items():
        hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(passed=not issues, scope="offline_artifact_structure", document_version=manifest.get("document_version"), contract_version=manifest.get("contract_version"), issues=issues, input_sha256=hashes, model_inference_executed=False, fabric_integration_tested=False, gate_approval_issued=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=HERE / "artifacts", help="Directory containing bundle.json")
    parser.add_argument("--example", type=Path, help="Validate another exchange JSON against the bundled draft")
    parser.add_argument("--out", type=Path, help="New report directory; existing directories are refused")
    args = parser.parse_args(argv)
    try:
        result = validate_bundle(args.bundle, args.example)
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        result = dict(passed=False, scope="offline_artifact_structure", issues=[dict(code="INPUT_READ", path="/", message=f"Cannot read a valid bundle ({type(exc).__name__})")], model_inference_executed=False, fabric_integration_tested=False, gate_approval_issued=False)
    output = args.out or REPO / "results/ai-contract-validation" / (datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%dT%H%M%S%z") + "-" + uuid4().hex[:8])
    try:
        output.mkdir(parents=True, exist_ok=False)
        (output / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        print("ERROR [REPORT_WRITE] Cannot create a new report directory; existing reports are never overwritten.", file=sys.stderr)
        return 2
    for issue in result["issues"]:
        print(f"ERROR [{issue['code']}] {issue['path']}: {issue['message']}")
    print(f"{'PASS' if result['passed'] else 'FAIL'}: offline artifact checks; report: {output}")
    print("No model inference, Fabric integration test or approval was performed.")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
