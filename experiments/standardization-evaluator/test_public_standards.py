import unittest
import evaluate as ev
import check_public_standards as check


class PublicTests(unittest.TestCase):
    def setUp(self):
        self.good = ev.record('표준단어', 'T', 'c', '1', {'단어명': '고객', '약어': 'CUST'})
        self.public = {'표준단어': ({'고객': {self.good['AI결과']}}, '단어명')}

    def test_known_name_wrong_abbreviation_is_mismatch(self):
        p = {**self.good, 'AI결과': ev.canonical({'단어명':'고객','약어':'CUSTOMER'})}
        m = check.check_records([p], self.public)['metrics'][0]
        self.assertEqual(m['명세 불일치'], 1)
        self.assertEqual(m['명세준수율']['비율'], 0)

    def test_new_candidate_not_wrong_or_approved(self):
        r = check.check_records([self.good], {})
        # A loaded public dictionary has the area even when no name is registered.
        r = check.check_records([self.good], {'표준단어': ({}, '단어명')})
        self.assertEqual(r['details'][0]['판정'], '미등록 후보')
        self.assertIsNone(r['metrics'][0]['명세준수율']['비율'])

    def test_conflict_and_missing_are_outside_comparable_denominator(self):
        public = {'표준단어': ({'고객': {'a','b'}}, '단어명')}
        r = check.check_records([self.good], public)
        self.assertEqual(r['details'][0]['판정'], '사전 충돌')
        p = {**self.good, 'AI결과': ''}
        r = check.check_records([p], self.public)
        self.assertEqual(r['metrics'][0]['후보 없음'], 1)
        self.assertEqual(r['metrics'][0]['명세준수율']['분모'], 0)

    def test_duplicate_keys_stop_and_business_code_is_outside_scope(self):
        with self.assertRaises(ev.InputError):
            check.check_records([self.good, self.good], self.public)
        p = ev.record('표준코드', 'T', 'code', '01', {'코드그룹':'G','코드값':'001'})
        self.assertEqual(check.check_records([p], self.public)['details'][0]['판정'], '범위 밖')

    def test_true_match_does_not_claim_business_accuracy(self):
        result = check.check_records([self.good], self.public)
        self.assertEqual(result['metrics'][0]['명세준수율']['비율'], 1)
        self.assertIn('업무 의미 정확도', check.render(result))


if __name__ == '__main__':
    unittest.main()
