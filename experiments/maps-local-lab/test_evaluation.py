"""Tests for conclusions that can be invalidated by metric or leakage bugs."""
import copy,json,unittest
import numpy as np
from run_experiments import HERE,Features,summarize,tune_threshold

class EvaluationTests(unittest.TestCase):
    def row(self,gold,pred,rank=None):
        return {'gold':gold,'predicted':pred,'ranked':rank or pred}

    def test_wrong_table_is_wrong_mapping(self):
        m=summarize([self.row(['COUNSEL.CUST_ID'],['CUSTOMER.CUST_ID'])])
        self.assertEqual((m['tp'],m['fp'],m['fn']),(0,1,1))
        self.assertEqual(m['mapping_f1'],0)

    def test_multitarget_is_not_collapsed(self):
        m=summarize([self.row(['CONTRACT.PRD_ID','COUNSEL.PRD_ID'],['COUNSEL.PRD_ID'])])
        self.assertEqual(m['mapping_precision'],1)
        self.assertEqual(m['mapping_recall'],.5)
        self.assertAlmostEqual(m['mapping_f1'],2/3)
        self.assertEqual(m['top1_accuracy'],1)
        self.assertEqual(m['exact_set_accuracy'],0)

    def test_exclusions_affect_precision(self):
        m=summarize([self.row(['A.X'],['A.X']),self.row([],['A.Y']),self.row([],[])])
        self.assertEqual(m['mapping_precision'],.5)
        self.assertEqual(m['mapping_recall'],1)
        self.assertAlmostEqual(m['decision_accuracy'],2/3)

    def test_test_labels_do_not_change_scores_or_threshold(self):
        data=json.loads((HERE/'data'/'snapshot.json').read_text(encoding='utf-8'))
        f=Features(data)
        train=[i for i,q in enumerate(f.q) if q['system']!='CHATBOT']
        original=f.scores('hybrid_transfer',train).copy()
        threshold=tune_threshold(f,'hybrid_transfer',train)
        # Perturb all held-out labels, leaving only schema metadata untouched.
        for i,q in enumerate(f.q):
            if q['system']=='CHATBOT':
                q['gold']=['CUSTOMER.CUST_ID'] if not q['gold'] else []
                f.gold[i]=set(q['gold'])
        np.testing.assert_array_equal(original,f.scores('hybrid_transfer',train))
        self.assertEqual(threshold,tune_threshold(f,'hybrid_transfer',train))

    def test_snapshot_integrity_and_unique_query_units(self):
        d=json.loads((HERE/'data'/'snapshot.json').read_text(encoding='utf-8'))
        self.assertEqual(len(d['queries']),len({q['id'] for q in d['queries']}))
        self.assertTrue(all(not q['column'].startswith('<') for q in d['queries']))
        targets={t['id'] for t in d['targets']}
        self.assertTrue(all(set(q['gold'])<=targets for q in d['queries']))
        self.assertEqual(sum(len(q['gold']) for q in d['queries']),68)

if __name__=='__main__':unittest.main(verbosity=2)
