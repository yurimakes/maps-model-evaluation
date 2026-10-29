# OPT-IN UPGRADE: original source is preserved in phase2_original. See build_phase2_upgrade.py.
# -*- coding: utf-8 -*-
"""컬럼 하나 → (표 고정) → 근거 모으기 → AI에게 묻기 → 코드로 검증·확신도 계산.

쉬운 설명
- AI(gpt)는 '추천 답'만 낸다. 그 답이 맞는 모양인지, 목표 칸이 진짜 있는지, 근거 이름표가 진짜인지는 코드가 확인한다.
- 확신도 점수도 AI가 말하는 것이 아니라 코드가 계산한다(AI가 준 항목별 점수를 가중합).
"""
import json
import re
import time
from datetime import datetime

from .azure_client import est_tokens, parse_json
from .strict_validation import evaluate_scores
from .embeddings import text_key
from .knowledge import TARGET_TABLES_FIXED
from .source_loader import CHANNEL_KO, CHANNEL_TO_TARGET

MAPPING_TYPES = ["DIRECT", "RENAME", "TRANSFORM", "CODE", "DERIVED", "EXCLUDE"]
PROCESS_TYPES = ["COPY", "FORMAT", "LOOKUP", "CONSTANT", "GENERATE_ID", "EXPLODE", "CUSTOMER_MATCH", "NONE"]
# 출처: 06 Mapping/team/6.1MAPS_Mapping_평가_기준서_v1.0.docx (기준일 2026-09-18, 팀 공식 확정본) 5.1~5.4 그대로.
# 2026-09-22 대조 확인: 가중치·게이트·등급 컷오프 전부 이 문서와 일치.
CRITERIA_VERSION = "6.1MAPS_Mapping_평가_기준서_v1.0 (2026-09-18)"
WEIGHTS = {"NAME": 0.15, "DESCRIPTION": 0.10, "DOMAIN": 0.10, "DATATYPE": 0.15, "SAMPLE": 0.20, "CODE": 0.15, "RELATION": 0.15}
GATES = ["RELATION_FIT", "DATATYPE_CONVERTIBLE"]
# 6.1 기준서 5.4의 REVIEW 컷(0.70)과 동일. recommend_v2()에서 "후보 전체 중 최고점"이 이 값 미만이면
# 게이트를 통과했어도 매핑으로 확정하지 않고 EXCLUDE로 본다(2026-09-27, 08_후보비교_흐름 실험에서 발견된
# "게이트만 안 FAIL이면 무조건 매핑됨" 버그의 수정).
MIN_MAP_SCORE = 0.70

SYSTEM_RULES = """너는 보험사 상담 데이터 이관(Source→Target)의 '매핑 추천 보조자'다. 최종 결정은 사람이 한다. 너는 후보와 근거만 추천한다.
지킬 것
1. [목표 후보]에 있는 TABLE.COLUMN 중에서만 고른다. 맞는 것이 없으면 target 을 EXCLUDE 로 하고 exclude_reason 을 쓴다.
2. [조회 근거]와 [검색 근거]에 적힌 내용만 근거로 삼는다. 없는 사실을 만들지 않는다. 근거에 붙은 id 만 evidence 에 적는다(목표 후보는 TOBE-표.칸 형식의 id 를 쓴다).
3. 코드값은 근거에 있는 값만 변환한다. 근거 없는 값은 강제로 맞추지 않는다.
4. 채점 항목은 점수(0~1) 또는 null(해당 없음). 근거를 못 찾으면 낮은 점수를 준다.
5. 반드시 JSON 한 개만 출력한다. 설명 글을 붙이지 않는다.

mapping_type 뜻: DIRECT 이름·값 그대로 / RENAME 이름만 표준 이름으로 / TRANSFORM 값을 표준 형식으로 변환 / CODE 코드값을 표준코드로 변환 / DERIVED 다른 자료로 조회하거나 만들어 냄 / EXCLUDE 이행 제외
process_type 뜻: COPY 복사 / FORMAT 형식 변환 / LOOKUP 표 조회 / CONSTANT 상수 채움 / GENERATE_ID 번호 생성 / EXPLODE 배열을 여러 행으로 / CUSTOMER_MATCH 고객 통합 / NONE 실행 없음(제외일 때)
자주 쓰는 짝: RENAME+COPY, DIRECT+COPY, TRANSFORM+FORMAT, CODE+LOOKUP, DERIVED+LOOKUP, DERIVED+CONSTANT, DERIVED+GENERATE_ID, EXCLUDE+NONE
채점 항목(가중치): NAME 명칭 유사(15%) / DESCRIPTION 설명 의미 유사(10%) / DOMAIN 도메인 일치(10%) / DATATYPE 데이터타입(15%) / SAMPLE 샘플값 패턴(20%) / CODE 코드값 대응(15%) / RELATION 업무 관계 PK·FK(15%)
gates(꼭 통과): RELATION_FIT 업무 관계가 맞는가, DATATYPE_CONVERTIBLE 타입 변환이 가능한가. 값은 PASS 또는 FAIL 또는 NA.
출력 형식 예(값은 예시일 뿐, 실제 컬럼에 맞게 채워라):
{"target":"COUNSEL.CNSL_ID","mapping_type":"RENAME","process_type":"COPY","rule":"상담 식별자를 그대로 복사","exclude_reason":null,"reason":"설명·이름이 같은 뜻(근거 TOBE-COUNSEL.CNSL_ID)","evidence":["TOBE-COUNSEL.CNSL_ID"],"gates":{"RELATION_FIT":"PASS","DATATYPE_CONVERTIBLE":"PASS"},"scores":{"NAME":0.7,"DESCRIPTION":0.9,"DOMAIN":1.0,"DATATYPE":0.9,"SAMPLE":0.8,"CODE":null,"RELATION":1.0},"exclude_confidence":null}
제외일 때는 target 을 "EXCLUDE", mapping_type 을 "EXCLUDE", process_type 을 "NONE" 으로 하고, gates 와 scores 는 모두 null 로 한다. 그리고 exclude_reason(제외 이유를 한 문장)과 exclude_confidence('제외가 맞다는 확신' 0~1 숫자)와 reason 은 반드시 채운다(비워 두지 않는다)."""

# ---- recommend_v2 전용: "하나만 골라라"가 아니라 후보 표 전체를 한 번에 채점시키는 프롬프트(2026-09-27, 08_후보비교_흐름에서 검증) ----
CANDIDATE_SCAN_SYSTEM_RULES = """너는 보험사 데이터 이관 매핑의 '전체 후보 채점자'다. 최종 결정은 사람이 한다. 너는 후보를 하나 고르지 않고, 후보 전체를 채점만 한다.
지킬 것
1. [목표 후보]에 나온 TABLE.COLUMN 전부에 대해 빠짐없이 하나씩 채점한다. 하나라도 빠뜨리면 안 된다. 후보에 없는 것을 만들어 답하지 않는다.
2. 각 후보마다 게이트 두 개를 판정한다: RELATION_FIT(업무 관계가 맞는가), DATATYPE_CONVERTIBLE(타입 변환이 가능한가). 값은 PASS 또는 FAIL 또는 NA(판단할 근거가 부족함).
3. 각 후보마다 채점 항목 7개에 0~1 점수(해당없으면 null)를 매긴다: NAME 명칭유사(15%) / DESCRIPTION 설명의미유사(10%) / DOMAIN 도메인일치(10%) / DATATYPE 데이터타입(15%) / SAMPLE 샘플값패턴(20%) / CODE 코드값대응(15%) / RELATION 업무관계 PK·FK(15%).
4. [조회 근거]와 [검색 근거]에 적힌 내용만 근거로 삼는다. 없는 사실을 만들지 않는다. 근거를 못 찾으면 낮은 점수를 준다.
5. 반드시 JSON 한 개만 출력한다. 설명 글을 붙이지 않는다.
출력 형식(값은 예시일 뿐, 실제 후보 전부를 채워라):
{"candidate_scan":[{"target":"COMPLAINT.CMPL_ID","gate_relation":"PASS","gate_datatype":"PASS","scores":{"NAME":0.7,"DESCRIPTION":0.9,"DOMAIN":1.0,"DATATYPE":0.9,"SAMPLE":0.8,"CODE":null,"RELATION":1.0}}]}
candidate_scan 배열의 길이는 [목표 후보]에 나온 칸 개수와 반드시 같아야 한다."""


# ---------------- 프롬프트 만들기 ----------------
def query_text(row):
    ch = row["channel"]
    return (f"채널 {CHANNEL_KO.get(ch, ch)} 표 {row['source_table']} 컬럼 {row['source_column']}. 설명 {row.get('as_is_desc') or ''}. "
            f"타입 {row.get('as_is_dtype') or ''}. 샘플 {row.get('top_values') or ''}")


def _clip(s, n):
    s = re.sub(r"\s+", " ", str(s))
    return s if len(s) <= n else s[: n - 1] + "…"


PSEUDO_DESC = {
    "<SOURCE_SYSTEM>": "원천에는 없는 가상 항목. '이 데이터가 어느 채널 시스템에서 왔는지'를 목표 칸에 상수로 채워 넣을 때 쓰는 값",
    "<DETAIL_TYPE>": "원천에는 없는 가상 항목. 상세 행이 어떤 종류(메뉴 이동, 자유 질문 등)인지 구분해 채워 넣을 때 쓰는 값",
}


def _fmt(v, unit="", as_int=False):
    try:
        if v is None or v == "" or (isinstance(v, float) and v != v):
            return "-"
        f = float(v)
        return (f"{int(f)}" if as_int else f"{f:g}") + unit
    except Exception:
        return f"{v}{unit}"


def source_block(row):
    ch = row["channel"]
    desc = row.get("as_is_desc") or PSEUDO_DESC.get(row["source_column"], "")
    lines = [f"[원천 컬럼]",
             f"채널: {ch}({CHANNEL_KO.get(ch, '')}) → 목표 표: {CHANNEL_TO_TARGET[ch]} (고정 규칙)",
             f"원천 표: {row['source_table']}  컬럼: {row['source_column']}",
             f"설명: {desc}  타입: {row.get('as_is_dtype') or '-'}  코드형: {row.get('code_column_yn') or '-'}  개인정보: {row.get('pii_yn') or '-'}",
             f"프로파일: 빈값 {_fmt(row.get('null_pct'), '%')}, 고유값 {_fmt(row.get('distinct_cnt'), '개', True)}, 대표값 {row.get('top_values')}"]
    return "\n".join(lines)


# ---------------- recommend_v2 전용 부품 (2026-09-27, 08_후보비교_흐름에서 검증 후 이전) ----------------
def build_candidate_scan_messages(catalog, row, table, facts, hits):
    """'하나 골라라' 대신 목표 후보 표 전체에 게이트·점수를 매기라는 질문을 조립한다."""
    parts = [source_block(row), "", f"[목표 후보] ({table} 표의 칸 전부 {len(catalog.by_table[table])}개. 전부 하나씩 채점할 것)", catalog.compact(table), "", "[조회 근거]"]
    if facts:
        for c in facts:
            parts.append(f"- id {c['chunk_id']}: {_clip(c['text'], 260)}")
    else:
        parts.append("- (이 컬럼에 대한 조회 근거 없음)")
    parts += ["", f"[검색 근거] (관련도 높은 순 {len(hits)}개)"]
    if hits:
        for h in hits:
            c = h["chunk"]
            parts.append(f"- id {c['chunk_id']} ({c['doc_type']}): {_clip(c['text'], 200)}")
    else:
        parts.append("- (검색 결과 없음)")
    parts += ["", "위 원천 컬럼을 [목표 후보]의 칸 전부와 하나씩 대조해서, 각 칸의 게이트·점수만 JSON으로 답하라(후보를 하나로 고르지 말 것)."]
    return [{"role": "system", "content": CANDIDATE_SCAN_SYSTEM_RULES}, {"role": "user", "content": "\n".join(parts)}]


def validate_candidate_scan(parsed, catalog, table):
    ids=[f"{table}.{r['COLUMN_NAME']}" for r in catalog.by_table[table]]
    out={t:{'gate_relation':None,'gate_datatype':None,'scores':{},'score_status':{},'na_reasons':{}} for t in ids}
    if not isinstance(parsed,dict) or not isinstance(parsed.get('candidate_scan'),list):return out,['JSON_PARSE_FAIL']
    seen=set();flags=[]
    for item in parsed['candidate_scan']:
        if not isinstance(item,dict):flags.append('NON_OBJECT_CANDIDATE');continue
        target=str(item.get('target') or '').strip()
        if target not in out:flags.append('UNKNOWN_TARGET');continue
        if target in seen:flags.append('DUPLICATE_TARGET');continue
        seen.add(target)
        out[target]={'gate_relation':str(item.get('gate_relation') or 'MISSING').upper(),'gate_datatype':str(item.get('gate_datatype') or 'MISSING').upper(),'scores':item.get('scores') or {},'score_status':item.get('score_status') or {},'na_reasons':item.get('na_reasons') or {}}
    if len(seen)!=len(ids):flags.append(f'MISSING_{len(ids)-len(seen)}_CANDIDATES')
    return out,sorted(set(flags))



def score_one_candidate(entry):
    evaluated=evaluate_scores(entry.get('scores'),entry.get('score_status'),entry.get('na_reasons'))
    gates_ok=entry.get('gate_relation')=='PASS' and entry.get('gate_datatype')=='PASS'
    return evaluated['confidence'],not gates_ok or bool(evaluated['invalid'])



def pick_best_candidate(candidate_map):
    scored=[];incomplete=False
    for target,entry in candidate_map.items():
        e=evaluate_scores(entry.get('scores'),entry.get('score_status'),entry.get('na_reasons'))
        gr,gd=entry.get('gate_relation'),entry.get('gate_datatype')
        gate_unknown=gr not in ('PASS','FAIL') or gd not in ('PASS','FAIL')
        incomplete|=gate_unknown or bool(e['missing']) or bool(e['invalid'])
        scored.append({'target':target,'confidence_score':e['confidence'],'gate_fail':gr!='PASS' or gd!='PASS' or bool(e['invalid']),'gate_relation':gr,'gate_datatype':gd,'missing_scores':e['missing'],'invalid_scores':e['invalid']})
    eligible=[s for s in scored if not s['gate_fail'] and not s['missing_scores'] and s['confidence_score'] is not None and s['confidence_score']>=MIN_MAP_SCORE]
    if eligible and not incomplete:
        best=sorted(eligible,key=lambda x:(-x['confidence_score'],x['target']))[0]
        return {'decision':'MAPPED','target':best['target'],'confidence_score':best['confidence_score'],'confidence_level':confidence_level(best['confidence_score']),'reason':'Both mandatory gates PASS; all applicable scores supplied.'},scored
    scored_values=[s['confidence_score'] for s in scored if s['confidence_score'] is not None]
    score=max(scored_values) if scored_values else None
    if incomplete or not scored:
        return {'decision':'REVIEW','target':None,'confidence_score':score,'confidence_level':'INVALID_CANDIDATE','reason':'INSUFFICIENT_EVIDENCE_NOT_EXCLUSION'},scored
    return {'decision':'EXCLUDE','target':'EXCLUDE','confidence_score':score,'confidence_level':'REVIEW','reason':'Complete candidate scan; no eligible mapping.'},scored



class _OneCandidateCatalog:
    """target 하나만 담은 임시 카탈로그. recommend_v2가 candidate_scan으로 이미 고른 후보 하나를
    기존 단일-후보 검증 로직(Recommender.build_messages / validate)에 그대로 태우기 위한 뷰일 뿐,
    실제 TargetCatalog 는 손대지 않는다."""

    def __init__(self, real_catalog, table, target_id):
        col = target_id.split(".", 1)[1]
        row = next(r for r in real_catalog.by_table[table] if r["COLUMN_NAME"] == col)
        self.by_table = {table: [row]}
        self.all_ids = {target_id}

    def exists(self, target):
        return target in self.all_ids

    def compact(self, table):
        r = self.by_table[table][0]
        key = f" {r['KEY']}" if r["KEY"] else ""
        nul = "필수" if r["NULLABLE"] == "N" else "선택"
        return f"{r['TABLE_NAME']}.{r['COLUMN_NAME']} [{r['DATA_TYPE']}{key}, {nul}] {r['DESCRIPTION']}"


class Recommender:
    def __init__(self, catalog, lookups, retriever, client, query_vectors=None, embedder=None,
                 mode="hybrid", k=5, max_completion_tokens=900, log=print):
        self.catalog, self.lookups, self.retriever = catalog, lookups, retriever
        self.client = client
        self.qvec = query_vectors or {}       # {질문글 지문: 벡터} 미리 계산해 둔 질문 임베딩
        self.embedder = embedder              # 없으면 즉석 계산(호출 발생)
        self.mode, self.k, self.max_out = mode, k, max_completion_tokens
        self.log = log

    # ---- 근거 모으기 ----
    def gather(self, row):
        ch, table = row["channel"], CHANNEL_TO_TARGET[row["channel"]]
        facts = []   # 정확 조회
        dq = self.lookups.dq_rule(ch, row["source_column"])
        if dq:
            facts.append(dq)
        for c in self.lookups.source_codes(ch, row["source_column"]):
            facts.append(c)
        cand_ids = [f"{table}.{r['COLUMN_NAME']}" for r in self.catalog.by_table[table]]
        if row.get("code_column_yn") == "Y":
            facts += self.lookups.std_codes_for(cand_ids, limit=2)
        seen = {c["chunk_id"] for c in facts}

        def allow(c):
            if c["chunk_id"] in seen:
                return False
            t = c.get("doc_type")
            if t in ("SOURCE_CODE_MASTER", "DQ_RULE"):
                return False            # 이미 정확 조회로 넣음(같은 채널만)
            if t == "TARGET_COLUMN":
                return False            # 목표 후보 25칸은 [목표 후보]에 이미 통째로 있어서 검색 결과에서는 뺀다(중복 방지)
            refs = c.get("target_refs") or []
            if refs and table not in {r.split(".")[0] for r in refs}:
                return False
            return True

        qv = None
        if self.mode in ("embedding", "hybrid") and self.retriever.has_embeddings():
            qv = self.qvec.get(text_key(query_text(row)))
            if qv is None and self.embedder:
                qv = self.embedder([query_text(row)])[0]
        hits = self.retriever.search(query_text(row), qv, mode=self.mode, k=self.k, allow=allow)
        return table, facts, hits

    def build_messages(self, row, table, facts, hits):
        parts = [source_block(row), "", f"[목표 후보] ({table} 표의 칸 전부. id 는 TOBE-표.칸)", self.catalog.compact(table), "", "[조회 근거]"]
        if facts:
            for c in facts:
                parts.append(f"- id {c['chunk_id']}: {_clip(c['text'], 260)}")
        else:
            parts.append("- (이 컬럼에 대한 조회 근거 없음)")
        parts += ["", f"[검색 근거] (관련도 높은 순 {len(hits)}개)"]
        if hits:
            for h in hits:
                c = h["chunk"]
                parts.append(f"- id {c['chunk_id']} ({c['doc_type']}): {_clip(c['text'], 200)}")
        else:
            parts.append("- (검색 결과 없음)")
        parts += ["", "위 원천 컬럼을 어느 목표 칸에 연결해야 하는지 JSON 으로만 답하라."]
        return [{"role": "system", "content": SYSTEM_RULES}, {"role": "user", "content": "\n".join(parts)}]

    # ---- 한 컬럼 추천 ----
    def recommend(self, row):
        t0 = time.time()
        table, facts, hits = self.gather(row)
        msgs = self.build_messages(row, table, facts, hits)
        est = sum(est_tokens(m["content"]) for m in msgs)
        shown = {c["chunk_id"] for c in facts} | {h["chunk"]["chunk_id"] for h in hits} | \
                {f"TOBE-{table}.{r['COLUMN_NAME']}" for r in self.catalog.by_table[table]}
        text, usage = self.client.chat(msgs, max_completion_tokens=self.max_out, json_mode=True)
        parsed = parse_json(text)
        result = validate(parsed, self.catalog, shown)
        if result["confidence_level"] == "INVALID_CANDIDATE" and \
                ("NO_EXCLUDE_REASON" in result["flags"] or "NO_EXCLUDE_CONFIDENCE" in result["flags"]):
            # 제외 추천인데 사유/확신도가 비었음 — 한 번만 다시 물어본다(비용 작음, 팀 결정 D-09)
            retry_msgs = msgs + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": "방금 답에서 exclude_reason 또는 exclude_confidence 가 비어 있었습니다. "
                                             "제외(EXCLUDE)로 답할 때는 exclude_reason(제외 이유 한 문장)과 "
                                             "exclude_confidence(0~1 숫자)를 반드시 채워서, 같은 형식의 JSON으로 다시 답하세요."},
            ]
            text2, usage2 = self.client.chat(retry_msgs, max_completion_tokens=self.max_out, json_mode=True)
            result2 = validate(parse_json(text2), self.catalog, shown)
            usage = {"prompt_tokens": (usage.get("prompt_tokens") or 0) + (usage2.get("prompt_tokens") or 0),
                     "completion_tokens": (usage.get("completion_tokens") or 0) + (usage2.get("completion_tokens") or 0)}
            if result2["confidence_level"] != "INVALID_CANDIDATE":
                result, text = result2, text2
            else:
                result["flags"] = ",".join(f for f in (result["flags"] + ",EXCLUDE_RETRY_FAILED").split(",") if f)
        result.update({
            "query_id": row.get("query_id"), "channel": row["channel"], "source_table": row["source_table"],
            "source_column": row["source_column"], "source_desc": row.get("as_is_desc") or PSEUDO_DESC.get(row["source_column"], ""),
            "target_table_rule": table, "retrieval_mode": self.mode,
            "prompt_tokens_est": est, "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "elapsed_sec": round(time.time() - t0, 1), "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "raw_answer": text,
        })
        ev = []
        used = set(result.get("evidence_ok") or [])
        for rank, c in enumerate(facts, 1):
            ev.append({"query_id": row.get("query_id"), "chunk_id": c["chunk_id"], "kind": "조회", "doc_type": c["doc_type"], "rank": rank,
                       "score": None, "cos": None, "bm25": None, "used_by_ai": c["chunk_id"] in used, "excerpt": _clip(c["text"], 200)})
        for rank, h in enumerate(hits, 1):
            c = h["chunk"]
            ev.append({"query_id": row.get("query_id"), "chunk_id": c["chunk_id"], "kind": "검색", "doc_type": c["doc_type"], "rank": rank,
                       "score": round(h["score"], 4), "cos": round(h["cos"], 4), "bm25": round(h["bm25"], 4), "used_by_ai": c["chunk_id"] in used,
                       "excerpt": _clip(c["text"], 200)})
        return result, ev

    # ---- 한 컬럼 추천(새 방식, 2026-09-27) ----
    def recommend_v2(self, row):
        """'하나만 골라라' 대신 목표 후보 표 전체에 게이트·점수를 매기게 하고, 코드가 문턱값(MIN_MAP_SCORE)을 넘는
        최고 확신도 후보를 고른다(08_후보비교_흐름에서 검증됨). 후보가 뽑히면 그 하나만 놓고 기존 recommend()와
        같은 단일-후보 검증(validate)을 한 번 더 돌려 mapping_type/process_type/rule/근거까지 채운다.
        전부 실격이면(문턱값 미달 포함) EXCLUDE로 보고, 가장 근접했던 후보를 근거로 제외 확신도를 코드가 계산한다."""
        t0 = time.time()
        table, facts, hits = self.gather(row)
        scan_msgs = build_candidate_scan_messages(self.catalog, row, table, facts, hits)
        scan_est = sum(est_tokens(m["content"]) for m in scan_msgs)
        scan_text, scan_usage = self.client.chat(scan_msgs, max_completion_tokens=2200, json_mode=True)
        cand_map, scan_flags = validate_candidate_scan(parse_json(scan_text), self.catalog, table)
        decision, scored = pick_best_candidate(cand_map)
        if scan_flags:
            decision = {"decision":"REVIEW","target":None,"confidence_score":None,"confidence_level":"INVALID_CANDIDATE","reason":"INCOMPLETE_OR_INVALID_CANDIDATE_SCAN"}

        prompt_tokens = scan_usage.get("prompt_tokens") or 0
        completion_tokens = scan_usage.get("completion_tokens") or 0
        raw_answer = scan_text
        extra_flags = list(scan_flags)
        if decision["decision"] == "REVIEW": extra_flags.append("INSUFFICIENT_EVIDENCE_NOT_EXCLUSION")

        if decision["decision"] == "MAPPED":
            one_cat = _OneCandidateCatalog(self.catalog, table, decision["target"])
            orig_catalog = self.catalog
            try:
                self.catalog = one_cat
                msgs2 = self.build_messages(row, table, facts, hits)
                text2, usage2 = self.client.chat(msgs2, max_completion_tokens=self.max_out, json_mode=True)
                shown2 = {c["chunk_id"] for c in facts} | {h["chunk"]["chunk_id"] for h in hits} | \
                         {f"TOBE-{table}.{r['COLUMN_NAME']}" for r in one_cat.by_table[table]}
                result = validate(parse_json(text2), one_cat, shown2)
                if result["confidence_level"] == "INVALID_CANDIDATE" and \
                        ("NO_EXCLUDE_REASON" in result["flags"] or "NO_EXCLUDE_CONFIDENCE" in result["flags"]):
                    # 2차 상세검증에서 AI가 마음을 바꿔 EXCLUDE로 답했는데 사유/확신도를 빠뜨린 경우 —
                    # 한 번만 다시 물어본다(recommend()의 D-09 재질문과 동일한 안전장치, 2026-09-27 추가)
                    retry_msgs = msgs2 + [
                        {"role": "assistant", "content": text2},
                        {"role": "user", "content": "방금 답에서 exclude_reason 또는 exclude_confidence 가 비어 있었습니다. "
                                                     "제외(EXCLUDE)로 답할 때는 exclude_reason(제외 이유 한 문장)과 "
                                                     "exclude_confidence(0~1 숫자)를 반드시 채워서, 같은 형식의 JSON으로 다시 답하세요."},
                    ]
                    text2b, usage2b = self.client.chat(retry_msgs, max_completion_tokens=self.max_out, json_mode=True)
                    result2 = validate(parse_json(text2b), one_cat, shown2)
                    usage2 = {"prompt_tokens": (usage2.get("prompt_tokens") or 0) + (usage2b.get("prompt_tokens") or 0),
                              "completion_tokens": (usage2.get("completion_tokens") or 0) + (usage2b.get("completion_tokens") or 0)}
                    if result2["confidence_level"] != "INVALID_CANDIDATE":
                        result, text2 = result2, text2b
                    else:
                        result["flags"] = ",".join(f for f in (result["flags"] + ",EXCLUDE_RETRY_FAILED").split(",") if f)
            finally:
                self.catalog = orig_catalog
            prompt_tokens += usage2.get("prompt_tokens") or 0
            completion_tokens += usage2.get("completion_tokens") or 0
            raw_answer = raw_answer + "\n---detail_call---\n" + text2
            if result["confidence_level"] == "INVALID_CANDIDATE":
                extra_flags.append("SCAN_PICKED_BUT_DETAIL_REJECTED")
        else:
            result = {
                "parse_ok": True, "ai_target": "EXCLUDE" if decision["decision"] == "EXCLUDE" else None, "ai_target_table": None, "ai_target_column": None,
                "ai_mapping_type": "EXCLUDE" if decision["decision"] == "EXCLUDE" else None, "ai_process_type": "NONE" if decision["decision"] == "EXCLUDE" else None, "ai_rule": None,
                "ai_exclude_reason": decision["reason"] if decision["decision"] == "EXCLUDE" else None, "ai_reason": decision["reason"],
                "evidence_ok": [], "evidence_dropped": [],
                "gate_relation": "NA", "gate_datatype": "NA",
                **{f"score_{k.lower()}": None for k in WEIGHTS},
                "confidence_score": decision["confidence_score"], "confidence_level": decision["confidence_level"],
                "confidence_formula": f"후보 {len(scored)}개 전체 비교 방식 — 게이트·문턱값({MIN_MAP_SCORE}) 통과 후보 없음, confidence_score=가장 근접했던 후보의 점수(그대로)",
                "flags": "", "needs_human_review": "Y", "criteria_version": CRITERIA_VERSION,
            }

        if extra_flags:
            result["flags"] = ",".join(f for f in (str(result.get("flags") or "") + "," + ",".join(extra_flags)).split(",") if f)

        result.update({
            "query_id": row.get("query_id"), "channel": row["channel"], "source_table": row["source_table"],
            "source_column": row["source_column"], "source_desc": row.get("as_is_desc") or PSEUDO_DESC.get(row["source_column"], ""),
            "target_table_rule": table, "retrieval_mode": self.mode,
            "prompt_tokens_est": scan_est, "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
            "elapsed_sec": round(time.time() - t0, 1), "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "raw_answer": raw_answer,
        })
        ev = []
        used = set(result.get("evidence_ok") or [])
        for rank, c in enumerate(facts, 1):
            ev.append({"query_id": row.get("query_id"), "chunk_id": c["chunk_id"], "kind": "조회", "doc_type": c["doc_type"], "rank": rank,
                       "score": None, "cos": None, "bm25": None, "used_by_ai": c["chunk_id"] in used, "excerpt": _clip(c["text"], 200)})
        for rank, h in enumerate(hits, 1):
            c = h["chunk"]
            ev.append({"query_id": row.get("query_id"), "chunk_id": c["chunk_id"], "kind": "검색", "doc_type": c["doc_type"], "rank": rank,
                       "score": round(h["score"], 4), "cos": round(h["cos"], 4), "bm25": round(h["bm25"], 4), "used_by_ai": c["chunk_id"] in used,
                       "excerpt": _clip(c["text"], 200)})
        return result, ev


# ---------------- 검증과 확신도 ----------------
def normalize_target(t):
    s = str(t or "").strip()
    if s.upper() in ("", "EXCLUDE", "NONE", "NULL", "N/A", "미매핑"):
        return "EXCLUDE"
    s = s.split("|")[-1].strip()
    s = re.sub(r"^TOBE-", "", s, flags=re.I)
    s = s.upper()
    if "EXCLUDE" in s or s.split(".")[-1] in ("NONE", "NULL", ""):
        return "EXCLUDE"
    return s


def _num(x):
    try:
        v = float(x)
        return min(1.0, max(0.0, v))
    except Exception:
        return None


def confidence_level(score):
    if score is None:
        return "LOW"
    if score >= 0.90:
        return "HIGH"
    if score >= 0.70:
        return "REVIEW"
    return "LOW"


def _legacy_validate(parsed, catalog, shown_ids):
    """AI 답을 검사하고 확신도를 코드로 계산한다."""
    flags = []
    out = {"parse_ok": bool(parsed)}
    if not parsed or not isinstance(parsed, dict):
        out.update({"ai_target": None, "ai_target_table": None, "ai_target_column": None, "ai_mapping_type": None, "ai_process_type": None,
                    "ai_rule": None, "ai_exclude_reason": None, "ai_reason": None, "evidence_ok": [], "evidence_dropped": [],
                    "confidence_score": None, "confidence_level": "INVALID_CANDIDATE", "flags": "JSON_PARSE_FAIL",
                    "gate_relation": None, "gate_datatype": None, **{f"score_{k.lower()}": None for k in WEIGHTS},
                    "needs_human_review": "Y", "criteria_version": CRITERIA_VERSION})
        return out
    target = normalize_target(parsed.get("target"))
    is_ex = target == "EXCLUDE"
    mtype = str(parsed.get("mapping_type") or "").upper().strip()
    ptype = str(parsed.get("process_type") or "").upper().strip()
    if is_ex:
        mtype, ptype = "EXCLUDE", "NONE"
    else:
        if mtype not in MAPPING_TYPES or mtype == "EXCLUDE":
            flags.append("BAD_MAPPING_TYPE")
        if ptype not in PROCESS_TYPES or ptype == "NONE":
            flags.append("BAD_PROCESS_TYPE")
    target_ok = is_ex or catalog.exists(target)
    if not target_ok:
        flags.append("TARGET_NOT_IN_CANDIDATES")
    ev_all = [str(x).strip() for x in (parsed.get("evidence") or []) if str(x).strip()]
    ev_all = [re.sub(r"^chunk_id:\s*", "", x) for x in ev_all]
    ev_ok = [x for x in ev_all if x in shown_ids]
    ev_bad = [x for x in ev_all if x not in shown_ids]
    if ev_bad:
        flags.append("EVIDENCE_NOT_SHOWN")
    if not ev_ok and not is_ex:
        flags.append("NO_EVIDENCE")

    gates = parsed.get("gates") if isinstance(parsed.get("gates"), dict) else {}
    g = {k: str(gates.get(k) or "NA").upper() for k in GATES}
    scores = parsed.get("scores") if isinstance(parsed.get("scores"), dict) else {}
    sc = {k: _num(scores.get(k)) for k in WEIGHTS}

    if is_ex:
        conf = _num(parsed.get("exclude_confidence"))
        if not parsed.get("exclude_reason"):
            flags.append("NO_EXCLUDE_REASON")
        if conf is None:
            flags.append("NO_EXCLUDE_CONFIDENCE")
        if "NO_EXCLUDE_REASON" in flags or "NO_EXCLUDE_CONFIDENCE" in flags:
            # 사유·확신도 없는 제외는 정상 추천이 아니다 — 승인 대상에서 막는다(재질문은 recommend()에서 1회 시도)
            level = "INVALID_CANDIDATE"
            formula = "제외 추천인데 사유/확신도가 비었음 — 사람 확인 전까지 무효(INVALID_CANDIDATE)"
        else:
            level = confidence_level(conf)
            level = "REVIEW" if level == "HIGH" else level  # 제외는 자동 확정하지 않는다: 최대 REVIEW
            formula = "제외 추천: AI가 답한 '제외 확신'을 그대로 사용(최대 REVIEW)"
        g = {k: "NA" for k in GATES}
    else:
        used = {k: v for k, v in sc.items() if v is not None}
        w = sum(WEIGHTS[k] for k in used)
        conf = round(sum(used[k] * WEIGHTS[k] for k in used) / w, 3) if w else None
        level = confidence_level(conf)
        formula = f"Σ(점수×가중치)/Σ(적용 가중치), 적용 항목 {len(used)}개"
        if "FAIL" in g.values():
            level = "INVALID_CANDIDATE"
            flags.append("GATE_FAIL")
        if not target_ok:
            level = "INVALID_CANDIDATE"
    tt, tc = (target.split(".", 1) + [None])[:2] if not is_ex else (None, None)
    out.update({
        "ai_target": target, "ai_target_table": tt, "ai_target_column": tc,
        "ai_mapping_type": mtype or None, "ai_process_type": ptype or None,
        "ai_rule": parsed.get("rule"), "ai_exclude_reason": parsed.get("exclude_reason"), "ai_reason": parsed.get("reason") or parsed.get("exclude_reason"),
        "evidence_ok": ev_ok, "evidence_dropped": ev_bad,
        "gate_relation": g["RELATION_FIT"], "gate_datatype": g["DATATYPE_CONVERTIBLE"],
        **{f"score_{k.lower()}": sc[k] for k in WEIGHTS},
        "confidence_score": conf, "confidence_level": level, "confidence_formula": formula,
        "flags": ",".join(flags), "needs_human_review": "Y",   # HIGH 라도 사람이 확인한다
        "criteria_version": CRITERIA_VERSION,
    })
    return out


def validate(parsed, catalog, shown_ids):
    result=_legacy_validate(parsed,catalog,shown_ids)
    if not isinstance(parsed,dict) or normalize_target(parsed.get('target'))=='EXCLUDE':return result
    e=evaluate_scores(parsed.get('scores'),parsed.get('score_status'),parsed.get('na_reasons'))
    flags=set(filter(None,str(result.get('flags') or '').split(',')))
    if e['missing']:flags.add('MISSING_SCORE_EVIDENCE')
    if e['invalid']:flags.add('INVALID_SCORE_VALUE')
    gates=parsed.get('gates') if isinstance(parsed.get('gates'),dict) else {}
    if any(str(gates.get(k) or '').upper()!='PASS' for k in GATES):flags.add('MANDATORY_GATE_NOT_PASS')
    if not e['observed']:flags.add('NO_OBSERVED_SCORES')
    if not result.get('evidence_ok'):flags.add('NO_EVIDENCE')
    blockers={'MANDATORY_GATE_NOT_PASS','NO_OBSERVED_SCORES','INVALID_SCORE_VALUE','NO_EVIDENCE','EVIDENCE_NOT_SHOWN','BAD_MAPPING_TYPE','BAD_PROCESS_TYPE','TARGET_NOT_IN_CANDIDATES'}
    result['confidence_score']=e['confidence']
    result['confidence_level']='INVALID_CANDIDATE' if flags&blockers else confidence_level(e['confidence'])
    if e['missing'] and result['confidence_level']=='HIGH':result['confidence_level']='REVIEW'
    result['flags']=','.join(sorted(flags))
    result['confidence_formula']='Observed weighted scores / all applicable weights; missing is not N/A.'
    result['score_evidence_status']=e
    result['needs_human_review']='Y'
    return result


SYSTEM_RULES += "\n추가 규약: score_status에 각 항목의 OBSERVED / NA / MISSING을 기록한다. NA일 때는 na_reasons에 구체적인 이유를 기록한다. 점수를 알 수 없으면 MISSING이다. 필수 게이트는 PASS가 확인되지 않으면 판단 보류다."
CANDIDATE_SCAN_SYSTEM_RULES += "\n추가 규약: score_status에 각 항목의 OBSERVED / NA / MISSING을 기록한다. NA일 때는 na_reasons에 구체적인 이유를 기록한다. 점수를 알 수 없으면 MISSING이다. 필수 게이트는 PASS가 확인되지 않으면 판단 보류다."
