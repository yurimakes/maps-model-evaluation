"""Label-safe evaluation utilities; no model or project runtime imports."""
import collections,math

def metrics(rows):
    tp=fp=fn=correct=positive=rank_correct=hit5=0
    for row in rows:
        gold=set(row['gold']);pred=set(row['predicted']);rank=row.get('ranked',[])
        tp+=len(gold&pred);fp+=len(pred-gold);fn+=len(gold-pred)
        correct+=gold==pred
        if gold:
            positive+=1;rank_correct+=bool(gold&set(rank[:1]));hit5+=bool(gold&set(rank[:5]))
    p=tp/(tp+fp) if tp+fp else 0.;r=tp/(tp+fn) if tp+fn else 0.
    return {'questions':len(rows),'positive_questions':positive,'accuracy':correct/max(1,len(rows)),'precision':p,'recall':r,'f1':2*p*r/(p+r) if p+r else 0.,'rank_top1':rank_correct/max(1,positive),'rank_top5':hit5/max(1,positive),'tp':tp,'fp':fp,'fn':fn,'proposals':sum(bool(x['predicted']) for x in rows)}

def predicted_rows(records,threshold,model,fold):
    rows=[]
    for record in records:
        score=record['score'];rank=record['ranked']
        pred=rank[:1] if rank and math.isfinite(score) and score>=threshold else []
        rows.append({**record,'model':model,'fold':fold,'threshold':threshold,'predicted':pred})
    return rows

def choose_threshold(training_records):
    # Fixed grid; all labels supplied here must be from other source systems.
    best=(-1.,-1.,-1.);chosen=0.
    for i in range(101):
        threshold=i/100
        m=metrics(predicted_rows(training_records,threshold,'calibration','train'))
        key=(m['f1'],m['precision'],-threshold)
        if key>best:best=key;chosen=threshold
    return chosen

def cross_source_evaluate(records,model):
    systems=sorted({r['system'] for r in records});rows=[];thresholds=[]
    for system in systems:
        train=[r for r in records if r['system']!=system];test=[r for r in records if r['system']==system]
        threshold=choose_threshold(train)
        rows.extend(predicted_rows(test,threshold,model,system))
        thresholds.append({'model':model,'heldout_system':system,'threshold':threshold,'training_questions':len(train),'test_questions':len(test)})
    return rows,thresholds

def baseline_from_log(raw,lookup,variant):
    grouped=collections.defaultdict(list)
    for r in raw:grouped[(r['채널'],r['원천컬럼'].lower())].append(r)
    rows=[]
    for key,runs in grouped.items():
        matches=lookup.get(key,[])
        if len(matches)!=1:continue
        q=matches[0]
        if variant=='first_rep':target=min(runs,key=lambda r:int(r['rep']))['target']
        else:target=collections.Counter(r['target'] for r in runs).most_common(1)[0][0]
        pred=[] if str(target).strip().upper() in ['','EXCLUDE','NONE','NULL','NO_MATCH'] else [target]
        rows.append({'id':q['id'],'system':q['system'],'column':q['column'],'gold':q['gold'],'predicted':pred,'ranked':pred,'score':None,'threshold':None})
    return rows
