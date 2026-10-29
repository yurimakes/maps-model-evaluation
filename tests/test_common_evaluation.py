import copy
import unittest
from evaluation.metrics import summarize
from evaluation.contract import comparison_key, validate

class ContractTests(unittest.TestCase):
    def row(self,gold,pred,rank=None):
        return dict(query_key='S|T|C',system='S',fold='S',gold=gold,predicted=pred,ranked=pred if rank is None else rank)

    def test_wrong_table_counts_fp_and_fn(self):
        m=summarize([self.row(['A.ID'],['B.ID'])])
        self.assertEqual((m['tp'],m['fp'],m['fn']),(0,1,1))

    def test_multiple_gold_targets_and_accuracy_denominators(self):
        m=summarize([self.row(['A.ID','B.ID'],['A.ID'])])
        self.assertEqual(m['mapping_recall'],.5)
        self.assertEqual(m['decision_accuracy'],1)
        self.assertEqual(m['exact_set_accuracy'],0)
        self.assertEqual(m['top1_hit_rate'],1)
        self.assertEqual(m['pair_recall_at1'],.5)

    def test_negative_questions_and_abstention(self):
        m=summarize([self.row([],['A.ID']),self.row(['A.ID'],[]),self.row([],[])])
        self.assertEqual((m['tp'],m['fp'],m['fn']),(0,1,1))
        self.assertEqual(m['decision_accuracy'],1/3)

    def test_ranking_does_not_imply_a_mapping(self):
        m=summarize([self.row(['A.ID'],[],['A.ID'])])
        self.assertEqual(m['top1_hit_rate'],1)
        self.assertEqual(m['mapping_f1'],0)

    def test_duplicate_missing_gold_and_candidate_errors(self):
        expected={'S|T|C':['A.ID']};allowed={'S|T|C':['A.ID','B.ID']}
        good=self.row(['A.ID'],['A.ID'])
        validate([good],expected,allowed)
        for bad in [[],[good,good],[self.row(['B.ID'],['A.ID'])],[self.row(['A.ID'],['C.ID'])],
                    [self.row(['A.ID'],['A.ID'],['A.ID','A.ID'])]]:
            with self.assertRaises(ValueError):validate(bad,expected,allowed)

    def test_different_protocol_or_cohort_cannot_share_comparison_key(self):
        expected={'q':['A.ID']};allowed={'q':['A.ID','B.ID']}
        key=comparison_key(expected,allowed,'nested-loso')
        self.assertNotEqual(key,comparison_key(expected,allowed,'replay'))
        self.assertNotEqual(key,comparison_key(expected,{'q':['A.ID']},'nested-loso'))
        self.assertNotEqual(key,comparison_key({'q':[]},allowed,'nested-loso'))

if __name__=='__main__':unittest.main(verbosity=2)
