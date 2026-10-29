# -*- coding: utf-8 -*-
"""원천 데이터 읽기 + 컬럼 프로파일 만들기.

★ 이 파일이 '원천을 어디서 가져오는가'를 바꾸는 유일한 자리다.
  FILES      : 팀 폴더에서 복사해 온 파일(CSV·JSON)을 읽는다. 오프라인 리허설·개발용.
  DATABRICKS : 팀이 만든 진짜 실버 표(`maps_databricks.silver.*`)를 **읽기 전용**으로 가져온다. 실제 Databricks 실행의 기본값.
나머지 코드는 '채널별 데이터프레임(값들의 표)'만 받으므로 어느 쪽을 쓰든 바뀌지 않는다.

쉬운 설명
- 프로파일 = 컬럼별 건강검진표: 빈 값 비율(NULL%), 값 종류 수, 가장 많이 나온 값. AI가 컬럼의 성격을 알 때 쓴다.
- 개인정보(이름·전화·주민번호 등)는 모양만 남기고(999-9999-9999), 긴 자유 글은 길이만 보여 준다.
- 팀 실버 표에는 절대 쓰지 않는다(SELECT 만 한다). 저장은 항상 `hive_metastore.maps_ai_demo` 에만 한다(delta_io.py 참고).
"""
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd

CHANNELS = ["INBOUND", "OUTBOUND", "SALESFORCE", "HOMEPAGE", "CHATBOT"]   # 있을 수 있는 채널 전체(이름·규칙 정의용)
# ★ 지금 실제로 쓰는 채널. 팀 실버 표(maps_databricks.silver.*)에 진짜 데이터가 들어온 채널만 여기 넣는다.
#   나머지 채널은 표는 있어도 아직 비어 있거나 안 채워졌을 수 있어서, 아예 읽지 않고 건너뛴다(보류).
#   다른 채널의 실버가 채워지면 이 줄에 채널 이름만 추가하면 된다. 다른 코드는 고칠 필요 없음.
ACTIVE_CHANNELS = ["HOMEPAGE"]
CHANNEL_KO = {"INBOUND": "인바운드", "OUTBOUND": "아웃바운드", "SALESFORCE": "세일즈포스", "HOMEPAGE": "홈페이지", "CHATBOT": "챗봇"}
# 채널 → 목표 표 (고정 규칙)
CHANNEL_TO_TARGET = {"INBOUND": "COUNSEL", "OUTBOUND": "COUNSEL", "SALESFORCE": "COUNSEL", "CHATBOT": "COUNSEL", "HOMEPAGE": "COMPLAINT"}

# 로컬 복사본 파일 (FILES 모드, 오프라인 리허설용)
LOCAL_FILES = {
    "INBOUND": "1_원천데이터(브론즈)/1_인바운드(콜센터)/인바운드_원천_상담_1000행.csv",
    "OUTBOUND": "1_원천데이터(브론즈)/2_아웃바운드(TM)/아웃바운드_원천_TM상담_1000행.csv",
    "SALESFORCE": "1_원천데이터(브론즈)/3_세일즈포스(웹상담)/세일즈포스_원천_상담_1000행.csv",
    "HOMEPAGE": "1_원천데이터(브론즈)/4_홈페이지(민원)/홈페이지_원천_민원_1000행.csv",
    "CHATBOT": "1_원천데이터(브론즈)/5_챗봇/챗봇_원천_세션_1005건.json",
}

# 팀 실버 표 (DATABRICKS 모드, 실제 Databricks 실행 시 기본값). 읽기만 한다.
DATABRICKS_TABLES = {
    "INBOUND": "maps_databricks.silver.inbound",
    "OUTBOUND": "maps_databricks.silver.outbound",
    "SALESFORCE": "maps_databricks.silver.salesforce",
    "HOMEPAGE": "maps_databricks.silver.homepage",
    "CHATBOT": "maps_databricks.silver.chatbot",
}
# 팀 실버 표에 업무 컬럼과 함께 붙어 있는 '파이프라인 관리용' 컬럼(매핑 추천 대상이 아님)
DATABRICKS_HOUSEKEEPING_COLS = {
    "ingest_date", "_source_system", "_source_table", "_source_record_key", "_source_batch_id",
    "_dq_run_id", "_cleansed_yn", "_candidate_created_at", "_dq_status", "_release_id", "_published_at",
}


class FileSource:
    """복사해 온 파일에서 읽기 (오프라인용)."""
    name = "FILES(복사본 파일, 오프라인용)"

    def __init__(self, base):
        self.base = Path(base)

    def load(self, channel):
        p = self.base / LOCAL_FILES[channel]
        if channel == "CHATBOT":
            return json.loads(p.read_text(encoding="utf-8"))["sessions"]   # 세션 목록(중첩 구조 그대로)
        return pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig")


class DatabricksSource:
    """팀이 만든 진짜 실버 표를 읽기 전용으로 가져오기(SELECT 만). spark 는 노트북의 spark.
    batch_id/dq_run_id 를 주면, 관리용 컬럼(`_source_batch_id`/`_dq_run_id`)으로 그 배치·DQ 실행에
    해당하는 행만 걸러서 돌려준다(둘 다 안 주면 지금까지처럼 표 전체)."""
    name = "DATABRICKS(maps_databricks.silver.*, 읽기 전용)"

    def __init__(self, spark, tables=None, batch_id=None, dq_run_id=None):
        self.spark = spark
        self.tables = tables or DATABRICKS_TABLES
        self.batch_id = batch_id or None
        self.dq_run_id = dq_run_id or None

    def load(self, channel):
        t = self.tables.get(channel)
        if not t:
            raise ValueError(f"{channel} 의 Databricks 표 이름이 비어 있습니다. source_loader.DATABRICKS_TABLES 를 채우세요.")
        df = self.spark.table(t).toPandas()   # SELECT 만. 쓰기는 절대 하지 않는다
        if self.batch_id and "_source_batch_id" in df.columns:
            df = df[df["_source_batch_id"].astype(str) == str(self.batch_id)]
        if self.dq_run_id and "_dq_run_id" in df.columns:
            df = df[df["_dq_run_id"].astype(str) == str(self.dq_run_id)]
        drop = [c for c in df.columns if c in DATABRICKS_HOUSEKEEPING_COLS]
        return df.drop(columns=drop)


def make_source(mode="FILES", base=None, spark=None, batch_id=None, dq_run_id=None):
    if mode == "FILES":
        return FileSource(base)
    if mode == "DATABRICKS":
        return DatabricksSource(spark, batch_id=batch_id, dq_run_id=dq_run_id)
    raise ValueError(mode)


def channel_row_counts(spark, tables=None):
    """채널별 실버 표에 행이 몇 개 있는지 가볍게 확인한다(SELECT count(1)만, 쓰기 없음).
    표가 아직 없거나 읽다가 에러 나면 0으로 본다(그 채널은 아직 준비 안 된 것으로 취급)."""
    tables = tables or DATABRICKS_TABLES
    counts = {}
    for ch, t in tables.items():
        try:
            counts[ch] = spark.table(t).count()
        except Exception:
            counts[ch] = 0
    return counts


def active_channels_databricks(spark, tables=None):
    """실버 표에 실제로 데이터가 들어온 채널만 고른다(비어 있으면 건너뜀).
    ACTIVE_CHANNELS 를 수동으로 안 고쳐도, 팀이 다른 채널 실버를 채우는 대로 자동으로 포함된다."""
    counts = channel_row_counts(spark, tables)
    return [ch for ch in CHANNELS if counts.get(ch, 0) > 0]


# ---------------- 값 뽑기 : 챗봇(로컬 JSON, 중첩 구조) ----------------
def _chatbot_values_nested(sessions, table, column):
    vals = []
    if table == "session":
        if column.endswith("[].query"):
            key = column.split("[]")[0]
            for s in sessions:
                for q in (s.get(key) or []):
                    vals.append(q.get("query"))
            return vals
        for s in sessions:
            cur = s
            for part in column.split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            vals.append(cur)
        return vals
    if table == "session_navigation":
        for s in sessions:
            for n in (s.get("navigation_path") or []):
                vals.append(s.get("session_id") if column == "session_id" else n.get(column))
        return vals
    if table == "session_free_text_query":
        for s in sessions:
            for i, q in enumerate(s.get("free_text_queries") or [], 1):
                if column == "session_id":
                    vals.append(s.get("session_id"))
                elif column == "query_seq":
                    vals.append(i)
                else:
                    vals.append(q.get(column))
        return vals
    return None


# ---------------- 값 뽑기 : 챗봇(팀 실버 표, 평평한 구조) ----------------
# 로컬 JSON은 세션 하나 안에 방문경로·자유질문이 배열로 중첩돼 있었는데,
# 팀 실버 표(silver.chatbot)는 그걸 이미 평평한 컬럼(nav_step, nav_full_path, user_query 등)으로 풀어 둔 표 하나다.
# 그런데 "한 세션이 한 행"인지 "방문 한 걸음마다 한 행"인지는 실제로 읽어 보기 전에는 알 수 없어서,
# 아래 코드가 실행할 때(행 수와 고유 세션 수를 비교해서) 스스로 판단한다. 사람이 미리 정해 둘 필요가 없다.
_CHATBOT_FLAT_MAP = {
    ("session", "session_id"): "session_id", ("session", "channel"): "channel",
    ("session", "device_type"): "device_type", ("session", "os"): "os", ("session", "app_version"): "app_version",
    ("session", "started_at"): "started_at", ("session", "ended_at"): "ended_at",
    ("session", "duration_seconds"): "duration_seconds", ("session", "entry_login_status"): "entry_login_status",
    ("session", "is_logged_in"): "is_logged_in", ("session", "customer_id"): "customer_id",
    ("session", "intent_category_guess"): "intent_category_guess",
    ("session", "product_interest.product_code"): "product_interest",   # 실버 표에는 원문 그대로(가공 전) 들어 있음
    ("session_navigation", "session_id"): "session_id", ("session_navigation", "step"): "nav_step",
    ("session_navigation", "full_path"): "nav_full_path", ("session_navigation", "timestamp"): "nav_timestamp",
    ("session_free_text_query", "session_id"): "session_id", ("session_free_text_query", "query"): "user_query",
    ("session_free_text_query", "timestamp"): "query_timestamp",
}


def _chatbot_values_flat(df, table, column):
    key = (table, column)
    if key == ("session_free_text_query", "query_seq"):
        ft = df[df["user_query"].notna()].copy()
        return (ft.groupby("session_id").cumcount() + 1).tolist()   # 실버 표에 순번이 없어서 같은 세션 안에서 센 값(추정)
    phys = _CHATBOT_FLAT_MAP.get(key)
    if phys is None or phys not in df.columns:
        return None
    if table == "session":
        sub = df.drop_duplicates("session_id")            # 세션당 한 값(행이 여러 개면 첫 값)
    elif table == "session_navigation":
        sub = df[df.get("nav_step").notna()] if "nav_step" in df.columns else df
    else:  # session_free_text_query
        sub = df[df.get("user_query").notna()] if "user_query" in df.columns else df
    return sub[phys].tolist()


def column_values(source_data, channel, table, column):
    """한 컬럼의 모든 값 목록(없는 가상 컬럼이면 None)."""
    if column.startswith("<"):
        return None
    if channel == "CHATBOT":
        if isinstance(source_data, list):          # FILES: 세션 목록(중첩 JSON)
            return _chatbot_values_nested(source_data, table, column)
        return _chatbot_values_flat(source_data, table, column)   # DATABRICKS: 평평한 표
    df = source_data
    if column in df.columns:
        return df[column].tolist()
    low = {c.lower(): c for c in df.columns}
    if column.lower() in low:
        return df[low[column.lower()]].tolist()
    return None


def chatbot_grain(df):
    """챗봇 실버 표가 '세션당 한 행'인지 '걸음마다 한 행'인지 알려 준다(화면 확인용)."""
    if isinstance(df, list):
        return f"로컬 JSON, 세션 {len(df)}개(중첩 구조 그대로)"
    n, u = len(df), df["session_id"].nunique() if "session_id" in df.columns else None
    same = (n == u)
    return f"전체 행 {n} / 고유 세션 {u} → {'세션당 한 행' if same else '세션당 여러 행(방문·질문마다 한 행으로 보임)'}"


# ---------------- 마스킹과 프로파일 ----------------
FREE_TEXT_HINT = re.compile(r"content|note|memo|text|query|stt|summary|address|desc|comment|내용|메모", re.I)


def mask_pattern(v):
    v = str(v)
    v = re.sub(r"[가-힣]", "가", v)
    v = re.sub(r"[A-Za-z]", "X", v)
    v = re.sub(r"\d", "9", v)
    return v[:40]


def profile_column(values, column, pii=False, top_n=3):
    """values → 프로파일 dict. 개인정보는 모양만, 긴 자유 글은 길이만."""
    if values is None:
        return {"sample_count": 0, "null_pct": None, "distinct_cnt": None, "top_values": "(원천에 없는 값 — 시스템이 정해 주는 상수/구분값이거나, 실버 표에 아직 없는 컬럼)"}
    vals = [None if (v is None or (isinstance(v, float) and v != v) or str(v).strip() == "") else v for v in values]
    n = len(vals)
    nn = [str(v) for v in vals if v is not None]
    null_pct = round(100 * (n - len(nn)) / n, 1) if n else None
    cnt = Counter(nn)
    lens = [len(x) for x in nn] or [0]
    avg_len = sum(lens) / len(lens)
    is_free = (avg_len >= 40) or (FREE_TEXT_HINT.search(column) and avg_len >= 20)
    if pii:
        top = "; ".join(f"{mask_pattern(k)}({c})" for k, c in cnt.most_common(top_n))
        top = "(개인정보 — 모양만) " + top
    elif is_free:
        top = f"(자유 텍스트 — 길이 {min(lens)}~{max(lens)}자, 평균 {avg_len:.0f}자)"
    else:
        top = "; ".join(f"{str(k)[:30]}({c})" for k, c in cnt.most_common(top_n))
    return {"sample_count": n, "null_pct": null_pct, "distinct_cnt": len(cnt), "top_values": top}


def load_input_columns(path):
    """AI에게 물을 '원천 컬럼 목록'(정답 열 없음)."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def build_profiles(source, inputs_df, channels=None):
    """활성 채널(기본 ACTIVE_CHANNELS)만 읽어 컬럼별 프로파일 표를 만든다. 나머지 채널은 아예 읽지 않는다(보류)."""
    channels = list(channels) if channels is not None else list(ACTIVE_CHANNELS)
    data = {ch: source.load(ch) for ch in channels}
    rows = []
    for _, r in inputs_df[inputs_df["channel"].isin(channels)].iterrows():
        vals = column_values(data[r["channel"]], r["channel"], r["source_table"], r["source_column"])
        p = profile_column(vals, r["source_column"], pii=(r.get("pii_yn") == "Y"))
        rows.append({**r.to_dict(), **p})
    counts = {ch: len(d) for ch, d in data.items()}
    return pd.DataFrame(rows), counts, data
