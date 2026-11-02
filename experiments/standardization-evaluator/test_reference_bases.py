import unittest
import evaluate as ev
import compare_reference_bases as ref


class ReferenceTests(unittest.TestCase):
    def test_distinct_source_identity_is_not_an_automatic_match(self):
        a = ev.record('컬럼 연결', '인바운드.상담정보', 'customer_name', '', '고객명')
        b = ev.record('컬럼 연결', '아웃바운드.고객정보', 'customer_name', '', '고객명')
        g = {**{k: a[k] for k in ev.IDENTITY}, '정답': '고객명', '정답상태': '미확정', '독립성': '미확인'}
        rows, metrics, extras = ref.compare([b], [g], {})
        self.assertEqual(rows[0]['참고판정'], '차이')  # prediction for source A is missing
        self.assertEqual(len(extras), 1)
        self.assertEqual(g['정답상태'], '미확정')

    def test_public_lookup_is_consistency_not_semantic_accuracy(self):
        p = ev.record('표준단어', 'T', 'c', '1', {'단어명': '고객', '약어': 'CUST'})
        g = {**{k: p[k] for k in ev.IDENTITY}, '정답': '', '정답상태': '미확정', '독립성': '미확인'}
        public = {'표준단어': ({'고객': {p['AI결과']}}, '단어명')}
        rows, metrics, _ = ref.compare([p], [g], public)
        self.assertEqual(rows[0]['참고판정'], '미측정')
        self.assertEqual(rows[1]['참고판정'], '일치')
        self.assertEqual(g['독립성'], '미확인')

    def test_retired_and_conflicting_public_definitions(self):
        rows = [{'n': '고객', 'a': 'OLD', '개정구분명(폐기 또는 변경)': '폐기'},
                {'n': '고객', 'a': 'CUST'}, {'n': '고객', 'a': 'CUSTOMER'}]
        idx = ref.index(rows, 'n', lambda r: {'약어': r['a']})
        self.assertEqual(len(idx['고객']), 2)
        self.assertNotIn(ev.canonical({'약어': 'OLD'}), idx['고객'])


if __name__ == '__main__':
    unittest.main()
