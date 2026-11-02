#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MAPS 실험 1 - 출력 독립 검증기

생성 프로그램(maps_exp1_baseline.py)을 import 하지 않고, 입력 CSV와 출력 파일을 디스크에서 다시 읽어 검사한다.
- JSON 파싱·구조·필드·결정값·연산값
- Source 식별자 1:1 대응(누락·중복·미존재), Target 참조 유효성
- 결정과 targets 의 일관성
- candidates.csv 구조·참조
- 알고리즘 소스의 하드코딩(입력 식별자 문자열 리터럴) 및 네트워크 모듈 import 정적 검사
정답 대조는 수행하지 않는다.
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

V_OUTPUT_FIELDS = ["source_system", "source_table", "source_column", "decision", "targets", "reason",
                   "missing_information"]
V_TARGET_FIELDS = ["target_table", "target_column", "operation", "parameters", "exception_policy"]
V_DECISIONS = {"MIGRATE", "EXCLUDE", "REVIEW"}
V_OPERATIONS = {"COPY", "FORMAT", "LOOKUP", "EXPLODE", "CONSTANT", "CUSTOMER_MATCH", "GENERATE_ID", "REVIEW"}
V_CANDIDATE_HEADER = ["source_system", "source_table", "source_column", "rank", "target_table", "target_column",
                      "score_final", "score_text", "score_name_char", "score_name_abbrev", "score_desc",
                      "desc_available", "table_affinity", "type_relation", "note"]
FORBIDDEN_MODULES = {"socket", "urllib", "http", "requests", "httpx", "aiohttp", "ftplib", "smtplib",
                     "subprocess", "openai", "anthropic", "azure", "boto3", "pyodbc", "psycopg2", "sqlalchemy"}


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [h.strip() for h in (reader.fieldnames or [])]
        return [{k: (v or "").strip() for k, v in r.items() if k is not None} for r in reader]


class Checks:
    def __init__(self) -> None:
        self.items: List[Dict[str, object]] = []

    def add(self, name: str, passed: bool, detail: str) -> None:
        self.items.append({"name": name, "passed": bool(passed), "detail": detail})


def _sample(xs: Sequence[object], n: int = 5) -> str:
    xs = list(xs)
    s = ", ".join(str(x) for x in xs[:n])
    return s + (f" 외 {len(xs) - n}건" if len(xs) > n else "")


def check_algorithm_sources(paths: Sequence[Path], identifiers: Set[str], chk: Checks) -> None:
    hits: List[str] = []
    bad_imports: List[str] = []
    for p in paths:
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=p.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in identifiers:
                hits.append(f"{p.name}:{node.lineno} '{node.value}'")
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] in FORBIDDEN_MODULES:
                        bad_imports.append(f"{p.name}:{node.lineno} {a.name}")
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in FORBIDDEN_MODULES:
                    bad_imports.append(f"{p.name}:{node.lineno} {node.module}")
    chk.add("no_hardcoded_identifiers", not hits,
            "알고리즘 소스에 입력 식별자(시스템·테이블·컬럼명) 문자열 리터럴 없음" if not hits
            else f"발견 {len(hits)}건: {_sample(hits)}")
    chk.add("no_network_or_db_imports", not bad_imports,
            "네트워크·외부 API·DB 모듈 import 없음" if not bad_imports else f"발견: {_sample(bad_imports)}")


def validate(source_path: Path, target_path: Path, mapping_path: Path, candidates_path: Optional[Path] = None,
             algorithm_paths: Sequence[Path] = (), top_k: int = 3) -> Dict[str, object]:
    chk = Checks()
    src_rows = _read_csv(source_path)
    tgt_rows = _read_csv(target_path)
    src_keys = [(r["SOURCE_SYSTEM"], r["SOURCE_TABLE"], r["SOURCE_COLUMN"]) for r in src_rows]
    src_set = set(src_keys)
    tgt_set = {(r["TABLE_NAME"], r["COLUMN_NAME"]) for r in tgt_rows}

    raw = mapping_path.read_text(encoding="utf-8")
    chk.add("no_code_fence", "```" not in raw, "코드펜스 없음" if "```" not in raw else "코드펜스 포함")
    try:
        data = json.loads(raw)
        chk.add("json_parse", True, "JSON 파싱 성공")
    except json.JSONDecodeError as e:
        chk.add("json_parse", False, f"JSON 파싱 실패: {e}")
        return {"passed": False, "checks": chk.items, "summary": {}}

    if not isinstance(data, list):
        chk.add("root_is_array", False, f"최상위가 배열이 아님({type(data).__name__})")
        return {"passed": False, "checks": chk.items, "summary": {}}
    chk.add("root_is_array", True, "최상위 배열")
    chk.add("count_matches_source", len(data) == len(src_rows),
            f"출력 {len(data)}건 / Source {len(src_rows)}행")

    field_err, type_err, dec_err, op_err, tfield_err, tref_err, dup_pair_err, cons_err, reason_err = \
        [], [], [], [], [], [], [], [], []
    out_keys: List[Tuple[str, str, str]] = []
    dec_count: Dict[str, int] = {}
    op_count: Dict[str, int] = {}
    for i, obj in enumerate(data):
        if not isinstance(obj, dict) or set(obj.keys()) != set(V_OUTPUT_FIELDS):
            field_err.append(i)
            continue
        if not all(isinstance(obj[k], str) for k in ("source_system", "source_table", "source_column",
                                                      "decision", "reason")) \
                or not isinstance(obj["targets"], list) \
                or not isinstance(obj["missing_information"], list) \
                or not all(isinstance(m, str) for m in obj["missing_information"]):
            type_err.append(i)
            continue
        key = (obj["source_system"], obj["source_table"], obj["source_column"])
        out_keys.append(key)
        d = obj["decision"]
        dec_count[d] = dec_count.get(d, 0) + 1
        if d not in V_DECISIONS:
            dec_err.append(i)
        if not obj["reason"].strip():
            reason_err.append(i)
        pairs = set()
        ops = []
        for t in obj["targets"]:
            if not isinstance(t, dict) or set(t.keys()) != set(V_TARGET_FIELDS) \
                    or not isinstance(t.get("parameters"), dict) or not isinstance(t.get("exception_policy"), str):
                tfield_err.append(i)
                continue
            op = t["operation"]
            ops.append(op)
            op_count[op] = op_count.get(op, 0) + 1
            if op not in V_OPERATIONS:
                op_err.append(i)
            pair = (t["target_table"], t["target_column"])
            if pair not in tgt_set:
                tref_err.append(f"{i}:{pair[0]}.{pair[1]}")
            if pair in pairs:
                dup_pair_err.append(i)
            pairs.add(pair)
        if d == "MIGRATE" and (not ops or any(o == "REVIEW" for o in ops)):
            cons_err.append(f"{i}:MIGRATE 인데 targets 없음 또는 REVIEW 연산")
        if d == "EXCLUDE" and ops:
            cons_err.append(f"{i}:EXCLUDE 인데 targets 존재")
        if d == "REVIEW" and any(o != "REVIEW" for o in ops):
            cons_err.append(f"{i}:REVIEW 인데 확정 연산 존재")

    chk.add("object_fields_exact", not field_err, "모든 객체 필드 일치" if not field_err
            else f"필드 불일치 객체 index {_sample(field_err)}")
    chk.add("field_types", not type_err, "필드 자료형 정상" if not type_err else f"오류 index {_sample(type_err)}")
    chk.add("decision_enum", not dec_err, "결정값 MIGRATE/EXCLUDE/REVIEW 만 사용" if not dec_err
            else f"오류 index {_sample(dec_err)}")
    chk.add("operation_enum", not op_err, "연산값 계약 목록 내" if not op_err else f"오류 index {_sample(op_err)}")
    chk.add("target_fields_exact", not tfield_err, "targets 원소 필드 일치" if not tfield_err
            else f"오류 index {_sample(tfield_err)}")
    chk.add("target_reference_valid", not tref_err, "Target 미존재 참조 0건" if not tref_err
            else f"미존재 참조 {len(tref_err)}건: {_sample(tref_err)}")
    chk.add("no_duplicate_target_pair", not dup_pair_err, "Source 내 중복 Target 쌍 없음" if not dup_pair_err
            else f"오류 index {_sample(dup_pair_err)}")
    chk.add("decision_target_consistency", not cons_err, "결정·연산 일관" if not cons_err
            else f"불일치 {len(cons_err)}건: {_sample(cons_err)}")
    chk.add("reason_nonempty", not reason_err, "판단 근거 모두 기재" if not reason_err
            else f"빈 근거 index {_sample(reason_err)}")

    unknown = [k for k in out_keys if k not in src_set]
    dups = sorted({k for k in out_keys if out_keys.count(k) > 1})
    missing = [k for k in src_keys if k not in set(out_keys)]
    chk.add("source_identifier_exists", not unknown, "출력 Source 식별자 모두 입력에 존재" if not unknown
            else f"입력에 없는 식별자 {len(unknown)}건: {_sample(['.'.join(k) for k in unknown])}")
    chk.add("source_no_duplicates", not dups, "Source 중복 0건" if not dups
            else f"중복 {len(dups)}건: {_sample(['.'.join(k) for k in dups])}")
    chk.add("source_no_missing", not missing, "Source 누락 0건" if not missing
            else f"누락 {len(missing)}건: {_sample(['.'.join(k) for k in missing])}")
    chk.add("source_order_preserved", out_keys == src_keys, "입력 순서 유지" if out_keys == src_keys
            else "입력 순서와 다름")

    cand_summary: Dict[str, int] = {}
    if candidates_path is not None:
        with open(candidates_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
            rows = list(reader)
        chk.add("candidates_header", header == V_CANDIDATE_HEADER, "candidates.csv 헤더 일치"
                if header == V_CANDIDATE_HEADER else f"헤더 불일치: {header}")
        errs: List[str] = []
        per_src: Dict[Tuple[str, str, str], List[int]] = {}
        if header == V_CANDIDATE_HEADER:
            for ln, r in enumerate(rows, start=2):
                rec = dict(zip(header, r))
                k = (rec["source_system"], rec["source_table"], rec["source_column"])
                if k not in src_set:
                    errs.append(f"{ln}행 Source 미존재")
                if (rec["target_table"], rec["target_column"]) not in tgt_set:
                    errs.append(f"{ln}행 Target 미존재")
                try:
                    rank = int(rec["rank"])
                    float(rec["score_final"])
                except ValueError:
                    errs.append(f"{ln}행 숫자 형식 오류")
                    continue
                per_src.setdefault(k, []).append(rank)
                if "확정 매핑 아님" not in rec["note"]:
                    errs.append(f"{ln}행 후보 표시 누락")
            for k, ranks in per_src.items():
                if ranks != list(range(1, len(ranks) + 1)) or len(ranks) > top_k:
                    errs.append(f"{'.'.join(k)} 순위 오류")
        chk.add("candidates_valid", not errs, f"후보 {len(rows)}행, Source {len(per_src)}개, 최대 {top_k}개/Source"
                if not errs else f"오류 {len(errs)}건: {_sample(errs)}")
        cand_summary = {"candidate_rows": len(rows), "sources_with_candidates": len(per_src)}

    if algorithm_paths:
        idents = {r["SOURCE_SYSTEM"] for r in src_rows} | {r["SOURCE_TABLE"] for r in src_rows} | \
                 {r["SOURCE_COLUMN"] for r in src_rows} | {r["TABLE_NAME"] for r in tgt_rows} | \
                 {r["COLUMN_NAME"] for r in tgt_rows}
        idents.discard("")
        check_algorithm_sources(algorithm_paths, idents, chk)

    passed = all(c["passed"] for c in chk.items)
    summary = {"output_objects": len(data), "source_rows": len(src_rows), "target_rows": len(tgt_rows),
               "decision_counts": dict(sorted(dec_count.items())), "operation_counts": dict(sorted(op_count.items())),
               **cand_summary}
    return {"passed": passed, "checks": chk.items, "summary": summary}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="MAPS 실험 1 출력 독립 검증기")
    ap.add_argument("--source", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--mapping", required=True)
    ap.add_argument("--candidates", default=None)
    ap.add_argument("--algorithm", action="append", default=[], help="하드코딩 정적 검사 대상 소스(반복 가능)")
    ap.add_argument("--top-k", type=int, default=3)
    a = ap.parse_args(argv)
    res = validate(Path(a.source), Path(a.target), Path(a.mapping),
                   Path(a.candidates) if a.candidates else None, [Path(p) for p in a.algorithm], a.top_k)
    for c in res["checks"]:
        print(f"[{'PASS' if c['passed'] else 'FAIL'}] {c['name']}: {c['detail']}")
    print(json.dumps(res["summary"], ensure_ascii=False))
    print("전체:", "PASS" if res["passed"] else "FAIL")
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
