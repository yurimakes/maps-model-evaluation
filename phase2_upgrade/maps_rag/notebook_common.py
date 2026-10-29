# -*- coding: utf-8 -*-
"""노트북들이 같이 쓰는 도우미 (키 읽기, 한글 머리글, 표 요약 등)."""
import os

ENDPOINT_DEFAULT = "https://maps5dt2-openai-poc.openai.azure.com/"
SECRET_SCOPE, SECRET_KEY = "maps_ai_demo", "azure_openai_key"

# 결과 표의 칸 이름(영문) → 사람이 읽는 한글 뜻
KO = {
    "query_id": "질문번호", "channel": "채널", "source_table": "원천표", "source_column": "원천컬럼", "source_desc": "원천 설명",
    "target_table_rule": "규칙상 목표표", "ai_target": "AI가 추천한 목표 칸", "ai_target_table": "추천 목표표", "ai_target_column": "추천 목표칸",
    "ai_mapping_type": "매핑 종류", "ai_process_type": "처리 방식", "ai_rule": "변환 규칙 설명", "ai_exclude_reason": "제외 이유",
    "ai_reason": "추천 이유", "confidence_score": "확신도 점수", "confidence_level": "확신도 등급", "confidence_formula": "확신도 계산식",
    "gate_relation": "관문: 업무관계", "gate_datatype": "관문: 타입변환",
    "score_name": "점수: 이름", "score_description": "점수: 설명", "score_domain": "점수: 도메인", "score_datatype": "점수: 타입",
    "score_sample": "점수: 샘플값", "score_code": "점수: 코드값", "score_relation": "점수: 업무관계",
    "evidence_ids": "근거 이름표", "evidence_dropped": "버린 근거(가짜 이름표)", "flags": "주의 표시", "needs_human_review": "사람 확인 필요",
    "retrieval_mode": "검색 방식", "prompt_tokens_est": "질문 토큰(추정)", "prompt_tokens": "질문 토큰(실측)", "completion_tokens": "답변 토큰",
    "elapsed_sec": "걸린 시간(초)", "created_at": "만든 시각", "parse_ok": "답 형식 OK", "criteria_version": "채점 기준 출처",
    "source_batch_id": "원천 배치번호", "dq_run_id": "DQ 실행번호",
}
RESULT_COLS = ["query_id", "channel", "source_table", "source_column", "source_desc", "target_table_rule", "ai_target", "ai_target_table", "ai_target_column", "ai_mapping_type",
               "ai_process_type", "ai_rule", "ai_exclude_reason", "ai_reason", "confidence_score", "confidence_level", "confidence_formula", "gate_relation", "gate_datatype",
               "score_name", "score_description", "score_domain", "score_datatype", "score_sample", "score_code", "score_relation",
               "evidence_ids", "evidence_dropped", "flags", "needs_human_review", "retrieval_mode", "prompt_tokens_est", "prompt_tokens",
               "completion_tokens", "elapsed_sec", "created_at", "criteria_version", "source_batch_id", "dq_run_id"]

# 주의 표시(flags) 코드 → 사람이 읽는 설명. 결과 화면에서 "왜 안 됐는지"를 풀어 쓸 때 쓴다.
FLAG_KO = {
    "BAD_MAPPING_TYPE": "매핑 종류 답이 정해진 목록에 없음",
    "BAD_PROCESS_TYPE": "처리 방식 답이 정해진 목록에 없음",
    "TARGET_NOT_IN_CANDIDATES": "AI가 고른 목표 칸이 후보 목록에 없음",
    "EVIDENCE_NOT_SHOWN": "AI가 보여주지 않은 근거 이름표를 인용함(근거 조작 의심)",
    "NO_EVIDENCE": "근거를 하나도 인용하지 않음",
    "NO_EXCLUDE_REASON": "제외 추천인데 이유를 안 씀",
    "NO_EXCLUDE_CONFIDENCE": "제외 추천인데 확신도 숫자를 안 씀",
    "GATE_FAIL": "필수 관문(업무관계 또는 타입변환) 중 하나가 FAIL",
    "EXCLUDE_RETRY_FAILED": "이유·확신도를 채우라고 한 번 더 물었지만 그래도 안 채워짐",
    "JSON_PARSE_FAIL": "AI 답변이 정해진 형식(JSON)이 아니어서 못 읽음",
}


def explain_flags(flags):
    """'NO_EXCLUDE_REASON,NO_EXCLUDE_CONFIDENCE' 같은 flags 글자를 사람이 읽는 문장으로 풀어 쓴다."""
    codes = [c for c in str(flags or "").split(",") if c]
    if not codes:
        return ""
    return " / ".join(FLAG_KO.get(c, c) for c in codes)


# 6.1 평가 기준서(6.1-A) 그대로: 평가항목 한글 이름과 "평가 내용" 설명. WEIGHTS(recommend.py)와 키가 같다.
CRITERIA_KO_NAME = {"NAME": "명칭", "DESCRIPTION": "설명", "DOMAIN": "도메인", "DATATYPE": "데이터타입",
                     "SAMPLE": "샘플값", "CODE": "코드값", "RELATION": "업무관계"}
CRITERIA_DESC = {
    "NAME": "Source/Target 컬럼명, 표준단어·표준용어의 의미 유사도",
    "DESCRIPTION": "한글 속성명, Comment, 업무 설명의 의미 유사도",
    "DOMAIN": "고객·상품·계약·상담·민원 등 업무 Domain 적합성",
    "DATATYPE": "Datatype, 길이, 형식 및 안전한 변환 가능성",
    "SAMPLE": "값 패턴, 길이, NULL/Distinct 특성, 날짜·전화·이메일 형식 등",
    "CODE": "Source 코드 의미와 TO-BE 표준코드 의미의 대응 가능성 (해당 없으면 N/A)",
    "RELATION": "Source Entity/업무목적과 Target Entity/관계 구조의 적합성",
}

# 6.1 평가 기준서(6.1-C 5.1) 필수 게이트 정의 그대로.
GATE_DESC = [
    {"게이트": "업무관계 적합성(RELATION_FIT)", "PASS 기준": "Source/Target의 업무 의미와 Entity 관계가 모순되지 않음", "FAIL 처리": "INVALID_CANDIDATE 또는 Human Review"},
    {"게이트": "데이터타입 변환 가능성(DATATYPE_CONVERTIBLE)", "PASS 기준": "동일 타입이거나 명확하고 안전한 변환 Rule 존재", "FAIL 처리": "INVALID_CANDIDATE"},
]

# 근거 이름표(evidence_id) 접두어 규칙. knowledge/facts 가 실제로 만드는 chunk_id 형식과 doc_type 대응.
EVIDENCE_PREFIX = [
    {"형식": "TOBE-표.칸", "뜻": "목표(타겟) 칸 규격 — 항상 후보로 함께 보여줌", "doc_type": "TARGET_COLUMN"},
    {"형식": "DQ-PRF-번호", "뜻": "이 원천 컬럼의 품질검사·프로파일링 결과(정확 조회, 같은 채널만)", "doc_type": "DQ_RULE"},
    {"형식": "SRCCODE-번호", "뜻": "원천 코드표(코드값의 실제 의미, 정확 조회)", "doc_type": "SOURCE_CODE_MASTER"},
    {"형식": "CODE-코드그룹명", "뜻": "TO-BE 표준코드 사전(코드형 컬럼일 때 조회)", "doc_type": "STD_CODE"},
    {"형식": "TERM-번호", "뜻": "표준용어 사전(검색으로 찾음)", "doc_type": "STD_TERM"},
    {"형식": "WORD-번호", "뜻": "표준단어 사전(검색으로 찾음)", "doc_type": "STD_WORD"},
    {"형식": "DOM-이름", "뜻": "표준 도메인 사전(검색으로 찾음)", "doc_type": "STD_DOMAIN"},
    {"형식": "DSN-M#/R#", "뜻": "팀 설계결정 문서(검색으로 찾음, 정답 성격 문서는 애초에 제외)", "doc_type": "DESIGN_DECISION"},
]


# DQ 규칙 카드 원문("역할 X, 업무키 Y. 검사: A,B. 기준: ... 실패 시 Z.")에 나오는 용어 → 쉬운 뜻.
# 지식_10_DQ규칙.jsonl 전체를 훑어서 실제로 쓰이는 값만 담았다(2026-09-23 확인).
DQ_ROLE_KO = {
    "BUSINESS_KEY": "업무상 핵심 식별자(이 값으로 레코드를 구분함)",
    "TECHNICAL_PK": "시스템 내부용 기술적 기본키",
    "CODE": "코드값(정해진 코드표 안의 값이어야 함)",
    "DATE_DATETIME": "날짜/일시 값",
    "EMAIL": "이메일 주소",
    "PHONE": "전화번호",
    "TEXT": "자유롭게 쓰는 글(자유 텍스트)",
    "CROSS_COLUMN": "다른 컬럼과 관계를 맞춰봐야 하는 값(예: 시작일 ≤ 종료일)",
    "GENERAL": "일반 값(특별한 역할 없음)",
}
DQ_CHECK_KO = {
    "NULL_CHECK": "빈 값(NULL) 검사",
    "DUPLICATE_CHECK": "중복 검사",
    "CODE_MASTER_CHECK": "코드표에 있는 값인지 검사",
    "DATETIME_RELATION": "다른 일시 컬럼과의 순서 관계 검사",
    "DATE_PARSE_CHECK": "날짜 형식으로 읽히는지 검사",
    "EMAIL_FORMAT_CHECK": "이메일 형식 검사",
    "LENGTH_LIMIT_CHECK": "길이 제한 검사",
    "METADATA_CONSTRAINT_CHECK": "메타데이터상 제약조건(필수 여부 등) 검사",
    "PHONE_FORMAT_CHECK": "전화번호 형식 검사",
    "WHITESPACE_CASE_CHECK": "공백·대소문자 검사",
}


def explain_dq_text(text):
    """DQ 규칙 카드 원문 한 줄을 '역할=... / 검사=... / 실패 시 ...' 쉬운 문장으로 풀어 쓴다."""
    import re
    if not text:
        return None
    parts = []
    m = re.search(r"역할 ([A-Z_]+)", text)
    if m:
        r = m.group(1)
        parts.append(f"역할={r}({DQ_ROLE_KO.get(r, '(설명 없음)')})")
    m = re.search(r"검사:\s*([A-Z_,]+)", text)
    if m:
        cs = [c for c in m.group(1).split(",") if c]
        parts.append("검사=" + ", ".join(f"{c}({DQ_CHECK_KO.get(c, '(설명 없음)')})" for c in cs))
    m = re.search(r"실패 시 (\w+)", text)
    if m:
        parts.append(f"실패 시 → {m.group(1)} 처리")
    return " / ".join(parts) if parts else None


# 매핑/처리 종류 → 쉬운 뜻 (SYSTEM_RULES 프롬프트에 적힌 설명과 동일한 내용).
MAPPING_TYPE_KO = {
    "DIRECT": "이름·값 그대로 대응",
    "RENAME": "이름만 표준 이름으로 바꿔서 대응",
    "TRANSFORM": "값을 표준 형식으로 변환해서 대응",
    "CODE": "코드값을 표준코드로 변환해서 대응",
    "DERIVED": "다른 자료로 조회하거나 새로 만들어서 채움",
    "EXCLUDE": "이번 이행 대상에서 제외",
}
PROCESS_TYPE_KO = {
    "COPY": "그대로 복사", "FORMAT": "형식 변환", "LOOKUP": "다른 표를 조회해서 채움",
    "CONSTANT": "고정값(상수)으로 채움", "GENERATE_ID": "새 번호를 만들어서 채움",
    "EXPLODE": "배열 하나를 여러 행으로 풀어서 채움", "CUSTOMER_MATCH": "고객을 찾아 연결해서 채움",
    "NONE": "실행 없음(제외일 때)",
}


# 6.1-A 원문의 "결과" 칸(대부분 Score 0~1, 코드값만 N/A 가능) — WEIGHTS 와 같은 순서.
CRITERIA_RESULT_KO = {k: ("Score 0~1 또는 N/A" if k == "CODE" else "Score 0~1")
                       for k in ["NAME", "DESCRIPTION", "DOMAIN", "DATATYPE", "SAMPLE", "CODE", "RELATION"]}


def evidence_explain(query_id, ev):
    """이 칸에 AI가 실제로 인용한 근거들을 'id: 내용' 여러 줄로 풀어 쓴다. ev 는 ai_evidence 표(pandas)."""
    if ev is None or len(ev) == 0:
        return "(근거 표 없음)"
    sub = ev[(ev["query_id"] == query_id) & (ev["used_by_ai"] == True)]  # noqa: E712
    if len(sub) == 0:
        return "(AI가 실제로 인용한 근거 없음)"
    return "\n".join(f"[{row.chunk_id}] {row.excerpt}" for row in sub.itertuples())


def with_ko_headers(pdf):
    """영문 칸 이름 뒤에 한글 뜻을 괄호로 붙인 사본(화면·CSV 용). 저장용 표는 영문 이름 그대로 둔다."""
    out = pdf.copy()
    out.columns = [f"{c}({KO[c]})" if c in KO else c for c in out.columns]
    return out


def get_key(dbutils=None):
    k = os.environ.get("MAPS_AZURE_KEY")          # 내 컴퓨터 연습용
    if k:
        return k
    if dbutils is None:
        raise RuntimeError("비밀 보관함을 읽으려면 dbutils 가 필요합니다.")
    try:
        return dbutils.secrets.get(SECRET_SCOPE, SECRET_KEY)
    except Exception as e:
        raise RuntimeError(f"비밀 보관함({SECRET_SCOPE}/{SECRET_KEY})을 읽지 못했습니다: {e}")


def endpoint():
    return os.environ.get("MAPS_AZURE_ENDPOINT", ENDPOINT_DEFAULT)


def flatten_result(res):
    """추천 결과 dict → 저장용 한 줄(리스트는 글자로)."""
    r = dict(res)
    r["evidence_ids"] = "; ".join(r.pop("evidence_ok", []) or [])
    r["evidence_dropped"] = "; ".join(r.get("evidence_dropped") or [])
    r.pop("raw_answer", None)
    return {c: r.get(c) for c in RESULT_COLS}


def pick_subset(df, n):
    """채널마다 고르게(간격을 두고) 정확히 n 개 뽑는다. n 이 전체 이상이면 전부."""
    if n >= len(df):
        return df.copy()
    total = len(df)
    groups = [(ch, g) for ch, g in df.groupby("channel", sort=False)]
    quota = {ch: n * len(g) / total for ch, g in groups}
    take = {ch: max(1, int(q)) for ch, q in quota.items()}
    while sum(take.values()) < n:        # 남는 자리는 소수점이 큰 채널부터 채운다
        ch = max(quota, key=lambda c: quota[c] - take[c])
        take[ch] += 1
    while sum(take.values()) > n:
        ch = max(take, key=lambda c: take[c] - quota[c])
        take[ch] -= 1
    picked = []
    for ch, g in groups:
        k = min(take[ch], len(g))
        step = len(g) / k
        picked += [g.index[int(i * step)] for i in range(k)]
    return df.loc[sorted(set(picked))].copy()


def load_prev(spark, delta_io, table, need):
    """이전에 저장한 표를 읽는다. 표가 없거나, 예전 버전이 만든 표라 필요한 칸이 없으면 None(새로 덮어쓴다)."""
    if not delta_io.table_exists(spark, table):
        return None
    df = delta_io.read_table(spark, table)
    if not set(need) <= set(df.columns):
        print(f"ℹ 예전 버전이 만든 '{table}' 표는 칸 구성이 달라서 무시하고 새 표로 덮어씁니다.")
        return None
    return df
