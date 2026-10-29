# -*- coding: utf-8 -*-
"""지식 조각(kb_*.jsonl) 읽기와 '정답 누수 차단'.

쉬운 설명
- 지식 조각 = 팀 문서를 한 줄(한 행)씩 잘라 둔 카드. 카드마다 chunk_id(이름표)가 있다.
- AI에게 보여 줄 카드와 보여 주면 안 되는 카드(=정답지)를 여기서 코드로 갈라 놓는다.
  "정답을 보지 마"라고 부탁하는 것이 아니라, 검색 대상에서 아예 빼 버린다.
"""
import json
from pathlib import Path

# 정답지나 다름없어서 기본으로 빼는 카드 종류
ANSWER_DOC_TYPES = {"MAPPING_EXAMPLE", "CODE_MAPPING"}          # 팀 확정 매핑(v1.2), 코드 매핑
# 설계 결정 중 특정 컬럼의 답을 말하는 것 (일반 규칙 M1·M5·LOAD_ORDER·R2·R5 는 허용)
BLOCKED_DESIGN_IDS = {"M2", "M3", "M4", "R1", "R3", "R4"}
# 검색 대상에서 제외(이 과제에서 쓰지 않음)
NOT_FOR_COLUMN_MAPPING = {"STD_PRODUCT"}

TARGET_TABLES_FIXED = ("COUNSEL", "COMPLAINT")   # 목표 표는 2개로 고정


def load_chunks(kb_dir):
    kb_dir = Path(kb_dir)
    chunks = []
    for p in sorted(kb_dir.glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                d = json.loads(line)
                d["_file"] = p.name
                chunks.append(d)
    return chunks


def is_blocked(chunk, include_answer_like=False):
    """AI에게 보여 주면 안 되는 카드인가?  include_answer_like=True 이면 정답 성격 카드도 허용(평가 시 점수가 부풀 수 있음)."""
    if chunk.get("doc_type") in NOT_FOR_COLUMN_MAPPING:
        return True
    if include_answer_like:
        return False
    if chunk.get("doc_type") in ANSWER_DOC_TYPES:
        return True
    if chunk.get("answer_like"):
        return True
    if chunk.get("doc_type") == "DESIGN_DECISION" and chunk.get("reference_key") in BLOCKED_DESIGN_IDS:
        return True
    return False


def target_table_of(chunk):
    refs = chunk.get("target_refs") or []
    return {r.split(".")[0] for r in refs}


def searchable(chunks, include_answer_like=False):
    """검색해도 되는 카드만. 목표 컬럼 카드(kb_01)는 상담·민원 표 것만 남긴다."""
    out = []
    for c in chunks:
        if is_blocked(c, include_answer_like):
            continue
        if c.get("doc_type") == "TARGET_COLUMN" and not (target_table_of(c) & set(TARGET_TABLES_FIXED)):
            continue
        out.append(c)
    return out


LOOKUP_ONLY_TYPES = {"DQ_RULE", "SOURCE_CODE_MASTER"}   # 정확한 열쇠로 조회하는 자료(검색·임베딩 대상 아님)


def retrievable(chunks, include_answer_like=False):
    """임베딩·검색으로 찾을 카드 = 볼 수 있는 카드 중 '조회 전용'이 아닌 것."""
    return [c for c in searchable(chunks, include_answer_like) if c.get("doc_type") not in LOOKUP_ONLY_TYPES]
