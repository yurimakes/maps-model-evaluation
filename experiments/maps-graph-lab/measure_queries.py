"""Real prototype recommendation latency, including feature preparation per request."""
import json,os,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent

def main():
    env={**os.environ,'PYTHONIOENCODING':'utf-8'}
    tick=time.perf_counter()
    p=subprocess.run([sys.executable,str(HERE/'query.py'),'recommend','--column','customer_name','--description','고객 이름','--dtype','VARCHAR(100)'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,check=True)
    cold=time.perf_counter()-tick;example=json.loads(p.stdout.decode('utf8'))
    assert example['ranked'][0]=='CUSTOMER.CUST_NM'
    from query import recommend
    samples=[]
    for i in range(10):
        r=recommend('NEW','external','customer_name','고객 이름','VARCHAR(100)');samples.append(r['elapsed_seconds'])
    import numpy as np
    result={'cold_cli_process_seconds':cold,'in_process_fresh_feature_requests':len(samples),'in_process_full_request_p50_seconds':float(np.median(samples)),'in_process_full_request_p95_seconds':float(np.quantile(samples,.95)),'samples_seconds':samples,'scope':'Prototype rebuilds all text features and the scoring graph per new request. First in-process sample includes importing the model libraries; later imports are cached. Cold CLI includes process startup and imports. Ten repetitions of one metadata query; latency only, not accuracy.','example':example}
    (HERE/'results/query_latency.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
