# -*- coding: utf-8 -*-
"""'정확한 열쇠로 조회'하는 자료들 (임베딩·검색 없이 코드가 그냥 찾아서 준다).

쉬운 설명 (보련님 제안을 받아들인 부분)
- 목표 표는 상담(COUNSEL)·민원(COMPLAINT) 2개로 고정이라 후보 목표 칸이 25개뿐이다 → 검색하지 않고 통째로 보여 준다.
- 원천 컬럼의 품질 규칙(DQ), 원천 코드표는 '채널+컬럼 이름'이라는 정확한 열쇠가 있으니 그대로 찾아 준다.
"""
import re
from pathlib import Path

import pandas as pd

from .knowledge import TARGET_TABLES_FIXED


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower().replace("__c", ""))


# 원천 컬럼명과 '원천 코드표' 카드 제목의 코드그룹명이 다르게 붙어 있는 경우.
# 코드표 자체(지식_11_원천코드표.jsonl)는 존재하는데, 카드 제목이 실제 브론즈 컬럼명과
# 달라서(문서화 안 된 리네이밍) source_codes()의 이름 매칭이 놓치던 사례를 보정한다.
# 팀 원본 지식조각 파일은 건드리지 않고, 조회 쪽에서만 별칭을 추가로 시도한다.
SRC_CODE_ALIASES = {
    ("HOMEPAGE", "PRODUCT_GB"): "PRODUCT_AREA",
    ("HOMEPAGE", "RCV_PATH"): "RECEIVE_CHANNEL",
    ("HOMEPAGE", "COMPLAINT_TP"): "COMPLAINT_TYPE",
}


class TargetCatalog:
    """목표(타겟) 물리모델에서 상담·민원 표의 컬럼 규격을 읽는다."""

    def __init__(self, physical_model_csv):
        df = pd.read_csv(physical_model_csv, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        df = df[df["TABLE_NAME"].isin(TARGET_TABLES_FIXED)]
        self.rows = df.to_dict("records")
        self.by_table = {t: [r for r in self.rows if r["TABLE_NAME"] == t] for t in TARGET_TABLES_FIXED}
        self.all_ids = {f"{r['TABLE_NAME']}.{r['COLUMN_NAME']}" for r in self.rows}

    def exists(self, target):
        return target in self.all_ids

    def compact(self, table):
        """프롬프트에 넣을 한 줄 표기 (토큰 절약)."""
        out = []
        for r in self.by_table[table]:
            key = f" {r['KEY']}" if r["KEY"] else ""
            nul = "필수" if r["NULLABLE"] == "N" else "선택"
            out.append(f"{r['TABLE_NAME']}.{r['COLUMN_NAME']} [{r['DATA_TYPE']}{key}, {nul}] {r['DESCRIPTION']}")
        return "\n".join(out)


class Lookups:
    """지식 조각에서 정확한 열쇠로 찾기."""

    def __init__(self, chunks):
        self.dq = {}       # (채널, 컬럼정규화) → chunk
        self.srccode = {}  # 채널 → [chunk]
        self.codes = []    # 표준코드 카드
        for c in chunks:
            t = c.get("doc_type")
            if t == "DQ_RULE":
                ch = (c.get("channels") or [""])[0]
                col = str(c.get("title", "")).split(".", 1)[-1]
                self.dq[(ch, _norm(col))] = c
            elif t == "SOURCE_CODE_MASTER":
                ch = (c.get("channels") or [""])[0]
                self.srccode.setdefault(ch, []).append(c)
            elif t == "STD_CODE":
                self.codes.append(c)

    def dq_rule(self, channel, column):
        return self.dq.get((channel, _norm(column)))

    def source_codes(self, channel, column):
        """이 원천 컬럼과 이름이 같은 '원천 코드표' 카드. 이름이 다르게 붙은 알려진 경우는 별칭으로도 찾는다."""
        col = _norm(column)
        alias = SRC_CODE_ALIASES.get((channel, str(column).upper()))
        alias_col = _norm(alias) if alias else None
        hits = []
        for c in self.srccode.get(channel, []):
            grp = _norm(str(c.get("title", "")).split(".", 1)[-1])
            if not grp or len(grp) < 3:
                continue
            if grp == col or grp in col or col in grp:
                hits.append(c)
            elif alias_col and (grp == alias_col or grp in alias_col or alias_col in grp):
                hits.append(c)
        return hits[:2]

    def std_codes_for(self, target_ids, limit=3):
        """후보 목표 칸에 붙은 표준코드(값 목록) 카드."""
        ids = set(target_ids)
        out = []
        for c in self.codes:
            if ids & set(c.get("target_refs") or []):
                out.append(c)
        return out[:limit]
