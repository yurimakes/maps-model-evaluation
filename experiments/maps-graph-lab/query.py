"""Inspect the stored graph, search evidence, or recommend for a new column."""
import argparse,json,sqlite3,time
from pathlib import Path
HERE=Path(__file__).resolve().parent

def recommend(system,table,column,description='',dtype='',method='graph_history'):
    tick=time.perf_counter()
    from benchmark import GraphFeatures
    from run_experiments import predict
    data=json.loads((HERE/'data/snapshot.json').read_text(encoding='utf8'))
    catalog=json.loads((HERE/'data/catalog.json').read_text(encoding='utf8'))
    n=len(data['queries'])
    data['queries'].append({'id':'|'.join((system,table,column)),'system':system,'table':table,'column':column,'description':description,'dtype':dtype,'gold':[]})
    f=GraphFeatures(data,catalog);scores=f.scores(method,list(range(n)))
    threshold=json.loads((HERE/'results/deployment_thresholds.json').read_text(encoding='utf8'))[method]
    r=predict(f,scores,[n],threshold,method,'new_query')[0]
    del r['gold'];del r['correct']
    r['purpose']='PROTOTYPE_RECOMMENDATION_REQUIRES_REVIEW'
    r['elapsed_seconds']=time.perf_counter()-tick
    return r

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    n=sub.add_parser('neighbors');n.add_argument('node_id')
    s=sub.add_parser('search');s.add_argument('text')
    r=sub.add_parser('recommend');r.add_argument('--system',default='NEW');r.add_argument('--table',default='external');r.add_argument('--column',required=True);r.add_argument('--description',default='');r.add_argument('--dtype',default='');r.add_argument('--method',choices=['graph_history','hybrid_transfer'],default='graph_history')
    args=p.parse_args()
    if args.action=='recommend':result=recommend(args.system,args.table,args.column,args.description,args.dtype,args.method)
    else:
        db=sqlite3.connect(HERE/'results/knowledge.sqlite');db.row_factory=sqlite3.Row
        if args.action=='neighbors':
            result=[dict(x) for x in db.execute('SELECT e.*,n.label FROM edges e JOIN nodes n ON n.id=e.target WHERE e.source=? UNION ALL SELECT e.*,n.label FROM edges e JOIN nodes n ON n.id=e.source WHERE e.target=?',(args.node_id,args.node_id))]
        else:
            # Quote the query as a literal FTS phrase; no SQL interpolation.
            phrase='"'+args.text.replace('"','""')+'"'
            result=[dict(x) for x in db.execute('SELECT s.document_id,n.label,snippet(document_search,1,\'[\',\']\',\'…\',30) AS evidence FROM document_search s JOIN nodes n ON n.id=s.document_id WHERE document_search MATCH ? LIMIT 10',(phrase,))]
        db.close()
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
