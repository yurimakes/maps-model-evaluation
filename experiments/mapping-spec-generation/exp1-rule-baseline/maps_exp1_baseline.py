#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MAPS 실험 1 - 메타데이터 기반 매핑정의서 초안 생성 Python 기준선

- 입력: source_metadata.csv, target_schema.csv, OUTPUT_CONTRACT.txt
- 출력: mapping_draft.json, candidates.csv, decision_trace.csv, report.txt,
        validation_result.json, run_manifest.json
- 외부 API, 네트워크, DB 접속을 사용하지 않는다.
- 개별 Source-Target 정답을 코드에 포함하지 않는다. 모든 판단은 아래의 범용 규칙으로만 수행한다.
  (1) 이름 문자 n-gram TF-IDF 유사도
  (2) 약어 부분수열(subsequence) 토큰 매칭
  (3) 설명 문자 n-gram TF-IDF 유사도
  (4) 자료형 관계 계수
  (5) 테이블 단위 친화도(라벨 없이 컬럼 유사도를 집계한 값)
- 유사도 점수는 정답 확률이나 정확도가 아니다.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ALGORITHM_VERSION = "exp1-baseline-1.0.0"

SOURCE_REQUIRED_COLUMNS = (
    "SOURCE_SYSTEM", "SOURCE_TABLE", "TABLE_NAME_ASSUMED", "SOURCE_COLUMN",
    "DATA_TYPE", "COLUMN_DESCRIPTION", "NULLABLE_YN", "PK_YN", "BUSINESS_KEY_YN",
    "CODE_YN", "PII_YN", "FORMAT_HINT", "SOURCE_CODE_HINT",
)
TARGET_REQUIRED_COLUMNS = ("TABLE_NAME", "COLUMN_NAME", "DATA_TYPE", "KEY", "NULLABLE", "DESCRIPTION")
SOURCE_FLAG_COLUMNS = ("TABLE_NAME_ASSUMED", "NULLABLE_YN", "PK_YN", "BUSINESS_KEY_YN", "CODE_YN", "PII_YN")
EXCLUSION_REQUIRED_COLUMNS = ("SOURCE_SYSTEM", "SOURCE_TABLE", "SOURCE_COLUMN", "EXCLUDE_REASON")

OUTPUT_FIELDS = ("source_system", "source_table", "source_column", "decision", "targets", "reason",
                 "missing_information")
TARGET_FIELDS = ("target_table", "target_column", "operation", "parameters", "exception_policy")
DECISIONS = ("MIGRATE", "EXCLUDE", "REVIEW")
OPERATIONS = ("COPY", "FORMAT", "LOOKUP", "EXPLODE", "CONSTANT", "CUSTOMER_MATCH", "GENERATE_ID", "REVIEW")
AUTO_OPERATIONS = ("COPY", "FORMAT")  # 이 기준선이 자동 확정할 수 있는 연산은 두 가지뿐이다.

CANDIDATE_NOTE = "후보(확정 매핑 아님)"


# ---------------------------------------------------------------------------
# 설정 (실제 입력 실행 전에 고정. 변경 시 ALGORITHM_VERSION 을 올린다.)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Config:
    top_k: int = 3
    candidate_min_score: float = 0.05
    # Target 확정 게이트
    accept_score: float = 0.45
    min_margin: float = 0.08
    min_desc_similarity: float = 0.20
    min_name_evidence: float = 0.20
    # 텍스트 점수 가중치 (사용 가능한 성분만으로 재정규화)
    weight_name_char: float = 0.35
    weight_name_abbrev: float = 0.25
    weight_desc: float = 0.40
    # 테이블 친화도: final = text * type_factor * (floor + (1-floor) * affinity)
    table_affinity_floor: float = 0.6
    # 자료형 관계 계수
    type_factor_safe: float = 1.0
    type_factor_rule_needed: float = 0.9
    type_factor_incompatible: float = 0.7
    type_factor_unknown: float = 1.0
    # 약어 매칭
    abbrev_min_ratio: float = 0.3
    abbrev_partial_credit: float = 0.8
    # TF-IDF n-gram 범위
    name_ngram_min: int = 2
    name_ngram_max: int = 4
    desc_ngram_min: int = 2
    desc_ngram_max: int = 3


class InputError(Exception):
    """입력 검사 실패. 실행을 중단하고 이유를 표시한다."""


# ---------------------------------------------------------------------------
# 자료형 해석
# ---------------------------------------------------------------------------
TYPE_FAMILY = {
    "VARCHAR": "STRING", "VARCHAR2": "STRING", "NVARCHAR": "STRING", "CHAR": "STRING", "NCHAR": "STRING",
    "STRING": "STRING", "PICKLIST": "STRING",
    "TEXT": "TEXT", "LONG TEXT AREA": "TEXT", "CLOB": "TEXT",
    "SMALLINT": "INTEGER", "INT": "INTEGER", "INTEGER": "INTEGER", "BIGINT": "INTEGER",
    "DECIMAL": "DECIMAL", "NUMERIC": "DECIMAL", "NUMBER": "DECIMAL",
    "DATE": "DATE",
    "TIMESTAMP": "TIMESTAMP", "DATETIME": "TIMESTAMP",
    "BOOLEAN": "BOOLEAN", "BOOL": "BOOLEAN",
}
INTEGER_DIGITS = {"SMALLINT": 5, "INT": 10, "INTEGER": 10, "BIGINT": 19}
_TYPE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 ]*?)\s*(?:\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\))?\s*$")


@dataclass(frozen=True)
class ParsedType:
    raw: str
    base: str
    family: str
    length: Optional[int] = None
    precision: Optional[int] = None
    scale: Optional[int] = None


def parse_data_type(raw: str) -> ParsedType:
    text = (raw or "").strip()
    if not text:
        return ParsedType(raw="", base="", family="UNKNOWN")
    m = _TYPE_RE.match(text)
    if not m:
        return ParsedType(raw=text, base=text.upper(), family="UNKNOWN")
    base = re.sub(r"\s+", " ", m.group(1)).upper()
    family = TYPE_FAMILY.get(base, "UNKNOWN")
    a = int(m.group(2)) if m.group(2) else None
    b = int(m.group(3)) if m.group(3) else None
    if family == "DECIMAL":
        return ParsedType(text, base, family, precision=a, scale=(b if b is not None else (0 if a is not None else None)))
    if family == "STRING":
        return ParsedType(text, base, family, length=a)
    return ParsedType(text, base, family)


# ---------------------------------------------------------------------------
# 입력 모델
# ---------------------------------------------------------------------------
@dataclass
class SourceCol:
    index: int
    system: str
    table: str
    column: str
    table_name_assumed: str
    data_type: str
    description: str
    nullable: str
    pk: str
    business_key: str
    code: str
    pii: str
    format_hint: str
    code_hint: str
    ptype: ParsedType = field(default=None)  # type: ignore[assignment]
    name_tokens: List[str] = field(default_factory=list)

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.system, self.table, self.column)


@dataclass
class TargetCol:
    index: int
    table: str
    column: str
    data_type: str
    key_raw: str
    nullable: str
    description: str
    ptype: ParsedType = field(default=None)  # type: ignore[assignment]
    name_tokens: List[str] = field(default_factory=list)

    @property
    def key(self) -> Tuple[str, str]:
        return (self.table, self.column)

    @property
    def key_set(self) -> Set[str]:
        return {k.strip().upper() for k in self.key_raw.split(",") if k.strip()}


# ---------------------------------------------------------------------------
# 정규화
# ---------------------------------------------------------------------------
_CAMEL_ACRONYM = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_LOWER_UPPER = re.compile(r"([a-z0-9])([A-Z])")
_NON_WORD = re.compile(r"[^0-9A-Za-z\uac00-\ud7a3]+")


def split_identifier(name: str) -> List[str]:
    """대소문자 경계, 언더스코어, 특수문자로 식별자를 분해한다. 1글자 토큰은 제외한다."""
    s = _CAMEL_ACRONYM.sub(r"\1 \2", name or "")
    s = _CAMEL_LOWER_UPPER.sub(r"\1 \2", s)
    s = _NON_WORD.sub(" ", s)
    return [t.lower() for t in s.split() if len(t) >= 2]


def normalize_description(text: str) -> str:
    """설명 문자열: 소문자화, 구두점 제거, 공백 제거(한국어 띄어쓰기 차이 흡수)."""
    s = _NON_WORD.sub(" ", (text or "").lower())
    return re.sub(r"\s+", "", s)


def is_subsequence(short: str, long_: str) -> bool:
    it = iter(long_)
    return all(ch in it for ch in short)


def token_match(a: str, b: str, cfg: Config) -> float:
    if a == b:
        return 1.0
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 2 or short[0] != long_[0]:
        return 0.0
    if len(short) / len(long_) < cfg.abbrev_min_ratio:
        return 0.0
    return cfg.abbrev_partial_credit if is_subsequence(short, long_) else 0.0


def abbreviation_score(src_tokens: Sequence[str], tgt_tokens: Sequence[str], cfg: Config) -> float:
    """토큰 단위 약어 매칭의 대칭 soft-Dice 점수 (0~1)."""
    if not src_tokens or not tgt_tokens:
        return 0.0
    s1 = sum(max(token_match(a, b, cfg) for b in tgt_tokens) for a in src_tokens)
    s2 = sum(max(token_match(a, b, cfg) for a in src_tokens) for b in tgt_tokens)
    return (s1 + s2) / (len(src_tokens) + len(tgt_tokens))


# ---------------------------------------------------------------------------
# 형식 힌트·코드 도메인 해석
# ---------------------------------------------------------------------------
_DATE_HINT_RE = re.compile(
    r"^YYYY(?P<ds>[-/.]?)MM(?P=ds)DD(?:(?P<dts>[ T]?)HH(?P<ts>:?)(?:MM|MI)(?:(?P<sec>(?P=ts)SS))?)?$"
)


def parse_date_hint(hint: str) -> Optional[Dict[str, str]]:
    """명시적 날짜/일시 형식 힌트만 해석한다. 해석 불가하면 None."""
    h = (hint or "").strip().upper()
    if not h:
        return None
    m = _DATE_HINT_RE.match(h)
    if not m:
        return None
    ds = m.group("ds") or ""
    pattern = f"%Y{ds}%m{ds}%d"
    kind = "DATE"
    if "HH" in h:
        ts = m.group("ts") or ""
        pattern += f"{m.group('dts') or ''}%H{ts}%M"
        if m.group("sec") is not None:
            pattern += f"{ts}%S"
        kind = "TIMESTAMP"
    return {"kind": kind, "pattern": pattern, "hint": (hint or "").strip()}


_ENUM_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Z0-9_]+(?:/[A-Z0-9_]+)+)(?![A-Za-z0-9_])")
_OPEN_SET_RE = re.compile(r"(^|[\s(])(등|etc\.?|기타)($|[\s.,)])", re.IGNORECASE)


def parse_target_enum_domain(description: str) -> Optional[Set[str]]:
    """Target 설명에 'A/B/C' 형태의 닫힌 허용값 목록이 있으면 집합으로 반환한다.
    '등', 'etc' 같은 열린 목록 표지가 있으면 닫힌 집합으로 보지 않는다."""
    d = (description or "").strip()
    if not d or _OPEN_SET_RE.search(d):
        return None
    found = _ENUM_RE.findall(d)
    if len(found) != 1:
        return None
    return set(found[0].split("/"))


def parse_source_code_hint(hint: str) -> Optional[Set[str]]:
    values = [v.strip() for v in (hint or "").split("|") if v.strip()]
    return set(values) if values else None


def is_code_like_target(t: TargetCol) -> bool:
    """명명 규칙(_CD/_YN 접미)이나 설명의 '코드' 표기, 닫힌 허용값 목록으로 코드성 컬럼을 판정한다."""
    last = t.name_tokens[-1] if t.name_tokens else ""
    return last in ("cd", "yn") or "코드" in t.description or parse_target_enum_domain(t.description) is not None


# ---------------------------------------------------------------------------
# 자료형 관계
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TypeVerdict:
    relation: str          # SAFE / RULE_NEEDED / INCOMPATIBLE / UNKNOWN
    operation: str         # COPY / FORMAT / REVIEW
    parameters: Dict[str, object]
    note: str
    review_code: str = ""  # REVIEW 인 경우 분류 코드


_CONVERTIBLE_PAIRS = {
    ("STRING", "TEXT"), ("TEXT", "STRING"),
    ("INTEGER", "DECIMAL"), ("DECIMAL", "INTEGER"),
    ("DATE", "TIMESTAMP"), ("TIMESTAMP", "DATE"),
    ("BOOLEAN", "STRING"), ("STRING", "BOOLEAN"),
}


def type_verdict(src: SourceCol, tgt: TargetCol) -> TypeVerdict:
    st, tt = src.ptype, tgt.ptype
    sf, tf = st.family, tt.family
    base_params = {"source_data_type": st.raw, "target_data_type": tt.raw}
    if sf == "UNKNOWN" or tf == "UNKNOWN":
        what = "Source" if sf == "UNKNOWN" else "Target"
        return TypeVerdict("UNKNOWN", "REVIEW", {}, f"{what} 자료형 미확인 또는 해석 불가", "TYPE_UNKNOWN")

    if sf == tf:
        if sf == "STRING":
            if st.length is not None and tt.length is not None and st.length > tt.length:
                return TypeVerdict("RULE_NEEDED", "REVIEW", {},
                                   f"길이 초과 가능: {st.raw} -> {tt.raw}", "LENGTH_OVERFLOW")
            return TypeVerdict("SAFE", "COPY", base_params, "동일 문자 계열, 길이 수용")
        if sf == "DECIMAL":
            if (tt.precision is not None and st.precision is not None):
                s_int = st.precision - (st.scale or 0)
                t_int = tt.precision - (tt.scale or 0)
                if s_int > t_int or (st.scale or 0) > (tt.scale or 0):
                    return TypeVerdict("RULE_NEEDED", "REVIEW", {},
                                       f"정밀도/소수자릿수 축소: {st.raw} -> {tt.raw}", "PRECISION_LOSS")
            return TypeVerdict("SAFE", "COPY", base_params, "동일 숫자 계열, 정밀도 수용")
        if sf == "INTEGER":
            if INTEGER_DIGITS.get(st.base, 10) > INTEGER_DIGITS.get(tt.base, 10):
                return TypeVerdict("RULE_NEEDED", "REVIEW", {},
                                   f"정수 범위 축소: {st.raw} -> {tt.raw}", "PRECISION_LOSS")
            return TypeVerdict("SAFE", "COPY", base_params, "동일 정수 계열, 범위 수용")
        return TypeVerdict("SAFE", "COPY", base_params, f"동일 자료형 계열({sf})")

    if sf == "STRING" and tf == "TEXT":
        return TypeVerdict("SAFE", "COPY", base_params, "문자열 -> TEXT 확장")
    if sf == "INTEGER" and tf == "DECIMAL":
        digits = INTEGER_DIGITS.get(st.base, 10)
        if tt.precision is None or (tt.precision - (tt.scale or 0)) >= digits:
            return TypeVerdict("SAFE", "COPY", base_params, "정수 -> DECIMAL 정밀도 수용")
        return TypeVerdict("RULE_NEEDED", "REVIEW", {}, f"정수 범위 > DECIMAL 정수부: {st.raw} -> {tt.raw}",
                           "PRECISION_LOSS")
    if sf == "STRING" and tf in ("DATE", "TIMESTAMP"):
        hint = parse_date_hint(src.format_hint)
        if hint is None:
            return TypeVerdict("RULE_NEEDED", "REVIEW", {},
                               f"문자열 -> {tf} 변환에 필요한 명시적 입력 형식(FORMAT_HINT) 없음", "FORMAT_UNKNOWN")
        if hint["kind"] == tf:
            params = {"source_format_hint": hint["hint"], "parse_pattern": hint["pattern"],
                      "source_data_type": st.raw, "target_data_type": tt.raw}
            return TypeVerdict("SAFE", "FORMAT", params, f"명시 형식 {hint['hint']} -> {tf}")
        return TypeVerdict("RULE_NEEDED", "REVIEW", {},
                           f"형식 정밀도 불일치: {hint['hint']}({hint['kind']}) -> {tf}", "FORMAT_PRECISION_MISMATCH")
    if (sf, tf) in _CONVERTIBLE_PAIRS or tf in ("STRING", "TEXT") or sf in ("STRING", "TEXT"):
        return TypeVerdict("RULE_NEEDED", "REVIEW", {}, f"자료형 변환 규칙 미정의: {sf} -> {tf}",
                           "TYPE_CONVERSION_UNDEFINED")
    return TypeVerdict("INCOMPATIBLE", "REVIEW", {}, f"자료형 계열 비호환: {sf} -> {tf}", "TYPE_INCOMPATIBLE")


def type_factor(relation: str, cfg: Config) -> float:
    return {
        "SAFE": cfg.type_factor_safe,
        "RULE_NEEDED": cfg.type_factor_rule_needed,
        "INCOMPATIBLE": cfg.type_factor_incompatible,
        "UNKNOWN": cfg.type_factor_unknown,
    }[relation]


# ---------------------------------------------------------------------------
# 입력 읽기·검사
# ---------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv_rows(path: Path, required: Sequence[str], label: str) -> List[Dict[str, str]]:
    if not path.is_file():
        raise InputError(f"{label}: 파일을 찾을 수 없음 ({path.name})")
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise InputError(f"{label}: 빈 파일")
        header = [h.strip() for h in header]
        dups = sorted({h for h in header if header.count(h) > 1})
        if dups:
            raise InputError(f"{label}: 헤더 중복 {dups}")
        missing = [c for c in required if c not in header]
        if missing:
            raise InputError(f"{label}: 필수 헤더 누락 {missing}")
        rows: List[Dict[str, str]] = []
        for line_no, values in enumerate(reader, start=2):
            if not values or all(not v.strip() for v in values):
                continue  # 완전히 빈 줄은 무시
            if len(values) != len(header):
                raise InputError(f"{label}: {line_no}행 필드 수 불일치 (헤더 {len(header)}개, 행 {len(values)}개)")
            rows.append({h: v.strip() for h, v in zip(header, values)})
    return rows


def load_sources(path: Path) -> List[SourceCol]:
    rows = read_csv_rows(path, SOURCE_REQUIRED_COLUMNS, "Source 메타데이터")
    out: List[SourceCol] = []
    errors: List[str] = []
    for i, r in enumerate(rows):
        for c in ("SOURCE_SYSTEM", "SOURCE_TABLE", "SOURCE_COLUMN"):
            if not r[c]:
                errors.append(f"{i + 2}행 {c} 비어 있음")
        for c in SOURCE_FLAG_COLUMNS:
            if r[c] not in ("Y", "N", ""):
                errors.append(f"{i + 2}행 {c} 값이 Y/N/빈값이 아님")
        s = SourceCol(
            index=i, system=r["SOURCE_SYSTEM"], table=r["SOURCE_TABLE"], column=r["SOURCE_COLUMN"],
            table_name_assumed=r["TABLE_NAME_ASSUMED"], data_type=r["DATA_TYPE"],
            description=r["COLUMN_DESCRIPTION"], nullable=r["NULLABLE_YN"], pk=r["PK_YN"],
            business_key=r["BUSINESS_KEY_YN"], code=r["CODE_YN"], pii=r["PII_YN"],
            format_hint=r["FORMAT_HINT"], code_hint=r["SOURCE_CODE_HINT"],
        )
        s.ptype = parse_data_type(s.data_type)
        s.name_tokens = split_identifier(s.column)
        out.append(s)
    seen: Dict[Tuple[str, str, str], int] = {}
    for s in out:
        if s.key in seen:
            errors.append(f"Source 식별자 중복: {'.'.join(s.key)} ({seen[s.key] + 2}행, {s.index + 2}행)")
        else:
            seen[s.key] = s.index
    if errors:
        raise InputError("Source 메타데이터 검사 실패:\n  - " + "\n  - ".join(errors))
    return out


def load_targets(path: Path) -> List[TargetCol]:
    rows = read_csv_rows(path, TARGET_REQUIRED_COLUMNS, "Target 스키마")
    out: List[TargetCol] = []
    errors: List[str] = []
    for i, r in enumerate(rows):
        for c in ("TABLE_NAME", "COLUMN_NAME"):
            if not r[c]:
                errors.append(f"{i + 2}행 {c} 비어 있음")
        if r["NULLABLE"] not in ("Y", "N", ""):
            errors.append(f"{i + 2}행 NULLABLE 값이 Y/N/빈값이 아님")
        t = TargetCol(index=i, table=r["TABLE_NAME"], column=r["COLUMN_NAME"], data_type=r["DATA_TYPE"],
                      key_raw=r["KEY"], nullable=r["NULLABLE"], description=r["DESCRIPTION"])
        t.ptype = parse_data_type(t.data_type)
        t.name_tokens = split_identifier(t.column)
        out.append(t)
    seen: Dict[Tuple[str, str], int] = {}
    for t in out:
        if t.key in seen:
            errors.append(f"Target 식별자 중복: {'.'.join(t.key)} ({seen[t.key] + 2}행, {t.index + 2}행)")
        else:
            seen[t.key] = t.index
    if errors:
        raise InputError("Target 스키마 검사 실패:\n  - " + "\n  - ".join(errors))
    return out


def check_protocol(path: Path) -> None:
    if not path.is_file():
        raise InputError(f"출력 계약 파일을 찾을 수 없음 ({path.name})")
    text = path.read_text(encoding="utf-8-sig")
    missing = [t for t in (*OUTPUT_FIELDS, *TARGET_FIELDS, *DECISIONS, *OPERATIONS) if t not in text]
    if missing:
        raise InputError(f"출력 계약 파일과 프로그램의 필드/값 목록 불일치: {missing}")


def load_exclusion_rules(path: Optional[Path], sources: Sequence[SourceCol]) -> Dict[Tuple[str, str, str], str]:
    """선택 입력: 업무 담당자가 명시한 제외 규칙. 기본 실행에서는 사용하지 않는다."""
    if path is None:
        return {}
    rows = read_csv_rows(path, EXCLUSION_REQUIRED_COLUMNS, "제외 규칙")
    valid = {s.key for s in sources}
    rules: Dict[Tuple[str, str, str], str] = {}
    errors: List[str] = []
    for i, r in enumerate(rows):
        k = (r["SOURCE_SYSTEM"], r["SOURCE_TABLE"], r["SOURCE_COLUMN"])
        if k not in valid:
            errors.append(f"{i + 2}행: Source에 없는 식별자 {'.'.join(k)}")
        elif not r["EXCLUDE_REASON"]:
            errors.append(f"{i + 2}행: EXCLUDE_REASON 비어 있음")
        else:
            rules[k] = r["EXCLUDE_REASON"]
    if errors:
        raise InputError("제외 규칙 검사 실패:\n  - " + "\n  - ".join(errors))
    return rules


# ---------------------------------------------------------------------------
# 후보 점수화
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    target: TargetCol
    final: float
    text: float
    name_char: float
    name_abbrev: float
    desc: float
    desc_available: bool
    table_affinity: float
    type_relation: str


def _tfidf_similarity(src_texts: List[str], tgt_texts: List[str], analyzer: str,
                      ngram: Tuple[int, int]) -> np.ndarray:
    corpus = [t for t in src_texts + tgt_texts if t]
    if not corpus:
        return np.zeros((len(src_texts), len(tgt_texts)))
    vec = TfidfVectorizer(analyzer=analyzer, ngram_range=ngram, lowercase=True, sublinear_tf=True)
    vec.fit(corpus)
    S = vec.transform(src_texts)
    T = vec.transform(tgt_texts)
    return cosine_similarity(S, T)


def score_all(sources: Sequence[SourceCol], targets: Sequence[TargetCol],
              cfg: Config) -> List[List[Candidate]]:
    ns, nt = len(sources), len(targets)
    name_sim = _tfidf_similarity([" ".join(s.name_tokens) for s in sources],
                                 [" ".join(t.name_tokens) for t in targets],
                                 "char_wb", (cfg.name_ngram_min, cfg.name_ngram_max))
    desc_sim = _tfidf_similarity([normalize_description(s.description) for s in sources],
                                 [normalize_description(t.description) for t in targets],
                                 "char", (cfg.desc_ngram_min, cfg.desc_ngram_max))
    abbrev = np.zeros((ns, nt))
    text = np.zeros((ns, nt))
    desc_avail = np.zeros((ns, nt), dtype=bool)
    tf = np.ones((ns, nt))
    relations = [[""] * nt for _ in range(ns)]
    for i, s in enumerate(sources):
        for j, t in enumerate(targets):
            abbrev[i, j] = abbreviation_score(s.name_tokens, t.name_tokens, cfg)
            avail = bool(normalize_description(s.description)) and bool(normalize_description(t.description))
            desc_avail[i, j] = avail
            w_total = cfg.weight_name_char + cfg.weight_name_abbrev + (cfg.weight_desc if avail else 0.0)
            val = cfg.weight_name_char * name_sim[i, j] + cfg.weight_name_abbrev * abbrev[i, j]
            if avail:
                val += cfg.weight_desc * desc_sim[i, j]
            text[i, j] = val / w_total if w_total > 0 else 0.0
            rel = type_verdict(s, t).relation
            relations[i][j] = rel
            tf[i, j] = type_factor(rel, cfg)

    # 테이블 친화도: Source 테이블 그룹별로, 각 Target 테이블에 대한 '컬럼별 최대 텍스트 점수의 평균'
    group_of: Dict[Tuple[str, str], List[int]] = {}
    for i, s in enumerate(sources):
        group_of.setdefault((s.system, s.table), []).append(i)
    tgt_tables = sorted({t.table for t in targets})
    cols_of_table = {T: [j for j, t in enumerate(targets) if t.table == T] for T in tgt_tables}
    affinity = np.zeros((ns, nt))
    for g, rows in group_of.items():
        raw = {}
        for T, cols in cols_of_table.items():
            raw[T] = float(np.mean([text[i, cols].max() for i in rows]))
        mx = max(raw.values()) if raw else 0.0
        for T, cols in cols_of_table.items():
            a = raw[T] / mx if mx > 0 else 0.0
            for i in rows:
                affinity[i, cols] = a

    final = text * tf * (cfg.table_affinity_floor + (1.0 - cfg.table_affinity_floor) * affinity)

    result: List[List[Candidate]] = []
    for i in range(ns):
        order = sorted(range(nt), key=lambda j: (-round(float(final[i, j]), 12), targets[j].table, targets[j].column))
        cands = []
        for j in order[: cfg.top_k]:
            if final[i, j] < cfg.candidate_min_score:
                break
            cands.append(Candidate(
                target=targets[j], final=float(final[i, j]), text=float(text[i, j]),
                name_char=float(name_sim[i, j]), name_abbrev=float(abbrev[i, j]), desc=float(desc_sim[i, j]),
                desc_available=bool(desc_avail[i, j]), table_affinity=float(affinity[i, j]),
                type_relation=relations[i][j],
            ))
        result.append(cands)
    return result


# ---------------------------------------------------------------------------
# 결정 규칙
# ---------------------------------------------------------------------------
@dataclass
class Decision:
    record: Dict[str, object]
    review_codes: List[str]
    target_identified: bool


def _fmt(x: float) -> str:
    return f"{x:.3f}"


def _cand_label(c: Candidate) -> str:
    return f"{c.target.table}.{c.target.column}({_fmt(c.final)})"


def build_exception_policy(src: SourceCol, tgt: TargetCol, op: str, extra: Sequence[str],
                           missing: List[str]) -> str:
    notes: List[str] = list(extra)
    if src.nullable == "Y" and tgt.nullable == "N":
        notes.append("Source NULL 허용·Target NOT NULL: NULL 값 처리 기준 미제공")
        missing.append("NULL 값 처리 기준(Source NULL 허용, Target NOT NULL)")
    elif src.nullable == "":
        notes.append("Source NULL 허용 여부 미확인")
    if "UK" in tgt.key_set:
        notes.append("Target 고유키(UK): 적재 전 중복 검사 필요")
    if op == "COPY" and src.ptype.family == "STRING" and src.ptype.length is None and tgt.ptype.length is not None:
        notes.append(f"Source 길이 미확인: 적재 전 {tgt.ptype.raw} 길이 검사 필요")
    if op == "FORMAT":
        notes.append("명시 형식과 다른 값의 처리 기준 미제공(변환 실패 값 별도 집계 필요)")
        missing.append("형식 불일치 값 처리 기준")
    if not notes:
        return "입력 메타데이터에서 확인된 추가 제약 없음"
    return "; ".join(notes)


def decide(src: SourceCol, cands: List[Candidate], exclusions: Dict[Tuple[str, str, str], str],
           cfg: Config) -> Decision:
    missing: List[str] = []
    codes: List[str] = []
    if src.table_name_assumed == "Y":
        missing.append("실제 물리 테이블명 미확정(TABLE_NAME_ASSUMED=Y)")
    if not src.data_type:
        missing.append("Source 자료형(DATA_TYPE) 미확인")
    if not src.description:
        missing.append("Source 컬럼 설명(COLUMN_DESCRIPTION) 미확인")
    if src.pii == "Y":
        missing.append("개인정보(PII_YN=Y) 이관 처리 기준")

    base = {"source_system": src.system, "source_table": src.table, "source_column": src.column}

    # 1) 명시적 제외 규칙
    if src.key in exclusions:
        rec = {**base, "decision": "EXCLUDE", "targets": [],
               "reason": f"명시적 제외 규칙 적용: {exclusions[src.key]}",
               "missing_information": missing}
        return Decision(rec, ["EXPLICIT_EXCLUSION_RULE"], False)

    cand_text = ", ".join(_cand_label(c) for c in cands) if cands else "없음"

    # 2) Target 확정 게이트
    fails: List[str] = []
    if not src.description:
        fails.append("Source 설명 없음: 이름만으로 Target 확정 불가")
        codes.append("NO_SOURCE_DESCRIPTION")
    if not src.data_type:
        fails.append("Source 자료형 없음: 자료형 적합성 확인 불가")
        codes.append("NO_SOURCE_TYPE")
    if not cands:
        fails.append("최소 점수 이상 후보 없음")
        codes.append("NO_CANDIDATE")
    else:
        top = cands[0]
        second = cands[1].final if len(cands) > 1 else 0.0
        if top.final < cfg.accept_score:
            fails.append(f"1위 점수 {_fmt(top.final)} < 기준 {cfg.accept_score}")
            codes.append("LOW_SCORE")
        if top.final - second < cfg.min_margin:
            fails.append(f"1·2위 차이 {_fmt(top.final - second)} < 기준 {cfg.min_margin} (다중 후보/동률)")
            codes.append("AMBIGUOUS_CANDIDATES")
        if src.description:
            if not top.desc_available:
                fails.append("Target 설명 없음: 설명 근거 부족")
                codes.append("NO_TARGET_DESCRIPTION")
            elif top.desc < cfg.min_desc_similarity:
                fails.append(f"설명 유사도 {_fmt(top.desc)} < 기준 {cfg.min_desc_similarity}")
                codes.append("LOW_DESCRIPTION_EVIDENCE")
        if max(top.name_char, top.name_abbrev) < cfg.min_name_evidence:
            fails.append(f"이름 근거 {_fmt(max(top.name_char, top.name_abbrev))} < 기준 {cfg.min_name_evidence}")
            codes.append("LOW_NAME_EVIDENCE")

    if fails:
        missing.append("Target 확정을 위한 업무 규칙 또는 담당자 검토")
        rec = {**base, "decision": "REVIEW", "targets": [],
               "reason": "Target 미확정 - " + "; ".join(fails) + f". 참고 후보(확정 아님): {cand_text}. "
                         "점수는 유사도이며 확률이 아님.",
               "missing_information": _dedup(missing)}
        return Decision(rec, codes, False)

    # 3) 연산 결정 (Target 확정 상태)
    top = cands[0]
    tgt = top.target
    second = cands[1].final if len(cands) > 1 else 0.0
    evidence = (f"Target 1위 {tgt.table}.{tgt.column}: 종합 {_fmt(top.final)}, 2위와 차이 {_fmt(top.final - second)}, "
                f"이름 {_fmt(top.name_char)}/약어 {_fmt(top.name_abbrev)}/설명 {_fmt(top.desc)}, "
                f"테이블 친화도 {_fmt(top.table_affinity)}")
    op = "REVIEW"
    params: Dict[str, object] = {}
    op_note = ""
    extra_policy: List[str] = []
    keys = tgt.key_set
    src_code = src.code == "Y"
    tgt_code = is_code_like_target(tgt)
    tv = type_verdict(src, tgt)

    if "PK" in keys or "FK" in keys:
        op_note = f"Target이 키 컬럼({tgt.key_raw}): 식별자 생성·재사용·참조 매칭 규칙이 입력에 없음"
        codes.append("TARGET_KEY_POLICY_UNDEFINED")
        missing.append("Target 키 생성 또는 참조 매칭 규칙")
    elif src_code or tgt_code:
        sdom = parse_source_code_hint(src.code_hint)
        tdom = parse_target_enum_domain(tgt.description)
        if sdom and tdom and sdom <= tdom and tv.operation == "COPY":
            op = "COPY"
            params = {**tv.parameters, "allowed_values": sorted(tdom), "source_values": sorted(sdom)}
            op_note = "Source 코드값 집합이 Target 명시 허용값의 부분집합 -> 값 변환 없이 COPY"
            extra_policy.append("허용값 외 값 발견 시 처리 기준 미제공")
            missing.append("허용값 외 코드값 처리 기준")
        else:
            why = []
            if not sdom:
                why.append("Source 코드값 목록 없음")
            if not tdom:
                why.append("Target 닫힌 허용값 목록 없음")
            if sdom and tdom and not sdom <= tdom:
                why.append("Source 코드값이 Target 허용값에 포함되지 않음")
            if tv.operation != "COPY" and sdom and tdom and sdom <= tdom:
                why.append(tv.note)
            op_note = "코드성 컬럼: 코드 대응표 미제공(LOOKUP 추측 금지) - " + ", ".join(why)
            codes.append("CODE_MAPPING_MISSING")
            missing.append("Source->Target 코드값 대응표")
    else:
        op, params, op_note = tv.operation, dict(tv.parameters), tv.note
        if op == "REVIEW":
            codes.append(tv.review_code or "TYPE_RULE_UNDEFINED")
            missing.append("자료형 변환 규칙")

    policy = build_exception_policy(src, tgt, op, extra_policy, missing)
    decision = "MIGRATE" if op in AUTO_OPERATIONS else "REVIEW"
    if decision == "MIGRATE":
        codes.append("AUTO_" + op)
        reason = f"{evidence}. {op_note}. 이름·설명·자료형 근거가 단일 후보를 지지하여 {op}로 초안 작성(업무 승인 전)."
    else:
        reason = (f"{evidence}. Target은 단일 후보로 식별되었으나 변환 규칙 미확정 - {op_note}. "
                  "operation=REVIEW는 담당자 확정 필요를 뜻함.")
    target_obj = {"target_table": tgt.table, "target_column": tgt.column, "operation": op,
                  "parameters": params if op in AUTO_OPERATIONS else {}, "exception_policy": policy}
    rec = {**base, "decision": decision, "targets": [target_obj], "reason": reason,
           "missing_information": _dedup(missing)}
    return Decision(rec, codes, True)


def _dedup(items: Sequence[str]) -> List[str]:
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def write_json(path: Path, records: List[Dict[str, object]]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_candidates(path: Path, sources: Sequence[SourceCol], cand_lists: Sequence[List[Candidate]]) -> None:
    header = ["source_system", "source_table", "source_column", "rank", "target_table", "target_column",
              "score_final", "score_text", "score_name_char", "score_name_abbrev", "score_desc",
              "desc_available", "table_affinity", "type_relation", "note"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for s, cands in zip(sources, cand_lists):
            for rank, c in enumerate(cands, start=1):
                w.writerow([s.system, s.table, s.column, rank, c.target.table, c.target.column,
                            f"{c.final:.4f}", f"{c.text:.4f}", f"{c.name_char:.4f}", f"{c.name_abbrev:.4f}",
                            f"{c.desc:.4f}", "Y" if c.desc_available else "N", f"{c.table_affinity:.4f}",
                            c.type_relation, CANDIDATE_NOTE])


def write_trace(path: Path, sources: Sequence[SourceCol], decisions: Sequence[Decision]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_system", "source_table", "source_column", "decision", "operation",
                    "target_identified", "rule_codes"])
        for s, d in zip(sources, decisions):
            ops = "|".join(t["operation"] for t in d.record["targets"])  # type: ignore[index]
            w.writerow([s.system, s.table, s.column, d.record["decision"], ops,
                        "Y" if d.target_identified else "N", "|".join(d.review_codes)])


# ---------------------------------------------------------------------------
# 파이프라인
# ---------------------------------------------------------------------------
@dataclass
class RunResult:
    sources: List[SourceCol]
    targets: List[TargetCol]
    candidates: List[List[Candidate]]
    decisions: List[Decision]
    out_files: Dict[str, Path]


def generate(source_path: Path, target_path: Path, protocol_path: Path, out_dir: Path,
             cfg: Config = Config(), expect_source_rows: Optional[int] = None,
             expect_target_rows: Optional[int] = None,
             exclusion_path: Optional[Path] = None) -> RunResult:
    inputs = [source_path, target_path, protocol_path] + ([exclusion_path] if exclusion_path else [])
    out_dir = out_dir.resolve()
    for p in inputs:
        if p.resolve().parent == out_dir:
            raise InputError("출력 폴더는 입력 파일 폴더와 달라야 함(원본 보호)")
    check_protocol(protocol_path)
    sources = load_sources(source_path)
    targets = load_targets(target_path)
    if expect_source_rows is not None and len(sources) != expect_source_rows:
        raise InputError(f"Source 행 수 {len(sources)} != 기대값 {expect_source_rows}")
    if expect_target_rows is not None and len(targets) != expect_target_rows:
        raise InputError(f"Target 행 수 {len(targets)} != 기대값 {expect_target_rows}")
    exclusions = load_exclusion_rules(exclusion_path, sources)

    cand_lists = score_all(sources, targets, cfg)
    decisions = [decide(s, c, exclusions, cfg) for s, c in zip(sources, cand_lists)]

    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "mapping_draft": out_dir / "mapping_draft.json",
        "candidates": out_dir / "candidates.csv",
        "decision_trace": out_dir / "decision_trace.csv",
    }
    write_json(files["mapping_draft"], [d.record for d in decisions])
    write_candidates(files["candidates"], sources, cand_lists)
    write_trace(files["decision_trace"], sources, decisions)
    return RunResult(sources, targets, cand_lists, decisions, files)


# ---------------------------------------------------------------------------
# 보고서
# ---------------------------------------------------------------------------
def _count(items) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for x in items:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({(100.0 * n / d if d else 0):.1f}%)"


def build_report(res: RunResult, cfg: Config, validation: Dict[str, object], input_hashes: Dict[str, str],
                 inputs_unchanged: bool, exclusion_used: bool) -> str:
    n = len(res.sources)
    recs = [d.record for d in res.decisions]
    dec = _count(r["decision"] for r in recs)
    ops = _count(t["operation"] for r in recs for t in r["targets"])  # type: ignore[union-attr]
    target_ident = sum(1 for d in res.decisions if d.target_identified)
    review_codes = _count(c for d in res.decisions if d.record["decision"] == "REVIEW" for c in d.review_codes)
    missing = _count(m for r in recs for m in r["missing_information"])  # type: ignore[union-attr]
    top1 = [c[0].final for c in res.candidates if c]
    no_cand = sum(1 for c in res.candidates if not c)

    def group_stats(key_fn) -> List[str]:
        groups: Dict[str, List[str]] = {}
        for s, d in zip(res.sources, res.decisions):
            groups.setdefault(key_fn(s), []).append(str(d.record["decision"]))
        lines = []
        for g in sorted(groups):
            c = _count(groups[g])
            lines.append(f"  {g:<28} 행 {len(groups[g]):>3} | " +
                         ", ".join(f"{k} {v}" for k, v in c.items()))
        return lines

    L: List[str] = []
    L.append("MAPS 실험 1 - 매핑정의서 초안 자동 생성 보고서")
    L.append(f"알고리즘 버전: {ALGORITHM_VERSION}")
    L.append("=" * 78)
    L.append("[1] 입력")
    L.append(f"  Source 행: {n} / 시스템: {len({s.system for s in res.sources})} / 테이블(시스템+테이블): "
             f"{len({(s.system, s.table) for s in res.sources})}")
    L.append(f"  Target 행: {len(res.targets)} / 테이블: {len({t.table for t in res.targets})}")
    L.append(f"  TABLE_NAME_ASSUMED=Y 행: {sum(s.table_name_assumed == 'Y' for s in res.sources)}")
    L.append(f"  DATA_TYPE·COLUMN_DESCRIPTION 모두 빈 행: "
             f"{sum((not s.data_type) and (not s.description) for s in res.sources)}")
    L.append(f"  제외 규칙 입력 사용: {'예' if exclusion_used else '아니오(명시 제외 규칙 없음 -> EXCLUDE 미사용)'}")
    for name, h in input_hashes.items():
        L.append(f"  SHA-256 {name}: {h}")
    L.append(f"  실행 전후 입력 파일 해시 동일(원본 미변경): {'예' if inputs_unchanged else '아니오'}")
    L.append("")
    L.append("[2] 알고리즘")
    L.append("  후보 점수 = 텍스트 점수 x 자료형 계수 x (floor + (1-floor) x 테이블 친화도)")
    L.append("  텍스트 점수 = 이름 문자 n-gram TF-IDF, 약어 부분수열 매칭, 설명 문자 n-gram TF-IDF의 가중 평균")
    L.append("  (설명이 없는 쌍은 설명 성분을 제외하고 재정규화). 테이블 친화도는 라벨 없이 계산한 값임.")
    L.append("  Target 확정 게이트: 점수, 1·2위 차이, Source 설명·자료형 존재, 설명·이름 근거 최소값을 모두 충족해야 함.")
    L.append("  연산: Target PK/FK -> REVIEW, 코드성 컬럼 -> 닫힌 허용값 부분집합일 때만 COPY 아니면 REVIEW,")
    L.append("        그 외 자료형 규칙으로 COPY/FORMAT/REVIEW. LOOKUP 등 나머지 연산은 근거 입력이 없어 생성하지 않음.")
    L.append("  EXCLUDE는 명시적 제외 규칙 입력이 있을 때만 사용.")
    L.append(f"  설정: {json.dumps(asdict(cfg), ensure_ascii=False)}")
    L.append(f"  라이브러리: Python {platform.python_version()}, numpy {np.__version__}, "
             f"scikit-learn {sklearn.__version__}")
    L.append("")
    L.append("[3] 생성 결과")
    L.append(f"  출력 Source 객체: {len(recs)}")
    for k in DECISIONS:
        L.append(f"  {k:<8}: {_pct(dec.get(k, 0), n)}")
    L.append(f"  입력 커버리지: {_pct(len(recs), n)}")
    L.append(f"  확정률(MIGRATE+EXCLUDE): {_pct(dec.get('MIGRATE', 0) + dec.get('EXCLUDE', 0), n)}")
    L.append(f"  보류율(REVIEW): {_pct(dec.get('REVIEW', 0), n)}")
    L.append(f"  Target 식별 행(MIGRATE + 'Target 식별·변환 보류' REVIEW): {_pct(target_ident, n)}")
    L.append(f"    그중 REVIEW(Target 식별, operation=REVIEW): {target_ident - dec.get('MIGRATE', 0)}")
    L.append(f"  REVIEW(Target 미확정, targets=[]): "
             f"{sum(1 for r in recs if r['decision'] == 'REVIEW' and not r['targets'])}")
    L.append(f"  operation 분포: {json.dumps(ops, ensure_ascii=False)}")
    if top1:
        arr = np.array(top1)
        L.append(f"  1위 후보 점수(유사도, 확률 아님): 최소 {arr.min():.3f} / 중앙 {np.median(arr):.3f} / "
                 f"최대 {arr.max():.3f}, 후보 없음 {no_cand}행")
    L.append("  시스템별:")
    L.extend(group_stats(lambda s: s.system))
    L.append("  테이블명 가정 여부별:")
    L.extend(group_stats(lambda s: f"TABLE_NAME_ASSUMED={s.table_name_assumed or '(빈값)'}"))
    L.append("  메타데이터 완비 여부별:")
    L.extend(group_stats(lambda s: "자료형·설명 있음" if (s.data_type and s.description) else "자료형/설명 누락"))
    L.append("")
    L.append("[4] REVIEW 사유 분류 (한 행에 복수 코드 가능)")
    for k, v in review_codes.items():
        L.append(f"  {k:<32} {v}")
    L.append("")
    L.append("[5] 추가 정보 필요 항목 빈도 (missing_information)")
    for k, v in missing.items():
        L.append(f"  {v:>4}  {k}")
    L.append("")
    L.append("[6] 자동 검증 (validate_output.py, 출력 파일을 디스크에서 다시 읽어 독립 검사)")
    L.append(f"  전체 결과: {'PASS' if validation.get('passed') else 'FAIL'}")
    for chk in validation.get("checks", []):  # type: ignore[union-attr]
        L.append(f"  [{'PASS' if chk['passed'] else 'FAIL'}] {chk['name']}: {chk['detail']}")
    L.append("")
    L.append("[7] 해석상 주의와 미검증 범위")
    L.append("  - 정답(기존 승인 매핑정의서) 대조는 실시하지 않음. 매핑 F1·이관 여부 일치도는 미측정.")
    L.append("  - 실제 값 샘플·기대 출력이 없으므로 변환 실행 정확도는 측정하지 않음.")
    L.append("  - 구조 검증 PASS는 출력 규격 충족을 뜻할 뿐 매핑 정확도를 뜻하지 않음.")
    L.append("  - 후보 점수는 이름·설명 유사도이며 정답 확률이 아님. candidates.csv는 확정 매핑이 아님.")
    L.append("  - REVIEW 중 targets가 있는 행은 'Target 단일 후보는 식별했으나 변환 규칙 미확정'이라는 이 기준선의")
    L.append("    출력 관례임. 평가 시 매핑 쌍 집계에 포함할지(포함/제외 두 방식) 평가 전에 정해야 함.")
    L.append("  - 복수 Target 자동 확정은 근거 규칙이 없어 생성하지 않음(1:N 관계는 REVIEW로 남음).")
    L.append("  - 설계자(구현 보조자)는 규칙 작성 시 입력 메타데이터 구조를 열람했음. 개별 컬럼 예외 규칙은 없으나,")
    L.append("    임계값·가중치가 이 입력에 우연히 유리하거나 불리할 수 있으므로 독립 입력에서 재검증이 필요함.")
    L.append("")
    L.append("[8] 작업 범위 확인")
    L.append("  - 이 프로그램은 네트워크·외부 API·Azure·DB 접속 코드를 포함하지 않음(정적 검사 결과는 [6] 참조).")
    L.append("  - 입력 파일은 읽기 전용으로 열며, 출력은 입력과 다른 폴더에만 기록함.")
    L.append("  - Git 작업을 수행하지 않음.")
    return "\n".join(L) + "\n"


def _manifest(args: argparse.Namespace, cfg: Config, input_hashes: Dict[str, str], output_hashes: Dict[str, str],
              started: str, finished: str, validation_passed: bool) -> Dict[str, object]:
    return {
        "algorithm_version": ALGORITHM_VERSION,
        "started_at_utc": started,
        "finished_at_utc": finished,
        "command": {
            "script": Path(sys.argv[0]).name,
            "source": Path(args.source).name, "target": Path(args.target).name,
            "protocol": Path(args.protocol).name,
            "exclusion_rules": Path(args.exclusion_rules).name if args.exclusion_rules else None,
            "expect_source_rows": args.expect_source_rows, "expect_target_rows": args.expect_target_rows,
        },
        "config": asdict(cfg),
        "environment": {"python": platform.python_version(), "implementation": platform.python_implementation(),
                        "operating_system": platform.system(), "numpy": np.__version__, "scikit_learn": sklearn.__version__},
        "input_sha256": input_hashes,
        "output_sha256": output_hashes,
        "validation_passed": validation_passed,
        "notes": "경로·개인정보·인증정보는 기록하지 않음. 정답 대조 미실시.",
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="MAPS 실험 1 매핑정의서 초안 생성 기준선")
    ap.add_argument("--source", required=True, help="source_metadata.csv")
    ap.add_argument("--target", required=True, help="target_schema.csv")
    ap.add_argument("--protocol", required=True, help="OUTPUT_CONTRACT.txt")
    ap.add_argument("--out-dir", required=True, help="출력 폴더(입력 폴더와 달라야 함)")
    ap.add_argument("--expect-source-rows", type=int, default=None)
    ap.add_argument("--expect-target-rows", type=int, default=None)
    ap.add_argument("--exclusion-rules", default=None, help="선택: 명시적 제외 규칙 CSV")
    args = ap.parse_args(argv)

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cfg = Config()
    src_p, tgt_p, pro_p = Path(args.source), Path(args.target), Path(args.protocol)
    exc_p = Path(args.exclusion_rules) if args.exclusion_rules else None
    out_dir = Path(args.out_dir)
    in_paths = {p.name: p for p in [src_p, tgt_p, pro_p] + ([exc_p] if exc_p else [])}
    try:
        before = {k: sha256_file(p) for k, p in in_paths.items() if p.is_file()}
        res = generate(src_p, tgt_p, pro_p, out_dir, cfg, args.expect_source_rows, args.expect_target_rows, exc_p)
    except InputError as e:
        print(f"[입력 오류 - 중단] {e}", file=sys.stderr)
        return 2
    after = {k: sha256_file(p) for k, p in in_paths.items()}
    unchanged = before == after

    import validate_output  # 같은 폴더의 독립 검증기
    validation = validate_output.validate(
        source_path=src_p, target_path=tgt_p, mapping_path=res.out_files["mapping_draft"],
        candidates_path=res.out_files["candidates"],
        algorithm_paths=[Path(__file__).resolve()], top_k=cfg.top_k)
    with open(out_dir / "validation_result.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(validation, f, ensure_ascii=False, indent=2)
        f.write("\n")

    report = build_report(res, cfg, validation, after, unchanged, exc_p is not None)
    (out_dir / "report.txt").write_text(report, encoding="utf-8", newline="\n")

    outs = ["mapping_draft.json", "candidates.csv", "decision_trace.csv", "validation_result.json", "report.txt"]
    out_hashes = {name: sha256_file(out_dir / name) for name in outs}
    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(out_dir / "run_manifest.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(_manifest(args, cfg, after, out_hashes, started, finished, bool(validation["passed"])), f,
                  ensure_ascii=False, indent=2)
        f.write("\n")

    dec = _count(d.record["decision"] for d in res.decisions)
    print(f"[완료] Source {len(res.sources)}행 -> 출력 {len(res.decisions)}건 | " +
          ", ".join(f"{k} {dec.get(k, 0)}" for k in DECISIONS))
    print(f"[검증] {'PASS' if validation['passed'] else 'FAIL'} "
          f"({sum(c['passed'] for c in validation['checks'])}/{len(validation['checks'])} 항목 통과)")
    print(f"[원본] 입력 파일 변경 없음: {'예' if unchanged else '아니오'}")
    print(f"[출력 폴더] {out_dir.name}")
    return 0 if (validation["passed"] and unchanged) else 1


if __name__ == "__main__":
    sys.exit(main())
