# Databricks notebook source
# MAGIC %md
# MAGIC # 10 · 운영 실행  ★ 실제 결과를 만드는 노트북
# MAGIC
# MAGIC **00~07번과 다른 점**
# MAGIC - 00~07은 "한 단계씩 눈으로 확인·실험"하는 노트북이고, 결과도 내 개인 스키마(`hive_metastore.maps_ai_demo`)에만 저장됩니다.
# MAGIC - 이 노트북은 **위젯 없이 위에서 아래로 한 번에** 돕니다. 원천도 내 복사본이 아니라 **팀의 진짜 실버 표**(`maps_databricks.silver.*`, 읽기 전용)를 읽고,
# MAGIC   결과는 **`maps_databricks.maps_ai_poc`**(이번 프로젝트에 내준 공유 스키마)에 저장합니다. `maps_databricks` 안의 다른 스키마(다른 팀 자료)는
# MAGIC   표 이름 검사로 막아 놔서 건드릴 수 없습니다(`delta_io_prod.py`).
# MAGIC
# MAGIC **만드는 표 4개** (`src_column_profile` / `ai_recommendations` / `ai_evidence` / `ai_call_log` — 00~07과 같은 이름·구조, 저장 위치만 다름)
# MAGIC
# MAGIC **채널 범위**: `source_system` 파라미터를 주면 그 채널 하나만 처리합니다(Databricks Job이 넘겨주는 값).
# MAGIC 파라미터 없이 수동으로 돌리면(2026-09-27부터) 5개 채널 실버 표에 행이 있는지 먼저 확인(`SELECT count(1)`)해서 **데이터 있는 채널 전부**를 자동으로 처리합니다.
# MAGIC
# MAGIC **target 결정 방식(2026-09-27부터)**: `rec.recommend_v2()`를 씁니다 — "하나만 골라라"가 아니라 **목표 후보 전체에 게이트·점수를 매기게 하고, 코드가 문턱값(0.70) 이상인 최고 확신도 후보를 고릅니다.**
# MAGIC 매핑되는 컬럼은 그 후보 하나만 다시 평가해서 mapping_type/process_type/rule까지 채우는 2단계 호출(컬럼당 최대 Azure 2번)이라, 04_AI추천(`rec.recommend()`, 1번 호출)보다 컬럼당 시간·토큰이 더 씁니다.
# MAGIC 08_후보비교_흐름 에서 단계별로 검증한 로직이고, 실제 함수는 `maps_rag/recommend.py`에 있습니다(08번과 10번이 같은 코드를 공유).
# MAGIC
# MAGIC **Job 파라미터(2026-09-27 추가)**: `maps-review-ui`(민찬기님) 쪽에서 Databricks Job으로 이 노트북을 실행할 때 `source_system`/`source_table`/`source_batch_id`/`dq_run_id` 4개를 넘겨줍니다.
# MAGIC 이 값들이 있으면 **그 배치에 해당하는 행만** 골라서 처리하고 결과에도 그대로 저장합니다(팀의 다른 파이프라인 단계와 같은 관례). 그래서 이제 **표를 통째로 비우고 다시 채우는 방식이 아니라, 이번 배치 분만 추가/갱신**하는 방식으로 바뀌었습니다(예전 배치 결과가 안 지워짐).
# COMMAND ----------
# ▶ 부품 준비 — 올려 둔 '코드·자료 묶음'을 풀어서 불러옵니다 (모든 노트북의 첫 코드 셀, 00~07과 동일)
import os, sys, io, hashlib, zipfile, shutil

WS = "/Workspace/Users/5dt003@msacademy.msai.kr/maps_ai_demo"      # 코드·지식조각·임베딩 묶음은 여기서 받아 옴(자료 자체는 개인 폴더, 결과 저장 위치와는 무관)
LOCAL = os.environ.get("MAPS_LOCAL_ROOT")                          # 내 컴퓨터 연습용(Databricks 에서는 비어 있음)

def ws_read(rel):
    p = f"{WS}/{rel}"
    try:
        with open(p, "rb") as f:
            return f.read()
    except Exception:
        from databricks.sdk import WorkspaceClient
        return WorkspaceClient().workspace.download(p).read()

if LOCAL:
    ROOT = LOCAL
else:
    _data = ws_read("bundle/maps_ai_demo_bundle.dat")
    _tag = hashlib.md5(_data).hexdigest()[:8]                       # 묶음이 바뀌면 자동으로 새 폴더에 새로 풉니다
    _base = "/local_disk0" if (os.path.isdir("/local_disk0") and os.access("/local_disk0", os.W_OK)) else "/tmp"
    ROOT = f"{_base}/maps_ai_demo_{_tag}"
    if not os.path.isdir(ROOT + "/코드"):
        shutil.rmtree(ROOT, ignore_errors=True)
        zipfile.ZipFile(io.BytesIO(_data)).extractall(ROOT)
os.environ["MAPS_ROOT"] = ROOT
for _k in [k for k in sys.modules if k == "maps_rag" or k.startswith("maps_rag.")]:
    del sys.modules[_k]                                              # 옛 코드가 남아 있지 않게
sys.path = [p for p in sys.path if "maps_ai_demo_" not in p]
sys.path.insert(0, ROOT + "/코드")
from maps_rag import paths, delta_io_prod as dio, notebook_common as nc
print("✔ 부품 준비 완료 —", ROOT)
print(f"  결과 표는 {dio.CATALOG}.{dio.SCHEMA} 에만 저장됩니다. 그 밖의 팀 스키마는 코드가 막습니다.")
# COMMAND ----------
# MAGIC %md
# MAGIC ### 단계 1 · 실행 파라미터
# MAGIC **Job 파라미터(위젯, `maps-review-ui`가 넘겨줌)** — 수동 실행할 땐 빈 칸으로 두면 예전처럼 동작합니다.
# MAGIC - `source_system`: 처리할 채널(`HOMEPAGE`/`SALESFORCE`/...). 비우면 실버에 데이터 있는 채널 전부를 자동 감지.
# MAGIC - `source_table`: 그 채널 안 특정 원천표만(예: 챗봇의 `session_navigation`만). 비우면 그 채널 전부.
# MAGIC - `source_batch_id`/`dq_run_id`: 이번 실버 적재 배치 번호. 주면 그 배치 행만 걸러서 처리하고 결과에도 그대로 저장(추적용).
# MAGIC
# MAGIC **아래는 위젯이 아니라 코드 값을 직접 고쳐서 쓰는 개발용 설정입니다.**
# MAGIC - `MODE`: 참고 자료 찾는 방식(`hybrid` 추천 / `bm25` / `embedding`)
# MAGIC - `LIMIT_ROWS`: `None`이면 전부 처리, 작은 수(예: `5`)로 두면 그만큼만 먼저 돌려서 **공유 스키마에 실제로 잘 쓰이는지 싼 값으로 먼저 확인**할 수 있습니다.
# MAGIC - `TPM`/`RPM`: Azure 리소스의 분당 토큰·요청 한도(04번과 같은 기본값).
# COMMAND ----------
dbutils.widgets.text("source_system", "")
dbutils.widgets.text("source_table", "")
dbutils.widgets.text("source_batch_id", "")
dbutils.widgets.text("dq_run_id", "")
SOURCE_SYSTEM = dbutils.widgets.get("source_system").strip()
SOURCE_TABLE = dbutils.widgets.get("source_table").strip()
SOURCE_BATCH_ID = dbutils.widgets.get("source_batch_id").strip()
DQ_RUN_ID = dbutils.widgets.get("dq_run_id").strip()
print(f"Job 파라미터: source_system={SOURCE_SYSTEM or '(비움→자동감지)'}  source_table={SOURCE_TABLE or '(비움→전체)'}  "
      f"source_batch_id={SOURCE_BATCH_ID or '(비움→필터 안 함)'}  dq_run_id={DQ_RUN_ID or '(비움→필터 안 함)'}")

MODE = "hybrid"
LIMIT_ROWS = None     # 처음 돌릴 때는 5 같은 작은 수로 먼저 확인해 보는 걸 추천합니다.
TPM = 70000   # Azure 배포 capacity 70에 맞춘 값(2026-09-27 상향)
RPM = 70
print(f"설정: MODE={MODE}  LIMIT_ROWS={LIMIT_ROWS}  TPM={TPM}  RPM={RPM}")
# COMMAND ----------
# MAGIC %md
# MAGIC ### 단계 1-1 · (거의 안 씀) `maps_databricks.maps_ai_poc` 표 통째로 비우기
# MAGIC **이제 정상적인 배치 실행에서는 이 표를 비우면 안 됩니다** — 표 하나에 여러 배치 결과가 같이 쌓이는 구조로 바뀌어서,
# MAGIC 비우면 이번 배치가 아닌 **다른 배치의 기존 결과까지 전부 사라집니다.** 개발 중 완전히 처음부터 다시 만들고 싶을 때만 `True`로 바꿔서 한 번 쓰고 다시 `False`로 되돌리세요.
# COMMAND ----------
RESET_TABLES = False   # 2026-09-27: 배치별로 표에 쌓이는 방식으로 바뀌어서 기본 False. 정말 전부 지우고 싶을 때만 True.

if RESET_TABLES:
    for _t in ["src_column_profile", "ai_recommendations", "ai_evidence", "ai_call_log"]:
        dio.drop_table(spark, _t)
        print(f"✔ 비움: {dio.CATALOG}.{dio.SCHEMA}.{_t}")
else:
    print("RESET_TABLES=False — 표를 비우지 않고 이어서 채웁니다.")
# COMMAND ----------
# MAGIC %md
# MAGIC ### 단계 2 · 원천 읽기(팀 진짜 실버 표, 읽기 전용) → 컬럼 프로파일 만들기
# MAGIC `source_loader.make_source(mode="DATABRICKS")`는 `maps_databricks.silver.*`를 **SELECT만** 합니다(절대 쓰지 않음).
# MAGIC `source_system` 파라미터가 있으면 그 채널만, 없으면 채널마다 행 수를 세어 봐서 데이터 있는 채널 전부를 처리합니다.
# MAGIC `src_column_profile`은 이제 통째로 덮어쓰지 않고, **이번에 다시 읽은 칸만 갈아 끼우고 나머지 채널의 예전 프로파일은 그대로 둡니다**
# MAGIC (배치 실행 하나가 한 채널만 다루기 때문에, 예전처럼 덮어쓰면 다른 채널 프로파일이 사라집니다).
# COMMAND ----------
import pandas as pd
from maps_rag import source_loader as sl

if SOURCE_SYSTEM:
    active = [SOURCE_SYSTEM]
    print(f"source_system 파라미터로 지정됨 → {active} 만 처리")
else:
    row_counts = sl.channel_row_counts(spark)
    active = sl.active_channels_databricks(spark)
    print("채널별 실버 행 수:", row_counts)
    print(f"이번에 처리할 채널: {active} (나머지는 실버가 비어 있어 건너뜀)")

source = sl.make_source(mode="DATABRICKS", spark=spark, batch_id=SOURCE_BATCH_ID or None, dq_run_id=DQ_RUN_ID or None)
inputs = sl.load_input_columns(paths.INPUT_COLUMNS)
if SOURCE_TABLE:
    inputs = inputs[inputs["source_table"] == SOURCE_TABLE]
    print(f"source_table 파라미터로 지정됨 → {SOURCE_TABLE} 만 처리")
prof, counts, _ = sl.build_profiles(source, inputs, channels=active)
prof["source_batch_id"] = SOURCE_BATCH_ID
prof["dq_run_id"] = DQ_RUN_ID
print(f"읽은 채널: {counts}")
print(f"이번에 물어볼 컬럼 {len(prof)}칸 (채널: {sorted(prof.channel.unique().tolist())})")
missing = prof[prof["sample_count"] == 0]
if len(missing):
    print(f"⚠ 실버 표에서 못 찾은 컬럼 {len(missing)}개(팀 표 구조가 달라졌을 수 있음, 또는 이 배치엔 해당 없음):", missing["source_column"].tolist())

prev_prof = nc.load_prev(spark, dio, "src_column_profile", ["query_id"])
if prev_prof is not None:
    keep = ~prev_prof["query_id"].isin(set(prof["query_id"]))
    prof_to_write = pd.concat([prev_prof[keep], prof], ignore_index=True)
else:
    prof_to_write = prof
name = dio.write_table(spark, prof_to_write, "src_column_profile")
print(f"✔ 저장: {name} (이번 채널 {len(prof)}칸 + 기존 다른 채널/배치 {len(prof_to_write) - len(prof)}칸)")
# COMMAND ----------
# MAGIC %md
# MAGIC ### 단계 3 · 지식창고·추천기 준비 (여기까지는 Azure 를 부르지 않음)
# COMMAND ----------
from maps_rag import knowledge as kn
from maps_rag.embeddings import VectorStore
from maps_rag.facts import TargetCatalog, Lookups
from maps_rag.retrieval import Retriever
from maps_rag.recommend import Recommender
from maps_rag.azure_client import AzureClient

chunks = kn.load_chunks(paths.KB_DIR)
visible, retr = kn.searchable(chunks), kn.retrievable(chunks)
store = VectorStore.load(paths.EMB_DIR / "embeddings.npz")
catalog, lookups = TargetCatalog(paths.TARGET_MODEL), Lookups(visible)
retriever = Retriever(retr, store.chunk_vectors(retr))
print(f"질문 {len(prof)}칸 | 지식 카드(검색 대상) {len(retr)}개 | 임베딩 사용 가능: {retriever.has_embeddings()} | 목표 후보 {len(catalog.all_ids)}칸")

client = AzureClient(nc.endpoint(), nc.get_key(dbutils), chat_tpm=TPM, chat_rpm=RPM)
rec = Recommender(catalog, lookups, retriever, client, query_vectors=store.vecs,
                  embedder=lambda texts: client.embed_batched(texts), mode=MODE, k=5)
# COMMAND ----------
# MAGIC %md
# MAGIC ### 단계 4 · 이번에 처리할 칸 고르기 (같은 배치를 이미 끝냈으면 건너뜀 — 이어 하기)
# MAGIC "이미 끝났다"의 기준이 `query_id`만이 아니라 **`query_id`+검색방식+이번 배치**로 바뀌었습니다.
# MAGIC 그래서 같은 컬럼이라도 배치가 다르면(=새로 들어온 데이터면) 다시 처리합니다. 배치 정보가 없던 예전 결과는 빈 배치("")로 취급합니다.
# MAGIC **오류로 실패한 칸(`confidence_level="ERROR"`)은 "끝났다"로 안 치고, 같은 배치로 다시 부르면 자동으로 재처리됩니다.**
# COMMAND ----------
prof_sorted = prof.sort_values("query_id").reset_index(drop=True)
old = nc.load_prev(spark, dio, "ai_recommendations", ["query_id", "retrieval_mode"])
if old is not None:
    for _c in ("source_batch_id", "dq_run_id"):
        if _c not in old.columns:
            old[_c] = ""   # 배치 추적 이전 버전 결과
    done_ids = set(old[(old["retrieval_mode"] == MODE) & (old["source_batch_id"].fillna("") == SOURCE_BATCH_ID) &
                        (old["dq_run_id"].fillna("") == DQ_RUN_ID) & (old["confidence_level"] != "ERROR")]["query_id"])
else:
    done_ids = set()
not_done = prof_sorted[~prof_sorted["query_id"].isin(done_ids)]
todo = not_done.head(LIMIT_ROWS) if LIMIT_ROWS is not None else not_done
print(f"전체 {len(prof_sorted)}칸 | 이미 끝난 칸(이번 배치 기준) {len(prof_sorted) - len(not_done)}개 | 이번에 할 칸 {len(todo)}개")
# COMMAND ----------
# MAGIC %md
# MAGIC ### 단계 5 · 추천 실행 ⏳ (칸마다 Azure 1번, 5칸마다 표에 저장 — 중간에 멈춰도 그때까지는 남음)
# COMMAND ----------
import time

results, evidences = [], []


def _save(final=False):
    if not results:
        return
    new = pd.DataFrame([nc.flatten_result(r) for r in results])
    new = new.reindex(columns=nc.RESULT_COLS)   # 저장 직전 칸 구성을 RESULT_COLS 그대로 강제(누락 방지)
    prev = nc.load_prev(spark, dio, "ai_recommendations", ["query_id", "retrieval_mode"])
    key_cols = ["query_id", "retrieval_mode", "source_batch_id", "dq_run_id"]
    if prev is not None:
        for _c in ("source_batch_id", "dq_run_id"):
            if _c not in prev.columns:
                prev[_c] = ""   # 배치 추적 이전 버전 결과
        prev_key = prev[key_cols].fillna("").astype(str).agg("||".join, axis=1)
        new_key = new[key_cols].fillna("").astype(str).agg("||".join, axis=1)
        keep = ~prev_key.isin(set(new_key))
        new = pd.concat([prev[keep].reindex(columns=nc.RESULT_COLS), new], ignore_index=True)
    dio.write_table(spark, new, "ai_recommendations")
    ev = pd.DataFrame(evidences)
    pe = nc.load_prev(spark, dio, "ai_evidence", ["query_id", "chunk_id", "kind"]) if len(ev) else None
    if pe is not None:
        pe = pe[~pe["query_id"].isin(set(ev["query_id"]))]
        ev = pd.concat([pe, ev], ignore_index=True)
    if len(ev):
        dio.write_table(spark, ev, "ai_evidence")
    if final and client.calls:
        cl = pd.DataFrame(client.calls)
        cl["run_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        pcl = nc.load_prev(spark, dio, "ai_call_log", ["kind", "sec", "run_at"])
        if pcl is not None:
            cl = pd.concat([pcl, cl], ignore_index=True)   # 실행 기록은 계속 쌓는다
        dio.write_table(spark, cl, "ai_call_log")


t_all = time.time()
try:
    for i, (_, r) in enumerate(todo.iterrows(), 1):
        row = r.to_dict()
        try:
            res, ev = rec.recommend_v2(row)
        except Exception as e:
            print(f"[{i}/{len(todo)}] ✘ {row['channel']}.{row['source_column']} 실패: {str(e)[:200]}")
            err_res = {c: None for c in nc.RESULT_COLS}
            err_res.update({
                "query_id": row.get("query_id"), "channel": row["channel"], "source_table": row["source_table"],
                "source_column": row["source_column"], "confidence_level": "ERROR", "flags": "RUN_EXCEPTION",
                "ai_reason": str(e)[:500], "needs_human_review": "Y", "retrieval_mode": MODE,
                "source_batch_id": SOURCE_BATCH_ID, "dq_run_id": DQ_RUN_ID,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            results.append(err_res)
            continue
        res["source_batch_id"] = SOURCE_BATCH_ID
        res["dq_run_id"] = DQ_RUN_ID
        for _e in ev:
            _e["source_batch_id"] = SOURCE_BATCH_ID
            _e["dq_run_id"] = DQ_RUN_ID
        results.append(res); evidences += ev
        print(f"[{i}/{len(todo)}] {row['channel']}.{row['source_column']} → {res.get('ai_target')}  "
              f"({res.get('ai_mapping_type')}/{res.get('ai_process_type')}) 확신도 {res.get('confidence_score')} {res.get('confidence_level')} "
              f"{('⚠' + res['flags']) if res.get('flags') else ''}  {res['elapsed_sec']}초")
        if i % 5 == 0:
            _save()
except BaseException as e:
    print("\n■ 중간에 멈췄습니다:", type(e).__name__, "— 지금까지 결과를 저장합니다.")
    raise
finally:
    _save(final=True)
    print(f"\n저장: {dio.CATALOG}.{dio.SCHEMA}.ai_recommendations / ai_evidence / ai_call_log  (이번 {len(results)}칸, {time.time() - t_all:.0f}초)")
# COMMAND ----------
# MAGIC %md
# MAGIC ### 단계 6 · 결과 요약
# COMMAND ----------
allr = dio.read_table(spark, "ai_recommendations")
allr = allr[allr.retrieval_mode == MODE].sort_values("query_id")
print(f"누적 결과 {len(allr)}행 (이 실행 모드={MODE} 기준)")
display(allr.groupby(["channel", "confidence_level"]).size().reset_index(name="건수"))
display(nc.with_ko_headers(allr))
