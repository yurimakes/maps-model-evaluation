import unittest
from run_phase2_model_ab import BoundedAzureClient,BudgetReached,metrics

class ModelABTests(unittest.TestCase):
    def test_budget_prevents_http_attempt(self):
        calls=[];client=BoundedAzureClient('https://example.invalid','fixture','fixture',{'used':0,'max_requests':0,'max_output_tokens':10},sender=lambda *a,**k:calls.append(1))
        with self.assertRaises(BudgetReached):client._post('fixture','chat/completions',{},None,0,'chat')
        self.assertEqual(calls,[])

    def test_output_limit_is_enforced_on_every_attempt(self):
        seen=[]
        class Response:
            status_code=200
            def json(self):return {'usage':{}}
        def sender(*args,**kwargs):seen.append(kwargs['json']);return Response()
        client=BoundedAzureClient('https://example.invalid','fixture','fixture',{'used':0,'max_requests':1,'max_output_tokens':10},sender=sender)
        client._post('fixture','chat/completions',{'max_completion_tokens':100},None,0,'chat')
        self.assertEqual(seen[0]['max_completion_tokens'],10)

    def test_negative_question_error_is_not_counted_as_correct_exclusion(self):
        m=metrics([{'gold':[],'predicted':[],'status':'ERROR'}])
        self.assertEqual(m['exact_decision_accuracy'],0);self.assertEqual(m['errors_or_invalid'],1)

    def test_invalid_proposal_is_not_counted_as_a_true_positive(self):
        m=metrics([{'gold':['A.X'],'predicted':['A.X'],'status':'INVALID_OR_REVIEW'}])
        self.assertEqual(m['tp'],0);self.assertEqual(m['fn'],1)

if __name__=='__main__':unittest.main(verbosity=2)
