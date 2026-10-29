# -*- coding: utf-8 -*-
"""Databricks 표(Delta) 저장·읽기. 반드시 hive_metastore.maps_ai_demo 안에서만 움직인다.

쉬운 설명
- 팀 표(maps_databricks 등)는 절대 건드리지 않도록, 표 이름이 'hive_metastore.maps_ai_demo.' 로 시작하지 않으면 코드가 멈춘다.
- 표의 칸 이름에는 공백·괄호·쉼표 같은 글자를 쓸 수 없어서(Delta 규칙) 자동으로 밑줄(_)로 바꾼다.
"""
import re

CATALOG = "hive_metastore"
SCHEMA = "maps_ai_demo"
PREFIX = f"{CATALOG}.{SCHEMA}."
BAD_CHARS = re.compile(r"[ ,;{}()=\n\t]")


def full(table):
    t = table if table.startswith(PREFIX) else PREFIX + table
    assert t.startswith(PREFIX) and t.count(".") == 2 and re.fullmatch(r"[A-Za-z0-9_\.]+", t), f"허용되지 않은 표 이름: {table}"
    return t


def ensure_schema(spark):
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")


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
    ensure_schema(spark)
    name = full(table)
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


def list_tables(spark):
    ensure_schema(spark)
    return [r.tableName for r in spark.sql(f"SHOW TABLES IN {CATALOG}.{SCHEMA}").collect()]
