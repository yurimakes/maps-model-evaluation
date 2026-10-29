import hashlib
import json

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()

def query_key(row):
    # Preserve case and table qualification; do not collapse equal column names.
    return '|'.join(row[field] for field in ('system', 'table', 'column'))

def cohort(snapshot, scope):
    targets = {t['id'] for t in snapshot['targets'] if scope == 'all' or t['table'] in ('COUNSEL', 'COMPLAINT')}
    questions = {}
    allowed = {}
    for q in snapshot['queries']:
        if scope == 'homepage' and q['system'] != 'HOMEPAGE':
            continue
        gold = set(q['gold']) & targets
        if q['gold'] and not gold:
            continue
        key = query_key(q)
        if key in questions:
            raise ValueError('Duplicate source/table/column identity')
        questions[key] = sorted(gold)
        allowed[key] = sorted(targets if scope == 'all' else {
            t for t in targets if t.split('.')[0] == ('COMPLAINT' if q['system'] == 'HOMEPAGE' else 'COUNSEL')})
        if not gold <= set(allowed[key]):
            raise ValueError('Gold outside per-query candidate scope')
    if not questions:
        raise ValueError('Empty cohort')
    return questions, allowed

def validate(rows, expected, allowed, fold_mode='source'):
    seen = set()
    for row in rows:
        key = row['query_key']
        if key in seen or key not in expected:
            raise ValueError('Duplicate or unknown query: ' + key)
        seen.add(key)
        for field in ('gold', 'predicted', 'ranked'):
            value = row[field]
            if not isinstance(value, list) or any(not isinstance(x, str) for x in value) or len(set(value)) != len(value):
                raise ValueError('Target IDs must be unique string lists')
            if not set(value) <= set(allowed[key]):
                raise ValueError('Target outside candidate scope: ' + key)
        if sorted(row['gold']) != expected[key]:
            raise ValueError('Gold differs from frozen snapshot: ' + key)
        if row['fold'] != (row['system'] if fold_mode == 'source' else 'historical'):
            raise ValueError('Unexpected held-out source identity: ' + key)
    if seen != set(expected):
        raise ValueError('Missing queries: ' + str(len(set(expected) - seen)))

def input_fingerprint(snapshot):
    # Ignore local source paths and run logs; include actual schema/dictionary inputs.
    return digest({'queries': sorted([{k:q.get(k) for k in ('system','table','column','description','dtype','gold')} for q in snapshot['queries']], key=query_key),
        'targets': sorted(snapshot['targets'],key=lambda t:t['id']), 'aliases':snapshot.get('aliases',{})})

def comparison_key(expected, allowed, protocol, inputs=None):
    return digest({'gold_by_query': expected, 'candidates_by_query': allowed, 'protocol': protocol,'input_fingerprint':inputs})
