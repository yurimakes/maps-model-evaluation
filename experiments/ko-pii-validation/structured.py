"""Read and mask actual synthetic CSV/JSON files, then measure field residuals."""
from pathlib import Path
import copy, csv, hashlib, json, sys
ROOT=Path(__file__).resolve().parents[1]
from ko_pii import Anonymizer, ProcessingMode, anonymize_json
from ko_pii.tabular import anonymize_records, map_columns

COLUMN_MAP={'customer_name':'PERSON','phone_number':'PHONE','email':'EMAIL',
 'address':'ADDRESS','birth_date':'DT_BIRTH','account_number':'ACCOUNT'}
HEADERS=[*COLUMN_MAP,'policy_id','consultation_note','status']
def dump_json(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def dump_csv(p,rows):
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=HEADERS);w.writeheader();w.writerows(rows)

def metrics(before,after):
 cells=[(i,c,str(r[c])) for i,r in enumerate(before) for c in COLUMN_MAP if r[c] is not None and r[c]!='']
 left=[{'row':i+1,'column':c} for i,c,value in cells if value in str(after[i][c])]
 return {'rows':len(before),'target_nonempty_cells':len(cells),'original_value_remaining_cells':len(left),
         'remaining_locations':left,'row_and_column_shape_preserved':len(before)==len(after) and all(list(a)==list(b) for a,b in zip(before,after))}

def run(out, files):
 records = json.loads((files/'synthetic_input.json').read_text(encoding='utf-8'))['rows']
 originals={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files.iterdir() if p.is_file()}
 with (files/'synthetic_input.csv').open(encoding='utf-8-sig',newline='') as f:csv_rows=list(csv.DictReader(f))
 json_payload=json.loads((files/'synthetic_input.json').read_text(encoding='utf-8'))
 snapshot=copy.deepcopy(json_payload)
 csv_auto,_=anonymize_records(csv_rows,strategy='redact',mode=ProcessingMode.STRICT)
 csv_explicit,_=anonymize_records(csv_rows,column_map=COLUMN_MAP,strategy='redact',mode=ProcessingMode.STRICT)
 json_auto=anonymize_json(json_payload,anonymizer=Anonymizer(strategy='redact',mode=ProcessingMode.STRICT)).data
 labels={f'/rows/{i}/{c}':label for i in range(len(records)) for c,label in COLUMN_MAP.items()}
 json_explicit=anonymize_json(json_payload,anonymizer=Anonymizer(strategy='redact',mode=ProcessingMode.STRICT),field_labels=labels).data
 dump_csv(out/'csv_auto.csv',csv_auto);dump_csv(out/'csv_explicit.csv',csv_explicit)
 dump_json(out/'json_auto.json',json_auto);dump_json(out/'json_explicit.json',json_explicit)
 # Integer and null identifiers are a separate JSON boundary case.
 numeric={'phone_number':1023456789,'account_number':0,'customer_name':None}
 numeric_auto=anonymize_json(numeric,anonymizer=Anonymizer(strategy='redact')).data
 numeric_explicit=anonymize_json(numeric,anonymizer=Anonymizer(strategy='redact'),field_labels={'/phone_number':'PHONE','/account_number':'ACCOUNT','/customer_name':'PERSON'}).data
 errors=[]
 for case,data,fields in [
  ('bool_identifier',{'phone_number':True},{'/phone_number':'PHONE'}),
  ('missing_pointer',{'phone_number':'010-2345-6789'},{'/missing':'PHONE'}),
  ('float_identifier',{'phone_number':10.5},{'/phone_number':'PHONE'})]:
  try:anonymize_json(data,anonymizer=Anonymizer(strategy='redact'),field_labels=fields);rejected=False
  except ValueError:rejected=True
  errors.append({'case':case,'rejected':rejected})
 result={'notice':'Synthetic field-residual comparison. Explicit labels are schema assertions, not improved automatic detector accuracy.',
  'column_map':COLUMN_MAP,'auto_header_map':map_columns(HEADERS),
  'csv_auto':metrics(csv_rows,csv_auto),'csv_explicit':metrics(csv_rows,csv_explicit),
  'json_auto':metrics(records,json_auto['rows']),'json_explicit':metrics(records,json_explicit['rows']),
  'free_text_policy_note':'CSV table API preserves unmapped note values; JSON recursively detects string values but can miss them. Notes and custom policy IDs remain outside explicit 6-column assurance.',
  'custom_policy_id_remaining_all_outputs':all(all(a['policy_id']==b['policy_id'] for a,b in zip(records,r)) for r in [csv_auto,csv_explicit,json_auto['rows'],json_explicit['rows']]),
  'csv_unmapped_notes_unchanged':all(a['consultation_note']==b['consultation_note'] for a,b in zip(records,csv_explicit)),
  'numeric_json':{'input':numeric,'auto':numeric_auto,'explicit':numeric_explicit},
  'error_cases':errors,'input_objects_unchanged':json_payload==snapshot and csv_rows==records,
  'input_file_hashes_before':originals,'input_file_hashes_after':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files.iterdir() if p.is_file()}}
 dump_json(out/'structured_results.json',result)
 assert result['input_objects_unchanged']
 assert result['input_file_hashes_before']==result['input_file_hashes_after']
 assert result['csv_explicit']['original_value_remaining_cells']==0
 assert result['json_explicit']['original_value_remaining_cells']==0
 assert all(c['rejected'] for c in errors)
 return result
