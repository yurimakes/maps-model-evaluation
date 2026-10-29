"""Generate an opt-in upgrade package from preserved original phase-2 code."""
import ast,json,shutil,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent

REPLACEMENTS={
'validate_candidate_scan':'''def validate_candidate_scan(parsed, catalog, table):
    ids=[f"{table}.{r['COLUMN_NAME']}" for r in catalog.by_table[table]]
    out={t:{'gate_relation':None,'gate_datatype':None,'scores':{},'score_status':{},'na_reasons':{}} for t in ids}
    if not isinstance(parsed,dict) or not isinstance(parsed.get('candidate_scan'),list):return out,['JSON_PARSE_FAIL']
    seen=set();flags=[]
    for item in parsed['candidate_scan']:
        if not isinstance(item,dict):flags.append('NON_OBJECT_CANDIDATE');continue
        target=str(item.get('target') or '').strip()
        if target not in out:flags.append('UNKNOWN_TARGET');continue
        if target in seen:flags.append('DUPLICATE_TARGET');continue
        seen.add(target)
        out[target]={'gate_relation':str(item.get('gate_relation') or 'MISSING').upper(),'gate_datatype':str(item.get('gate_datatype') or 'MISSING').upper(),'scores':item.get('scores') or {},'score_status':item.get('score_status') or {},'na_reasons':item.get('na_reasons') or {}}
    if len(seen)!=len(ids):flags.append(f'MISSING_{len(ids)-len(seen)}_CANDIDATES')
    return out,sorted(set(flags))
''',
'score_one_candidate':'''def score_one_candidate(entry):
    evaluated=evaluate_scores(entry.get('scores'),entry.get('score_status'),entry.get('na_reasons'))
    gates_ok=entry.get('gate_relation')=='PASS' and entry.get('gate_datatype')=='PASS'
    return evaluated['confidence'],not gates_ok or bool(evaluated['invalid'])
''',
'pick_best_candidate':'''def pick_best_candidate(candidate_map):
    scored=[];incomplete=False
    for target,entry in candidate_map.items():
        e=evaluate_scores(entry.get('scores'),entry.get('score_status'),entry.get('na_reasons'))
        gr,gd=entry.get('gate_relation'),entry.get('gate_datatype')
        gate_unknown=gr not in ('PASS','FAIL') or gd not in ('PASS','FAIL')
        incomplete|=gate_unknown or bool(e['missing']) or bool(e['invalid'])
        scored.append({'target':target,'confidence_score':e['confidence'],'gate_fail':gr!='PASS' or gd!='PASS' or bool(e['invalid']),'gate_relation':gr,'gate_datatype':gd,'missing_scores':e['missing'],'invalid_scores':e['invalid']})
    eligible=[s for s in scored if not s['gate_fail'] and not s['missing_scores'] and s['confidence_score'] is not None and s['confidence_score']>=MIN_MAP_SCORE]
    if eligible and not incomplete:
        best=sorted(eligible,key=lambda x:(-x['confidence_score'],x['target']))[0]
        return {'decision':'MAPPED','target':best['target'],'confidence_score':best['confidence_score'],'confidence_level':confidence_level(best['confidence_score']),'reason':'Both mandatory gates PASS; all applicable scores supplied.'},scored
    scored_values=[s['confidence_score'] for s in scored if s['confidence_score'] is not None]
    score=max(scored_values) if scored_values else None
    if incomplete or not scored:
        return {'decision':'REVIEW','target':None,'confidence_score':score,'confidence_level':'INVALID_CANDIDATE','reason':'INSUFFICIENT_EVIDENCE_NOT_EXCLUSION'},scored
    return {'decision':'EXCLUDE','target':'EXCLUDE','confidence_score':score,'confidence_level':'REVIEW','reason':'Complete candidate scan; no eligible mapping.'},scored
'''
}

STRICT_WRAPPER='''
def validate(parsed, catalog, shown_ids):
    result=_legacy_validate(parsed,catalog,shown_ids)
    if not isinstance(parsed,dict) or normalize_target(parsed.get('target'))=='EXCLUDE':return result
    e=evaluate_scores(parsed.get('scores'),parsed.get('score_status'),parsed.get('na_reasons'))
    flags=set(filter(None,str(result.get('flags') or '').split(',')))
    if e['missing']:flags.add('MISSING_SCORE_EVIDENCE')
    if e['invalid']:flags.add('INVALID_SCORE_VALUE')
    gates=parsed.get('gates') if isinstance(parsed.get('gates'),dict) else {}
    if any(str(gates.get(k) or '').upper()!='PASS' for k in GATES):flags.add('MANDATORY_GATE_NOT_PASS')
    if not e['observed']:flags.add('NO_OBSERVED_SCORES')
    if not result.get('evidence_ok'):flags.add('NO_EVIDENCE')
    blockers={'MANDATORY_GATE_NOT_PASS','NO_OBSERVED_SCORES','INVALID_SCORE_VALUE','NO_EVIDENCE','EVIDENCE_NOT_SHOWN','BAD_MAPPING_TYPE','BAD_PROCESS_TYPE','TARGET_NOT_IN_CANDIDATES'}
    result['confidence_score']=e['confidence']
    result['confidence_level']='INVALID_CANDIDATE' if flags&blockers else confidence_level(e['confidence'])
    if e['missing'] and result['confidence_level']=='HIGH':result['confidence_level']='REVIEW'
    result['flags']=','.join(sorted(flags))
    result['confidence_formula']='Observed weighted scores / all applicable weights; missing is not N/A.'
    result['score_evidence_status']=e
    result['needs_human_review']='Y'
    return result
'''

def build():
    src=HERE/'phase2_original'/'data'/'maps_rag';dest=HERE/'phase2_upgrade'/'maps_rag'
    shutil.copytree(src,dest,dirs_exist_ok=True)
    shutil.copy2(HERE/'strict_validation.py',dest/'strict_validation.py')
    shutil.copy2(src/'retrieval.py',dest/'legacy_retrieval.py')
    shutil.copy2(HERE/'improved_retrieval.py',dest/'retrieval.py')
    original=(src/'recommend.py').read_text(encoding='utf-8-sig');tree=ast.parse(original);lines=original.splitlines(keepends=True)
    edits=[]
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and node.name in REPLACEMENTS:
            edits.append((node.lineno-1,node.end_lineno,REPLACEMENTS[node.name]))
        if isinstance(node,ast.FunctionDef) and node.name=='validate':
            code=''.join(lines[node.lineno-1:node.end_lineno]).replace('def validate(', 'def _legacy_validate(',1)
            edits.append((node.lineno-1,node.end_lineno,code+'\n'+STRICT_WRAPPER))
    for a,b,text in sorted(edits,reverse=True):lines[a:b]=[text+'\n']
    code=''.join(lines)
    code=code.replace('from .azure_client import est_tokens, parse_json','from .azure_client import est_tokens, parse_json\nfrom .strict_validation import evaluate_scores',1)
    code=code.replace('decision, scored = pick_best_candidate(cand_map)','decision, scored = pick_best_candidate(cand_map)\n        if scan_flags:\n            decision = {"decision":"REVIEW","target":None,"confidence_score":None,"confidence_level":"INVALID_CANDIDATE","reason":"INCOMPLETE_OR_INVALID_CANDIDATE_SCAN"}',1)
    code=code.replace('extra_flags = list(scan_flags)','extra_flags = list(scan_flags)\n        if decision["decision"] == "REVIEW": extra_flags.append("INSUFFICIENT_EVIDENCE_NOT_EXCLUSION")',1)
    code=code.replace('"parse_ok": True, "ai_target": "EXCLUDE", "ai_target_table": None, "ai_target_column": None,','"parse_ok": True, "ai_target": "EXCLUDE" if decision["decision"] == "EXCLUDE" else None, "ai_target_table": None, "ai_target_column": None,',1)
    code=code.replace('"ai_mapping_type": "EXCLUDE", "ai_process_type": "NONE", "ai_rule": None,','"ai_mapping_type": "EXCLUDE" if decision["decision"] == "EXCLUDE" else None, "ai_process_type": "NONE" if decision["decision"] == "EXCLUDE" else None, "ai_rule": None,',1)
    code=code.replace('"ai_exclude_reason": decision["reason"], "ai_reason": decision["reason"],','"ai_exclude_reason": decision["reason"] if decision["decision"] == "EXCLUDE" else None, "ai_reason": decision["reason"],',1)
    protocol='\\n추가 규약: score_status에 각 항목의 OBSERVED / NA / MISSING을 기록한다. NA일 때는 na_reasons에 구체적인 이유를 기록한다. 점수를 알 수 없으면 MISSING이다. 필수 게이트는 PASS가 확인되지 않으면 판단 보류다.'
    code+='\nSYSTEM_RULES += "'+protocol+'"\nCANDIDATE_SCAN_SYSTEM_RULES += "'+protocol+'"\n'
    code='# OPT-IN UPGRADE: original source is preserved in phase2_original. See build_phase2_upgrade.py.\n'+code
    ast.parse(code);(dest/'recommend.py').write_text(code,encoding='utf-8')
    manifest={'source_archive_sha256':json.loads((HERE/'phase2_original'/'archive_manifest.json').read_text(encoding='utf-8'))['archive_sha256'],'modified_files':['recommend.py','strict_validation.py','retrieval.py'],'source_preserved':True,'files':{str(p.relative_to(dest)):hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.glob('*.py')}}
    (HERE/'phase2_upgrade'/'build_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('UPGRADE',dest)

if __name__=='__main__':build()
