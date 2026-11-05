"""Check frozen synthetic regression expectations; not an independent accuracy test."""
from pathlib import Path
import argparse, hashlib, json

def verify(path):
    read=lambda name:json.loads((path/name).read_text(encoding='utf-8'))
    summary=read('summary.json');text=read('probe_results.json');structured=read('structured_results.json')
    assert summary['all_text']['STRICT']==dict(tp=39,fp=5,fn=14,gold=53,literal_remaining=15,uncovered=15)
    assert summary['all_text']['PARANOID']==dict(tp=39,fp=5,fn=14,gold=53,literal_remaining=12,uncovered=14)
    assert summary['dialogue']['STRICT']==dict(tp=10,fp=2,fn=8,gold=18,literal_remaining=8,uncovered=8)
    assert len(text['STRICT']['cases'])==53
    assert read('run_manifest.json')['fixture_sha256']=='6cf41b43ee87eeef07c691135d64d50be0e0fe1d186da192d5817ea208b71c2b'
    for name,remaining in [('csv_auto',22),('csv_explicit',0),('json_auto',27),('json_explicit',0)]:
        assert structured[name]['target_nonempty_cells']==46
        assert structured[name]['original_value_remaining_cells']==remaining
        assert structured[name]['row_and_column_shape_preserved']
    assert structured['input_objects_unchanged']
    assert structured['input_file_hashes_before']==structured['input_file_hashes_after']
    assert all(case['rejected'] for case in structured['error_cases'])
    assert structured['custom_policy_id_remaining_all_outputs']
    assert structured['csv_unmapped_notes_unchanged']
    # Critical distinction: output can change while part of a sensitive span remains.
    address=next(c for c in text['PARANOID']['cases'] if c['id']=='dialogue_address_local')
    assert address['input']!=address['output'] and 'ADDRESS' in address['uncovered_labels']
    assert structured['numeric_json']['explicit']=={'phone_number':'[전화번호]','account_number':'[계좌번호]','customer_name':None}
    print('Frozen fixture counts, masking residuals, input preservation and rejection boundaries verified.')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--results',required=True)
    verify(Path(parser.parse_args().results))
