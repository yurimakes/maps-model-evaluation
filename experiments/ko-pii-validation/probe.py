"""Synthetic exploratory probe; this is not a MAPS production benchmark."""
from pathlib import Path
import csv, hashlib, json, platform, re, statistics, sys, time

ROOT = Path(__file__).resolve().parents[1]
import ko_pii
from ko_pii import Anonymizer, ProcessingMode, anonymize_json
from ko_pii.tabular import map_columns

def run(out, fixture_path):
    fixture_bytes = fixture_path.read_bytes()
    fixtures = [json.loads(line) for line in fixture_bytes.decode('utf-8').splitlines() if line.strip()]
    labels = sorted({s['label'] for c in fixtures for s in c['spans']})
    all_runs = {}
    for mode in [ProcessingMode.STRICT, ProcessingMode.PARANOID]:
        anon = Anonymizer(mode=mode, strategy='redact', include=labels)
        rows = []; counts = {l:{'tp':0,'fp':0,'fn':0,'gold':0,'literal_remaining':0,'uncovered_gold_spans':0} for l in labels}
        for c in fixtures:
            result = anon.process(c['text'])
            gold = {(s['label'],s['start'],s['end']) for s in c['spans']}
            pred = {(r.detection.label,r.detection.start,r.detection.end) for r in result.detections}
            blocked = [(r.detection.start,r.detection.end) for r in result.blocked_items()]
            for label in labels:
                counts[label]['tp'] += len({s for s in gold & pred if s[0]==label})
                counts[label]['fp'] += len({s for s in pred-gold if s[0]==label})
                counts[label]['fn'] += len({s for s in gold-pred if s[0]==label})
            remnants=[]; uncovered=[]
            for label,start,end in gold:
                counts[label]['gold'] += 1
                if c['text'][start:end] in result.text:
                    counts[label]['literal_remaining']+=1; remnants.append(label)
                if not all(any(a<=j<b for a,b in blocked) for j in range(start,end)):
                    counts[label]['uncovered_gold_spans']+=1; uncovered.append(label)
            rows.append({'id':c['id'],'group':c['group'],'input':c['text'],'output':result.text,
                         'gold':c['spans'],'predictions':[{'label':r.detection.label,'start':r.detection.start,'end':r.detection.end,'action':r.action.value} for r in result.detections],
                         'literal_remaining_labels':remnants,'uncovered_labels':uncovered})
        for d in counts.values():
            d['precision'] = d['tp']/(d['tp']+d['fp']) if d['tp']+d['fp'] else None
            d['recall'] = d['tp']/(d['tp']+d['fn']) if d['tp']+d['fn'] else None
        all_runs[mode.value] = {'by_label':counts,'cases':rows,'negative_cases':sum(not c['spans'] for c in fixtures),
          'changed_negative_cases':sum(not c['spans'] and c['text']!=r['output'] for c,r in zip(fixtures,rows))}
    # Boundary demonstrations are separate from the detector score.
    raw={'customer_name':'이상','phone_number':1023456789,'address':'가상마을 3층 302호','policy_id':'P-2026-001','diagnosis':'가상질환 진단','note':'콜백 요청','demo@example.com':'key-is-preserved'}
    auto=anonymize_json(raw, anonymizer=Anonymizer(strategy='redact')).data
    forced=anonymize_json(raw,anonymizer=Anonymizer(strategy='redact'),field_labels={'/customer_name':'PERSON','/phone_number':'PHONE','/address':'ADDRESS'}).data
    token=Anonymizer(strategy='tokenize',include=['EMAIL']).process('demo@example.com / demo@example.com')
    boundaries={'raw_synthetic':raw,'json_auto':auto,'json_explicit_labels':forced,
      'map_columns':map_columns(['customer_name','phone_number','birth_date','policy_id','성명','전화번호']),
      'tokenized':token.text,'vault_can_reveal':token.vault.reveal('<EMAIL_1>')=='demo@example.com',
      'input_not_mutated':raw['customer_name']=='이상' and raw['phone_number']==1023456789}
    texts=[c['text'] for c in fixtures]; anon=Anonymizer(strategy='redact',include=labels)
    samples=[]
    for t in texts: anon.process(t)
    for repeat in range(5):
        for t in texts:
            ts=time.perf_counter();anon.process(t);samples.append((time.perf_counter()-ts)*1000)
    elapsed=sum(samples)/1000
    perf={'warm_calls':len(samples),'unique_texts':len(texts),'unique_chars':sum(map(len,texts)),
          'p50_ms':statistics.median(samples),'p95_ms':sorted(samples)[int(.95*(len(samples)-1))],
          'measured_processing_seconds':elapsed,'calls_per_second':len(samples)/elapsed,
          'note':'Serial warm in-memory calls; initialization, I/O, Spark scheduling, LLM and network excluded; synthetic inputs only.'}
    manifest={'package':'ko-pii','version':ko_pii.__version__,'python':sys.version,'platform':platform.platform(),
      'cpu':platform.processor(),'fixture_sha256':hashlib.sha256(fixture_bytes).hexdigest(),
      'wheel_sha256':'74855b2f082676570c67e0f43683bf4230c26db7a5aa228a615fce882eeff753',
      'upstream_commit':'8957e8bc9f0ade3d21381734523b18920330c159',
      'synthetic_only':True,'cases':len(fixtures),'gold_spans':sum(len(c['spans']) for c in fixtures),
      'supported_labels_evaluated':labels,'limitations':'Exploratory hand-authored cases, no independent holdout, no production accuracy or SLA claim.'}
    for filename,data in [('probe_results.json',all_runs),('boundary_results.json',boundaries),('latency.json',perf),('run_manifest.json',manifest)]:
        (out/filename).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (out/'label_metrics.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['mode','label',*next(iter(all_runs['STRICT']['by_label'].values()))]
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for mode,r in all_runs.items():
            for label,d in r['by_label'].items(): writer.writerow({'mode':mode,'label':label,**d})
    return {'manifest':manifest,'runs':all_runs,'boundaries':boundaries}
