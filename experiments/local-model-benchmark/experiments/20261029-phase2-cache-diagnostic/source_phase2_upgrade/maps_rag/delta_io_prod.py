# -*- coding: utf-8 -*-
"""실제 운영(실행) 노트북 전용 Delta 저장·읽기. 반드시 maps_databricks.maps_ai_poc 안에서만 움직인다.

쉬운 설명
- `maps_databricks`는 여러 팀이 같이 쓰는 카탈로그다. 그 안에서 이 프로젝트에 내준 스키마는 `maps_ai_poc` 하나뿐이라,
  표 이름이 'maps_databricks.maps_ai_poc.' 로 시작하지 않으면(=다른 팀 스키마를 건드리려 하면) 코드가 멈춘다.
- 스키마 자체는 팀이 이미 만들어 둔 것이라 여기서 새로 만들지 않는다(만들 권한이 없을 수 있고, 만들 필요도 없다).
- 00~07 실험 노트북이 쓰는 `delta_io.py`(hive_metastore.maps_ai_demo)와는 완전히 분리된 별도 모듈이다 —
  실험 노트북을 실수로 이 스키마에 쓰게 만들 위험이 없다.
"""
import re

CATALOG = "maps_databricks"
SCHEMA = "maps_ai_poc"
PREFIX = f"{CATALOG}.{SCHEMA}."
BAD_CHARS = re.compile(r"[ ,;{}()=\n\t]")


def full(table):
    t = table if table.startswith(PREFIX) else PREFIX + table
    assert t.startswith(PREFIX) and t.count(".") == 2 and re.fullmatch(r"[A-Za-z0-9_\.]+", t), \
        f"허용되지 않은 표 이름(이 프로젝트 스키마 밖입니다): {table}"
    return t


def sanitize_columns(pdf):
    pdf = pdf.copy()
    pdf.columns = [BAD_CHARS.sub("_", str(c)) for c in pdf.columns]
    return pdf


def _clean(pdf):
    """판다스 표 → (칸 이름 목록, 칸별 값 목록). NaN→None, 리스트는 숫자 목록 또는 글자로, 글 칸은 전부 str 로."""
    import numpy as np
    pdf = sanitize_columns(pdf)
    names, cols, kinds = [], [], []
    for c in pdf.columns:
        s = pdf[c]
        vals = s.tolist()
        dt = str(s.dtype)
        if dt.startswith(("float", "Float")):
            cols.append([None if (v is None or v != v) else float(v) for v in vals]); kinds.append("double")
        elif dt.startswith(("int", "Int", "uint")):
            cols.append([None if (v is None or (isinstance(v, float) and v != v)) else int(v) for v in vals]); kinds.append("long")
        elif dt == "bool":
            cols.append([bool(v) for v in vals]); kinds.append("bool")
        else:
            first = next((v for v in vals if v is not None and not (isinstance(v, float) and v != v)), None)
            def _is_num_list(v):
                return isinstance(v, (list, tuple, np.ndarray)) and len(v) > 0 and isinstance(v[0], (int, float, np.integer, np.floating)) and not isinstance(v[0], bool)
            if isinstance(first, (list, tuple, np.ndarray)) and any(_is_num_list(v) for v in vals if v is not None):
                cols.append([None if v is None else [float(x) for x in v] for v in vals]); kinds.append("array")   # 숫자 목록(임베딩)
            elif isinstance(first, (bool, np.bool_)):
                cols.append([None if (v is None or (isinstance(v, float) and v != v)) else bool(v) for v in vals]); kinds.append("bool")
            else:
                def conv(v):
                    if v is None or (isinstance(v, float) and v != v):
                        return None
                    if isinstance(v, (list, tuple, set)):
                        return "; ".join(str(x) for x in v)
                    return v if isinstance(v, str) else str(v)
                cols.append([conv(v) for v in vals]); kinds.append("string")
        names.append(c)
    return names, cols, kinds


def _spark_schema(names, kinds):
    try:
        from pyspark.sql.types import StructType, StructField, StringType, DoubleType, LongType, BooleanType, ArrayType
    except Exception:
        return None
    m = {"string": StringType(), "double": DoubleType(), "long": LongType(), "bool": BooleanType(), "array": ArrayType(DoubleType())}
    return StructType([StructField(n, m[k], True) for n, k in zip(names, kinds)])


def write_table(spark, pdf, table, mode="overwrite"):
    import pandas as pd
    name = full(table)   # 스키마는 팀이 이미 만들어 둠 — 여기서 CREATE SCHEMA 는 하지 않는다(권한이 없을 수 있음)
    names, cols, kinds = _clean(pdf)
    schema = _spark_schema(names, kinds)
    if schema is not None:      # 실제 Databricks: 칸 종류를 직접 정해 줘서 '전부 빈 칸' 때문에 타입을 못 정하는 오류를 막는다
        sdf = spark.createDataFrame(list(zip(*cols)) if cols and len(cols[0]) else [], schema)
    else:                       # 내 컴퓨터 연습용
        sdf = spark.createDataFrame(pd.DataFrame(dict(zip(names, cols))))
    w = sdf.write.format("delta").mode(mode)
    if mode == "overwrite":
        w = w.option("overwriteSchema", "true")
    w.saveAsTable(name)
    return name


def read_table(spark, table):
    return spark.table(full(table)).toPandas()


def table_exists(spark, table):
    return spark.catalog.tableExists(full(table))


def drop_table(spark, table):
    spark.sql(f"DROP TABLE IF EXISTS {full(table)}")


def delete_all_rows(spark, table):
    """표는 그대로 두고 행만 전부 지운다. DROP+재생성과 달리 표에 걸린 권한(GRANT)이 그대로 남는다."""
    spark.sql(f"DELETE FROM {full(table)}")


def list_tables(spark):
    return [r.tableName for r in spark.sql(f"SHOW TABLES IN {CATALOG}.{SCHEMA}").collect()]
