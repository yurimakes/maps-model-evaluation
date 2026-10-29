"""Create a portable, content-hashed snapshot without dependencies or customer raw files."""
import hashlib,json,shutil,sys,zipfile
from datetime import datetime,timezone,timedelta
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
STAGE=ROOT/'output/github-snapshot'

def stage():
    STAGE.mkdir(parents=True,exist_ok=True)
    selected=[]
    def copy(p,rel):
        target=STAGE/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
        selected.append({'source':str(p.relative_to(ROOT)),'path':rel.as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    for lab in ('maps-local-lab','maps-graph-lab'):
        base=ROOT/'output'/lab
        for p in sorted(base.rglob('*')):
            if not p.is_file() or any(s in p.relative_to(base).parts for s in ('.packages','__pycache__','.git')):continue
            copy(p,Path('experiments')/lab/p.relative_to(base))
    for p in sorted((ROOT/'tmp').glob('*')):
        if p.suffix in ('.py','.cjs','.mjs'):copy(p,Path('research_support')/p.name)
    readme='''# MAPS 온톨로지·그래프 실험 스냅샷

2026-10-29 실행 코드·테스트·입력 메타데이터·그래프·실측 결과를 보존한 비공개 연구 저장소입니다.

## 결과

5개 원천 시스템, 평가 컬럼 114개, Target 78개. 원천 시스템을 통째로 보류하는 중첩 검증으로 비교했습니다.

| 방법 | Top-1 | Top-5 | 매핑 F1 |
|---|---:|---:|---:|
| 메타데이터 TF-IDF | 41.5% | 75.4% | 36.6% |
| 사전·BM25·자료형 | 60.0% | 86.2% | 43.8% |
| 기존 승인 이력 결합 | 64.6% | 89.2% | **54.0%** |
| 용어·단어·도메인 그래프 | 66.2% | 83.1% | 42.9% |
| 그래프 + 다른 원천 승인 이력 | **69.2%** | **92.3%** | 51.8% |

그래프는 후보 순위를 개선했으나 자동 추천·보류를 합친 매핑 F1은 기존 이력보다 2.2%p 낮았습니다. 외부 독립 데이터에서의 개선은 검증하지 않았습니다.

## 파일

- [전체 실험 설명·재현 방법](experiments/maps-graph-lab/README.md)
- [결과 보고서 HTML](experiments/maps-graph-lab/results/report.html): 내려받아 브라우저에서 열기
- [성능표](experiments/maps-graph-lab/results/metrics.csv), [원천별 성능](experiments/maps-graph-lab/results/metrics_by_system.csv), [오답](experiments/maps-graph-lab/results/errors.csv)
- [그래프 SQLite](experiments/maps-graph-lab/results/knowledge.sqlite), [그래프 JSON](experiments/maps-graph-lab/results/graph.json)
- [검증 기록](experiments/maps-graph-lab/results/verification.json), [실제 추천 지연시간](experiments/maps-graph-lab/results/query_latency.json)
- [파일 해시·스냅샷 목록](SNAPSHOT_MANIFEST.json)

`experiments/maps-local-lab`는 이전 기준 실험 전체와 테스트, `experiments/maps-graph-lab`는 이번 구축·그래프 실험 전체입니다. `research_support`는 기존 보고서 생성·검사 코드의 보존본입니다. 실행 의존성 폴더·캐시·원본 고객 데이터·영상은 업로드하지 않았습니다. 그래프·평가에 필요한 파생 메타데이터와 파일 해시는 포함했습니다.

## 빠른 재현

```powershell
python -m pip install -r experiments/maps-graph-lab/requirements.txt
python experiments/maps-graph-lab/benchmark.py
python experiments/maps-graph-lab/verify.py
python experiments/maps-graph-lab/query.py recommend --column customer_name --description "고객 이름" --dtype "VARCHAR(100)"
```

당시 원본은 읽기만 했으며 51개 원본 파일의 해시 보존을 확인했습니다. 원본이 없는 컴퓨터에서는 벤치마크를 파생 스냅샷으로 재현하고 원본 해시 재검사 누락을 별도 기록합니다. 전체 그래프의 승인 매핑은 조회용이며, 평가는 학습 원천만으로 별도 그래프를 만듭니다. 보류 원천의 정답을 변경하는 10개 유출 방지 검사를 통과했습니다.

표준용어·도메인은 규칙의 원문을 보존하지만 모든 업무 규칙을 실행하는 엔진은 아닙니다. Fabric 배포와 실제 LLM RAG·비용 절감 검증은 이 스냅샷에 포함하지 않습니다.
'''
    (STAGE/'README.md').write_text(readme,encoding='utf8')
    (STAGE/'.gitignore').write_text('__pycache__/\n*.pyc\n.packages/\n.venv/\n.env\n.env.*\nnode_modules/\n',encoding='utf8')
    for name in ('README.md','.gitignore'):
        p=STAGE/name;selected.append({'source':'generated','path':name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    manifest={'timestamp':datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds'),'repository':'https://github.com/yurimakes/maps-ontology-graph','visibility_required':'private','source_code_policy':'All workspace-authored experiment and research helper code included; third-party runtime dependency directories and caches excluded.','files':selected}
    (STAGE/'SNAPSHOT_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    # Local fallback archive independently preserves the identical selected files.
    archive=ROOT/'output/MAPS_ontology_graph_snapshot_20261029.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for r in selected:z.write(STAGE/r['path'],r['path'])
        z.write(STAGE/'SNAPSHOT_MANIFEST.json','SNAPSHOT_MANIFEST.json')
    print(json.dumps({'stage':str(STAGE),'files':len(selected)+1,'archive':str(archive),'archive_bytes':archive.stat().st_size},ensure_ascii=False))

if __name__=='__main__':stage()
