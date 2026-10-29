import copy,unittest
from model_comparison_utils import metrics,cross_source_evaluate

class NeuralEvaluationTests(unittest.TestCase):
    def test_positive_wrong_table_is_false_positive_and_false_negative(self):
        r=metrics([{'gold':['COMPLAINT.CUST_ID'],'predicted':['COUNSEL.CUST_ID'],'ranked':['COUNSEL.CUST_ID']}])
        self.assertEqual((r['tp'],r['fp'],r['fn']),(0,1,1))

    def test_negative_questions_penalize_precision(self):
        r=metrics([{'gold':['A.X'],'predicted':['A.X'],'ranked':['A.X']},{'gold':[],'predicted':['A.Y'],'ranked':['A.Y']}])
        self.assertEqual(r['precision'],.5);self.assertEqual(r['recall'],1)

    def test_heldout_labels_do_not_affect_own_threshold(self):
        rows=[{'id':'a','system':'A','gold':['T.X'],'ranked':['T.X'],'score':.8},{'id':'b','system':'B','gold':[],'ranked':['T.X'],'score':.7},{'id':'c','system':'C','gold':['T.X'],'ranked':['T.X'],'score':.9}]
        _,a=cross_source_evaluate(rows,'fixture');changed=copy.deepcopy(rows);changed[0]['gold']=[]
        _,b=cross_source_evaluate(changed,'fixture')
        self.assertEqual(next(r['threshold'] for r in a if r['heldout_system']=='A'),next(r['threshold'] for r in b if r['heldout_system']=='A'))

if __name__=='__main__':unittest.main(verbosity=2)
