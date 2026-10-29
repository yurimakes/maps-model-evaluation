import copy,json,unittest
import numpy as np
from phase2_original.data.maps_rag import recommend as old
from phase2_original.data.maps_rag.retrieval import Retriever as OriginalRetriever
from phase2_upgrade.maps_rag import recommend as new
from phase2_upgrade.maps_rag.retrieval import Retriever as ImprovedRetriever
from strict_validation import evaluate_scores

class Catalog:
    by_table={'COMPLAINT':[{'TABLE_NAME':'COMPLAINT','COLUMN_NAME':'CMPL_ID','KEY':'PK','NULLABLE':'N','DATA_TYPE':'VARCHAR(50)','DESCRIPTION':'민원접수번호'}]}
    all_ids={'COMPLAINT.CMPL_ID'}
    def exists(self,t):return t in self.all_ids
    def compact(self,t):return 'COMPLAINT.CMPL_ID [VARCHAR(50)] 민원접수번호'

class Lookups:
    def dq_rule(self,*args):return None
    def source_codes(self,*args):return []
    def std_codes_for(self,*args,**kwargs):return []

class NoRetrieval:
    def has_embeddings(self):return False
    def search(self,*args,**kwargs):return []

class ScriptedClient:
    """A deterministic test fixture, not an LLM or measured model prediction."""
    def __init__(self,responses):self.responses=responses;self.calls=[]
    def chat(self,*args,**kwargs):
        self.calls.append(kwargs);return json.dumps(self.responses[len(self.calls)-1]),{'prompt_tokens':0,'completion_tokens':0}

def detail(**overrides):
    p={'target':'COMPLAINT.CMPL_ID','mapping_type':'RENAME','process_type':'COPY','rule':'copy','evidence':['TOBE-COMPLAINT.CMPL_ID'],'gates':{'RELATION_FIT':'PASS','DATATYPE_CONVERTIBLE':'PASS'},'scores':dict.fromkeys(old.WEIGHTS,1.)}
    p.update(overrides);return p

def scan(gate='PASS',scores=None):return {'candidate_scan':[{'target':'COMPLAINT.CMPL_ID','gate_relation':gate,'gate_datatype':gate,'scores':dict.fromkeys(old.WEIGHTS,1.) if scores is None else scores}]}

class Phase2Tests(unittest.TestCase):
    def test_missing_scores_cannot_be_renormalized_to_high(self):
        p=detail(scores={'NAME':1.})
        self.assertEqual(old.validate(p,Catalog(),{'TOBE-COMPLAINT.CMPL_ID'})['confidence_score'],1.)
        r=new.validate(p,Catalog(),{'TOBE-COMPLAINT.CMPL_ID'})
        self.assertEqual(r['confidence_score'],.15)
        self.assertNotEqual(r['confidence_level'],'HIGH')
        self.assertIn('MISSING_SCORE_EVIDENCE',r['flags'])

    def test_justified_na_can_be_excluded_from_denominator(self):
        p=detail();p['scores']['CODE']=None;p['score_status']={'CODE':'NA'};p['na_reasons']={'CODE':'This is a non-code identifier.'}
        r=new.validate(p,Catalog(),{'TOBE-COMPLAINT.CMPL_ID'})
        self.assertEqual(r['confidence_score'],1.)
        self.assertEqual(r['confidence_level'],'HIGH')

    def test_unjustified_na_is_not_silently_accepted(self):
        e=evaluate_scores({'NAME':1.},{'CODE':'NA'})
        self.assertIn('CODE',e['invalid']);self.assertIn('CODE',e['missing'])

    def test_unknown_gate_is_not_pass(self):
        p=detail(gates={'RELATION_FIT':'NA','DATATYPE_CONVERTIBLE':'PASS'})
        self.assertEqual(old.validate(p,Catalog(),{'TOBE-COMPLAINT.CMPL_ID'})['confidence_level'],'HIGH')
        self.assertEqual(new.validate(p,Catalog(),{'TOBE-COMPLAINT.CMPL_ID'})['confidence_level'],'INVALID_CANDIDATE')

    def test_citing_unseen_evidence_blocks_valid_mapping(self):
        p=detail(evidence=['TOBE-COMPLAINT.CMPL_ID','invented'])
        self.assertEqual(new.validate(p,Catalog(),{'TOBE-COMPLAINT.CMPL_ID'})['confidence_level'],'INVALID_CANDIDATE')

    def test_no_evidence_blocks_valid_mapping(self):
        self.assertEqual(new.validate(detail(evidence=[]),Catalog(),set())['confidence_level'],'INVALID_CANDIDATE')

    def test_invalid_mapping_and_process_types_block_mapping(self):
        for field in ['mapping_type','process_type']:
            p=detail(**{field:'INVENTED'})
            self.assertEqual(new.validate(p,Catalog(),{'TOBE-COMPLAINT.CMPL_ID'})['confidence_level'],'INVALID_CANDIDATE')

    def test_out_of_range_and_non_finite_scores_rejected(self):
        for value in [2.,-1.,float('nan'),float('inf'),True]:
            p=detail();p['scores']['NAME']=value
            self.assertEqual(new.validate(p,Catalog(),{'TOBE-COMPLAINT.CMPL_ID'})['confidence_level'],'INVALID_CANDIDATE')

    def test_duplicate_candidate_is_flagged(self):
        p=scan();p['candidate_scan']*=2
        _,flags=new.validate_candidate_scan(p,Catalog(),'COMPLAINT')
        self.assertIn('DUPLICATE_TARGET',flags)

    def test_positive_two_stage_flow_is_preserved(self):
        row={'query_id':'fixture','channel':'HOMEPAGE','source_table':'homepage_complaint','source_column':'COMPLAINT_ID','as_is_desc':'민원접수번호'}
        for module in [old,new]:
            client=ScriptedClient([scan(),detail()])
            r,_=module.Recommender(Catalog(),Lookups(),NoRetrieval(),client,mode='bm25').recommend_v2(row)
            self.assertEqual(r['ai_target'],'COMPLAINT.CMPL_ID');self.assertEqual(len(client.calls),2);self.assertEqual(r['needs_human_review'],'Y')

    def test_unknown_scan_stops_before_unjustified_detail_call(self):
        row={'query_id':'fixture','channel':'HOMEPAGE','source_table':'homepage_complaint','source_column':'COMPLAINT_ID'}
        client=ScriptedClient([scan(gate='NA'),detail()])
        r,_=new.Recommender(Catalog(),Lookups(),NoRetrieval(),client,mode='bm25').recommend_v2(row)
        self.assertEqual(len(client.calls),1);self.assertIsNone(r['ai_target']);self.assertIn('INSUFFICIENT_EVIDENCE_NOT_EXCLUSION',r['flags'])

    def test_original_requires_complete_embedding_cache(self):
        chunks=[{'chunk_id':'a','text':'alpha'},{'chunk_id':'b','text':'beta'}]
        self.assertFalse(OriginalRetriever(chunks,{'a':[1.,0.]}).has_embeddings())
        improved=ImprovedRetriever(chunks,{'a':[1.,0.]})
        self.assertTrue(improved.has_embeddings())
        self.assertEqual(improved.search('',[1.,0.],mode='embedding')[0]['chunk']['chunk_id'],'a')

    def test_embedding_mode_without_query_vector_returns_no_fake_hits(self):
        chunks=[{'chunk_id':'a','text':'alpha'}]
        self.assertEqual(ImprovedRetriever(chunks,{'a':[1.,0.]}).search('alpha',mode='embedding'),[])

    def test_zero_relevance_does_not_fill_evidence_with_arbitrary_docs(self):
        chunks=[{'chunk_id':'a','text':'alpha'}]
        self.assertEqual(ImprovedRetriever(chunks).search('zzzz',mode='bm25'),[])

    def test_embedding_space_mismatch_is_explicit(self):
        with self.assertRaises(ValueError):ImprovedRetriever([{'chunk_id':'a','text':'alpha'}],{'a':[1.,0.]}).search('alpha',[1.,0.,0.])

    def test_default_full_cache_weighting_preserves_original_ranking(self):
        chunks=[{'chunk_id':'a','text':'alpha beta'},{'chunk_id':'b','text':'beta gamma'},{'chunk_id':'c','text':'gamma delta'}]
        vectors={'a':[1.,0.],'b':[.7,.3],'c':[.2,.8]}
        a=OriginalRetriever(chunks,vectors).search('alpha',[1.,0.],k=2)
        b=ImprovedRetriever(chunks,vectors).search('alpha',[1.,0.],k=2)
        self.assertEqual([x['chunk']['chunk_id'] for x in a],[x['chunk']['chunk_id'] for x in b])
        for x,y in zip(a,b):self.assertAlmostEqual(x['score'],y['score'],places=6)

if __name__=='__main__':unittest.main(verbosity=2)
