# -*- coding: utf-8 -*-
"""폴더 위치 한 곳에 모으기. 내 컴퓨터와 Databricks(압축을 푼 폴더)에서 똑같이 동작한다."""
import os
from pathlib import Path

ROOT = Path(os.environ.get("MAPS_ROOT") or Path(__file__).resolve().parents[2])   # '자료'와 '코드'가 들어 있는 폴더
DATA = ROOT / "자료"
CODE = ROOT / "코드"
KB_DIR = DATA / "4_지식조각_RAG용" / "지식조각"
TARGET_MODEL = DATA / "2_타겟_정의" / "2_타겟_물리모델_v1.0.csv"
INPUT_COLUMNS = CODE / "data" / "원천컬럼_입력목록.csv"      # 정답 열이 없는 '질문 목록' (build_inputs.py 가 만든다)
EMB_DIR = CODE / "data" / "임베딩"

# 지식 조각을 검색에 쓸 때 제외할 종류(상품 마스터는 컬럼 매핑에 쓰지 않음)
