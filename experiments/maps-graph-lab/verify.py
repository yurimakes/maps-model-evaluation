"""Independent metric arithmetic, fold graph isolation, referential integrity, and source checks."""
import hashlib,json,sqlite3,time,zipfile
from pathlib import Path
from benchmark import GraphFeatures,METHODS,np,tune_threshold
from build_graph import dump
HERE=Path(__file__).resolve().parent;OUT=HERE/'results'

def run(require_sources=False):
    tick=time.perf_counter();data=json.loads((HERE/'data/snapshot.json').read_text(encoding='utf8'));catalog=json.loads((HERE/'data/catalog.json').read_text(encoding='utf8'));result=json.loads((OUT/'results.json').read_text(encoding='utf8'))
    f=GraphFeatures(data,catalog);leak=[]
    for system in sorted({q['system'] for q in f.q}):
        train=[i for i,q in enumerate(f.q) if q['system']!=system]
        for method in ('graph_catalog','graph_history'):
            before=f.scores(method,train).copy();th=tune_threshold(f,method,train)
            saved=[(i,f.gold[i],f.q[i]['gold']) for i,q in enumerate(f.q) if q['system']==system]
            for i,gold,qgold in saved:
                f.gold[i]=set(f.tids) if not gold else set();f.q[i]['gold']=sorted(f.gold[i])
            f.cache.clear()
            after=f.scores(method,train);th2=tune_threshold(f,method,train)
            assert np.array_equal(before,after),(system,method,'score leakage')
            assert th==th2,(system,method,'threshold leakage')
            for i,gold,qgold in saved:f.gold[i]=gold;f.q[i]['gold']=qgold
            f.cache.clear();leak.append({'system':system,'method':method,'heldout_labels_changed':'all target IDs or empty','scores_identical':True,'threshold_identical':True})
    metric=[]
    for m in METHODS:
        rows=[r for r in result['predictions'] if r['method']==m];tp=fp=fn=hit1=hit5=npos=0
        assert len(rows)==len({r['query_id'] for r in rows})==114
        for r in rows:
            gold=set(r['gold']);pred=set(r['predicted']);tp+=len(gold&pred);fp+=len(pred-gold);fn+=len(gold-pred)
            if gold:npos+=1;hit1+=bool(gold&set(r['ranked'][:1]));hit5+=bool(gold&set(r['ranked'][:5]))
        row=next(r for r in result['summary'] if r['method']==m)
        assert (tp,fp,fn)==(row['tp'],row['fp'],row['fn'])
        assert abs(2*tp/(2*tp+fp+fn)-row['mapping_f1'])<1e-12
        assert abs(hit1/npos-row['top1_accuracy'])<1e-12
        assert abs(hit5/npos-row['top5_accuracy'])<1e-12
        metric.append({'method':m,'independent_metrics_match':True})
    db=sqlite3.connect(OUT/'knowledge.sqlite')
    dangling=db.execute('SELECT COUNT(*) FROM edges e LEFT JOIN nodes s ON s.id=e.source LEFT JOIN nodes t ON t.id=e.target WHERE s.id IS NULL OR t.id IS NULL').fetchone()[0]
    assert dangling==0
    assert db.execute("SELECT COUNT(*) FROM edges WHERE relation='APPROVED_MAP'").fetchone()[0]==68
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    # This checks every physical input, including files that were only inventoried.
    inv=json.loads((OUT/'inventory.json').read_text(encoding='utf8'));physical=[r for r in inv if '!' not in r['path']]
    present=[];missing=[]
    for r in physical:
        if Path(r['path']).exists():
            assert hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256'];present.append(r['path'])
        else:missing.append(r['path'])
    if require_sources:assert not missing,'Original source files are required but unavailable.'
    assert not [r for r in inv if r['status'] in ('parse_error','pdf_parser_unavailable','archive_depth_limit','archive_size_limit')]
    neighbors=db.execute("SELECT COUNT(*) FROM edges WHERE source='target:CUSTOMER.CUST_NM'").fetchone()[0];assert neighbors>=1
    fts=db.execute("SELECT COUNT(*) FROM document_search WHERE document_search MATCH ?",('"매핑"',)).fetchone()[0];assert fts>0
    db.close()
    checks={'passed':True,'leakage_checks':leak,'metric_checks':metric,'sqlite_integrity':'ok','dangling_edges':dangling,'physical_source_hashes_verified_unchanged':len(present),'source_files_unavailable_for_recheck':missing,'file_parse_errors':0,'document_search_hits_for_mapping':fts,'elapsed_seconds':time.perf_counter()-tick}
    dump(OUT/'verification.json',checks)
    print(json.dumps(checks,ensure_ascii=False,indent=2))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--require-source-files',action='store_true');a=p.parse_args();run(a.require_source_files)
