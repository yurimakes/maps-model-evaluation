# -*- coding: utf-8 -*-
"""
MAPS 실험 1 기준선 - 합성 사례 테스트 (표준 라이브러리 unittest)
합성 결과는 MAPS 성능 점수에 포함하지 않는다.
실행: python -m unittest discover -s tests -v
"""
import csv
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import maps_exp1_baseline as mb  # noqa: E402
import validate_output as vo  # noqa: E402

SRC_HEADER = list(mb.SOURCE_REQUIRED_COLUMNS)
TGT_HEADER = list(mb.TARGET_REQUIRED_COLUMNS)

# 합성 Source 10행 (실제 입력과 무관한 가상 식별자)
SYN_SOURCE = [
    ["SHOPSYS", "TB_MBR_MASTER", "N", "MEMBER_NAME", "VARCHAR(50)", "회원명", "Y", "N", "N", "N", "Y", "", ""],
    ["SHOPSYS", "TB_MBR_MASTER", "N", "JOIN_YMD", "CHAR(8)", "가입일자", "Y", "N", "N", "N", "N", "YYYYMMDD", ""],
    ["SHOPSYS", "TB_MBR_MASTER", "N", "SMS_AGREE_YN", "CHAR(1)", "SMS 수신 동의 여부", "N", "N", "N", "Y", "N", "Y/N",
     "Y|N"],
    ["SHOPSYS", "TB_MBR_MASTER", "N", "MEMBER_GRADE", "VARCHAR(10)", "회원 등급 코드", "Y", "N", "N", "Y", "N", "", ""],
    ["SHOPSYS", "TB_MBR_MASTER", "N", "MEMBER_NO", "VARCHAR(20)", "회원 식별 번호", "N", "Y", "Y", "N", "N", "", ""],
    ["SHOPSYS", "TB_ORD_HIST", "N", "ORDER_NO", "VARCHAR(30)", "주문번호", "N", "Y", "Y", "N", "N", "", ""],
    ["SHOPSYS", "TB_ORD_HIST", "N", "ORDER_MEMO", "VARCHAR(200)", "주문 메모", "Y", "N", "N", "N", "N", "", ""],
    ["SHOPSYS", "TB_ORD_HIST", "Y", "RAW_FIELD_X", "", "", "", "", "", "", "", "", ""],
    ["SHOPSYS", "TB_ORD_HIST", "N", "ORDER_AMT", "DECIMAL(12,0)", "주문금액", "Y", "N", "N", "N", "N", "", ""],
    ["SHOPSYS", "TB_ORD_HIST", "N", "DEL_FLAG", "CHAR(1)", "삭제 여부", "N", "N", "N", "Y", "N", "", ""],
]
# 합성 Target 8행
SYN_TARGET = [
    ["MEMBER", "MBR_KEY", "VARCHAR(40)", "PK", "N", "회원 통합 식별자"],
    ["MEMBER", "MBR_NM", "VARCHAR(80)", "", "Y", "회원명"],
    ["MEMBER", "JOIN_DT", "DATE", "", "Y", "가입일자"],
    ["MEMBER", "GRADE_CD", "VARCHAR(10)", "", "Y", "회원등급 코드"],
    ["MEMBER", "SMS_AGR_YN", "CHAR(1)", "", "N", "SMS 수신 동의 여부(Y/N)"],
    ["ORDERS", "ORD_NO", "VARCHAR(30)", "PK", "N", "주문번호"],
    ["ORDERS", "ORD_AMT", "DECIMAL(15,2)", "", "Y", "주문금액"],
    ["ORDERS", "ORD_MEMO", "VARCHAR(100)", "", "Y", "주문 메모"],
]
PROTOCOL_TEXT = (
    'source_system source_table source_column decision targets reason missing_information '
    'target_table target_column operation parameters exception_policy '
    'MIGRATE | EXCLUDE | REVIEW COPY | FORMAT | LOOKUP | EXPLODE | CONSTANT | CUSTOMER_MATCH | GENERATE_ID | REVIEW'
)


def write_csv(path: Path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


class SyntheticFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="maps_exp1_test_"))
        self.inp = self.tmp / "input"
        self.out = self.tmp / "output"
        self.inp.mkdir()
        self.src = self.inp / "source_metadata.csv"
        self.tgt = self.inp / "target_schema.csv"
        self.pro = self.inp / "OUTPUT_CONTRACT.txt"
        write_csv(self.src, SRC_HEADER, SYN_SOURCE)
        write_csv(self.tgt, TGT_HEADER, SYN_TARGET)
        self.pro.write_text(PROTOCOL_TEXT, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestInputValidation(SyntheticFixture):
    def test_load_counts(self):
        self.assertEqual(len(mb.load_sources(self.src)), 10)
        self.assertEqual(len(mb.load_targets(self.tgt)), 8)

    def test_missing_header(self):
        write_csv(self.src, SRC_HEADER[:-1], [r[:-1] for r in SYN_SOURCE])
        with self.assertRaises(mb.InputError):
            mb.load_sources(self.src)

    def test_duplicate_source(self):
        write_csv(self.src, SRC_HEADER, SYN_SOURCE + [SYN_SOURCE[0]])
        with self.assertRaises(mb.InputError):
            mb.load_sources(self.src)

    def test_duplicate_target(self):
        write_csv(self.tgt, TGT_HEADER, SYN_TARGET + [SYN_TARGET[1]])
        with self.assertRaises(mb.InputError):
            mb.load_targets(self.tgt)

    def test_field_count_mismatch(self):
        rows = [r[:] for r in SYN_SOURCE]
        rows[2] = rows[2][:-2]
        write_csv(self.src, SRC_HEADER, rows)
        with self.assertRaises(mb.InputError):
            mb.load_sources(self.src)

    def test_bad_flag_value(self):
        rows = [r[:] for r in SYN_SOURCE]
        rows[0][6] = "X"
        write_csv(self.src, SRC_HEADER, rows)
        with self.assertRaises(mb.InputError):
            mb.load_sources(self.src)

    def test_expected_count_mismatch(self):
        with self.assertRaises(mb.InputError):
            mb.generate(self.src, self.tgt, self.pro, self.out, expect_source_rows=140)

    def test_protocol_mismatch(self):
        self.pro.write_text("source_system only", encoding="utf-8")
        with self.assertRaises(mb.InputError):
            mb.generate(self.src, self.tgt, self.pro, self.out)

    def test_output_dir_must_differ_from_input(self):
        with self.assertRaises(mb.InputError):
            mb.generate(self.src, self.tgt, self.pro, self.inp)

    def test_exclusion_rule_unknown_source(self):
        ex = self.inp / "exclusion_rules.csv"
        write_csv(ex, list(mb.EXCLUSION_REQUIRED_COLUMNS), [["SHOPSYS", "TB_ORD_HIST", "NO_SUCH_COL", "사유"]])
        with self.assertRaises(mb.InputError):
            mb.generate(self.src, self.tgt, self.pro, self.out, exclusion_path=ex)


class TestHelpers(unittest.TestCase):
    def test_split_identifier(self):
        self.assertEqual(mb.split_identifier("Order_Total__c"), ["order", "total"])
        self.assertEqual(mb.split_identifier("lastModifiedDate"), ["last", "modified", "date"])
        self.assertEqual(mb.split_identifier("HTTPServerID"), ["http", "server", "id"])
        self.assertEqual(mb.split_identifier("MBR_NM"), ["mbr", "nm"])

    def test_abbreviation(self):
        cfg = mb.Config()
        self.assertEqual(mb.token_match("nm", "name", cfg), cfg.abbrev_partial_credit)
        self.assertEqual(mb.token_match("ord", "order", cfg), cfg.abbrev_partial_credit)
        self.assertEqual(mb.token_match("xy", "order", cfg), 0.0)
        self.assertEqual(mb.token_match("od", "order", cfg), 0.0 if 2 / 5 < cfg.abbrev_min_ratio
                         else cfg.abbrev_partial_credit)
        self.assertGreater(mb.abbreviation_score(["member", "name"], ["mbr", "nm"], cfg), 0.7)

    def test_parse_type(self):
        t = mb.parse_data_type("DECIMAL(12,0)")
        self.assertEqual((t.family, t.precision, t.scale), ("DECIMAL", 12, 0))
        self.assertEqual(mb.parse_data_type("String(18)").length, 18)
        self.assertEqual(mb.parse_data_type("Long Text Area").family, "TEXT")
        self.assertEqual(mb.parse_data_type("Datetime").family, "TIMESTAMP")
        self.assertEqual(mb.parse_data_type("").family, "UNKNOWN")
        self.assertEqual(mb.parse_data_type("GEOMETRY").family, "UNKNOWN")

    def test_date_hint(self):
        self.assertEqual(mb.parse_date_hint("YYYYMMDD")["pattern"], "%Y%m%d")
        h = mb.parse_date_hint("YYYY-MM-DD HH:MM:SS")
        self.assertEqual((h["kind"], h["pattern"]), ("TIMESTAMP", "%Y-%m-%d %H:%M:%S"))
        self.assertIsNone(mb.parse_date_hint("[MM:SS] 화자: 내용"))
        self.assertIsNone(mb.parse_date_hint("1/2"))
        self.assertIsNone(mb.parse_date_hint(""))

    def test_enum_domain(self):
        self.assertEqual(mb.parse_target_enum_domain("Y/N"), {"Y", "N"})
        self.assertEqual(mb.parse_target_enum_domain("동의 여부(Y/N)"), {"Y", "N"})
        self.assertIsNone(mb.parse_target_enum_domain("ALPHA/BETA 등"))
        self.assertIsNone(mb.parse_target_enum_domain("가/나/다"))
        self.assertEqual(mb.parse_source_code_hint("A1|B2"), {"A1", "B2"})
        self.assertIsNone(mb.parse_source_code_hint(""))


class TestEndToEnd(SyntheticFixture):
    def _run(self, out, exclusion=None):
        return mb.generate(self.src, self.tgt, self.pro, out, exclusion_path=exclusion)

    def _by_col(self, res):
        return {d.record["source_column"]: d for d in res.decisions}

    def test_decisions(self):
        ex = self.inp / "exclusion_rules.csv"
        write_csv(ex, list(mb.EXCLUSION_REQUIRED_COLUMNS),
                  [["SHOPSYS", "TB_ORD_HIST", "DEL_FLAG", "합성 테스트용 명시 제외 규칙"]])
        res = self._run(self.out, ex)
        by = self._by_col(res)

        def first(col):
            return by[col].record["targets"][0]

        # MIGRATE / COPY
        self.assertEqual(by["MEMBER_NAME"].record["decision"], "MIGRATE")
        self.assertEqual((first("MEMBER_NAME")["target_column"], first("MEMBER_NAME")["operation"]),
                         ("MBR_NM", "COPY"))
        # MIGRATE / FORMAT (명시 형식 -> DATE)
        self.assertEqual(by["JOIN_YMD"].record["decision"], "MIGRATE")
        self.assertEqual(first("JOIN_YMD")["operation"], "FORMAT")
        self.assertEqual(first("JOIN_YMD")["parameters"]["parse_pattern"], "%Y%m%d")
        # 코드 도메인 부분집합 -> COPY
        self.assertEqual(by["SMS_AGREE_YN"].record["decision"], "MIGRATE")
        self.assertEqual(first("SMS_AGREE_YN")["target_column"], "SMS_AGR_YN")
        self.assertEqual(first("SMS_AGREE_YN")["parameters"]["allowed_values"], ["N", "Y"])
        # 정밀도 수용 DECIMAL -> COPY
        self.assertEqual(by["ORDER_AMT"].record["decision"], "MIGRATE")
        self.assertEqual(first("ORDER_AMT")["operation"], "COPY")
        # 코드 대응표 없음 -> REVIEW (LOOKUP 추측 금지)
        self.assertEqual(by["MEMBER_GRADE"].record["decision"], "REVIEW")
        self.assertIn("CODE_MAPPING_MISSING", by["MEMBER_GRADE"].review_codes)
        self.assertEqual(first("MEMBER_GRADE")["operation"], "REVIEW")
        # Target PK -> REVIEW
        self.assertEqual(by["ORDER_NO"].record["decision"], "REVIEW")
        self.assertIn("TARGET_KEY_POLICY_UNDEFINED", by["ORDER_NO"].review_codes)
        self.assertEqual(by["MEMBER_NO"].record["decision"], "REVIEW")
        # 길이 초과 -> REVIEW
        self.assertEqual(by["ORDER_MEMO"].record["decision"], "REVIEW")
        self.assertIn("LENGTH_OVERFLOW", by["ORDER_MEMO"].review_codes)
        # 자료형·설명 미확인 -> REVIEW, targets=[]
        self.assertEqual(by["RAW_FIELD_X"].record["decision"], "REVIEW")
        self.assertEqual(by["RAW_FIELD_X"].record["targets"], [])
        self.assertIn("NO_SOURCE_DESCRIPTION", by["RAW_FIELD_X"].review_codes)
        # 명시 제외 규칙 -> EXCLUDE
        self.assertEqual(by["DEL_FLAG"].record["decision"], "EXCLUDE")
        self.assertEqual(by["DEL_FLAG"].record["targets"], [])
        # 연산 범위: 이 기준선은 COPY/FORMAT/REVIEW 외 연산을 생성하지 않는다.
        ops = {t["operation"] for d in res.decisions for t in d.record["targets"]}
        self.assertTrue(ops <= {"COPY", "FORMAT", "REVIEW"})

    def test_no_exclusion_without_rule(self):
        res = self._run(self.out)
        self.assertNotIn("EXCLUDE", {d.record["decision"] for d in res.decisions})

    def test_validator_passes_and_contract(self):
        res = self._run(self.out)
        v = vo.validate(self.src, self.tgt, res.out_files["mapping_draft"], res.out_files["candidates"],
                        [ROOT / "maps_exp1_baseline.py"], 3)
        failed = [c for c in v["checks"] if not c["passed"]]
        self.assertEqual(failed, [])
        data = json.loads(res.out_files["mapping_draft"].read_text(encoding="utf-8"))
        self.assertEqual(len(data), 10)
        self.assertEqual(list(data[0].keys()), list(mb.OUTPUT_FIELDS))

    def test_determinism(self):
        r1 = self._run(self.tmp / "o1")
        r2 = self._run(self.tmp / "o2")
        for name in ("mapping_draft", "candidates", "decision_trace"):
            self.assertEqual(r1.out_files[name].read_bytes(), r2.out_files[name].read_bytes(), name)

    def test_candidates_are_marked(self):
        res = self._run(self.out)
        with open(res.out_files["candidates"], encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertTrue(rows)
        self.assertTrue(all(r["note"] == mb.CANDIDATE_NOTE for r in rows))
        self.assertTrue(all(int(r["rank"]) <= 3 for r in rows))

    def test_input_files_unchanged(self):
        before = {p.name: mb.sha256_file(p) for p in (self.src, self.tgt, self.pro)}
        self._run(self.out)
        after = {p.name: mb.sha256_file(p) for p in (self.src, self.tgt, self.pro)}
        self.assertEqual(before, after)

    def test_cli_main(self):
        rc = mb.main(["--source", str(self.src), "--target", str(self.tgt), "--protocol", str(self.pro),
                      "--out-dir", str(self.out), "--expect-source-rows", "10", "--expect-target-rows", "8"])
        self.assertEqual(rc, 0)
        for name in ("mapping_draft.json", "candidates.csv", "decision_trace.csv", "report.txt",
                     "validation_result.json", "run_manifest.json"):
            self.assertTrue((self.out / name).is_file(), name)
        manifest = (self.out / "run_manifest.json").read_text(encoding="utf-8")
        self.assertNotIn(str(self.tmp), manifest)  # 경로 미기록


class TestValidatorDetectsErrors(SyntheticFixture):
    def setUp(self):
        super().setUp()
        self.res = mb.generate(self.src, self.tgt, self.pro, self.out)
        self.path = self.res.out_files["mapping_draft"]
        self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def _validate(self, data):
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        v = vo.validate(self.src, self.tgt, self.path)
        return {c["name"]: c["passed"] for c in v["checks"]}

    def test_missing_source(self):
        r = self._validate(self.data[:-1])
        self.assertFalse(r["source_no_missing"])
        self.assertFalse(r["count_matches_source"])

    def test_duplicate_source(self):
        r = self._validate(self.data + [self.data[0]])
        self.assertFalse(r["source_no_duplicates"])

    def test_invalid_target_reference(self):
        d = json.loads(json.dumps(self.data))
        d[0]["decision"] = "MIGRATE"
        d[0]["targets"] = [{"target_table": "MEMBER", "target_column": "NOT_EXIST", "operation": "COPY",
                            "parameters": {}, "exception_policy": ""}]
        self.assertFalse(self._validate(d)["target_reference_valid"])

    def test_bad_enums_and_consistency(self):
        d = json.loads(json.dumps(self.data))
        d[0]["decision"] = "MAYBE"
        d[1]["decision"] = "MIGRATE"
        d[1]["targets"] = []
        r = self._validate(d)
        self.assertFalse(r["decision_enum"])
        self.assertFalse(r["decision_target_consistency"])

    def test_code_fence(self):
        self.path.write_text("```\n" + json.dumps(self.data) + "\n```", encoding="utf-8")
        v = vo.validate(self.src, self.tgt, self.path)
        self.assertFalse(v["passed"])

    def test_hardcoding_detector(self):
        fake = self.tmp / "fake_algo.py"
        fake.write_text("ANSWER = {'MEMBER_NAME': 'MBR_NM'}\nimport socket\n", encoding="utf-8")
        v = vo.validate(self.src, self.tgt, self.path, None, [fake])
        r = {c["name"]: c["passed"] for c in v["checks"]}
        self.assertFalse(r["no_hardcoded_identifiers"])
        self.assertFalse(r["no_network_or_db_imports"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
