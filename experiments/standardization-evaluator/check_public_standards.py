"""Public dictionary specification checks, without business gold or model calls."""
import argparse
import html
import json
from collections import Counter
from pathlib import Path

import evaluate as ev
import compare_reference_bases as ref

CHECK_IDS = {'표준단어': 'P01', '표준용어': 'P02', '표준도메인': 'P03'}
FILES = ('공통표준단어_20251101.csv', '공통표준용어_20251101.csv', '공통표준도메인_20251101.csv')


def check_records(predictions, public):
    ev.unique(predictions, 'AI 결과')
    details = []
    for p in predictions:
        area, value = p['평가영역'], p['AI결과']
        check_id = CHECK_IDS.get(area, '')
        expected = ''
        if area not in public:
            state, reason = '범위 밖', '공공 단어·용어·도메인 사전만으로 연결·코드의 업무 정답을 판단하지 않음'
        elif not value:
            state, reason = '후보 없음', 'AI 답 공란; 준수율 분모에서 제외하고 미제공으로 보고'
        else:
            ev.validate_payload(area, value, 'AI 결과')
            dictionary, field = public[area]
            values = dictionary.get(json.loads(value)[field], set())
            if not values:
                state, reason = '미등록 후보', '신규 후보·별칭·폐기 여부 확인 필요; 자동 오답 또는 승인 아님'
            elif len(values) != 1:
                state, reason = '사전 충돌', '동일 이름에 복수 명세; 판정 보류'
            else:
                expected = next(iter(values))
                state = '명세 일치' if ev.canonical(value) == expected else '명세 불일치'
                reason = '선택한 이름의 사전 명세 비교; 원천 업무 의미의 선택 타당성은 평가하지 않음'
        details.append({**{k: p[k] for k in ev.IDENTITY}, '평가항목ID': check_id,
                        'AI결과': value, '사전명세': expected, '판정': state, '이유': reason,
                        '신뢰도': p.get('신뢰도', '')})
    metrics = []
    for area, check_id in CHECK_IDS.items():
        rows = [d for d in details if d['평가영역'] == area]
        counts = Counter(d['판정'] for d in rows)
        n = counts['명세 일치'] + counts['명세 불일치']
        metrics.append({'평가항목ID': check_id, '평가영역': area, '제공된대응수': len(rows),
                        **{s: counts[s] for s in ('명세 일치', '명세 불일치', '미등록 후보', '사전 충돌', '후보 없음')},
                        '명세준수율': ev.rate(counts['명세 일치'], n),
                        '사전대조커버리지': ev.rate(n, len(rows))})
    return {'metrics': metrics, 'details': details}


def render(result):
    def pct(rate):
        return '미측정' if rate['비율'] is None else f"{rate['비율']:.1%} ({rate['분자']}/{rate['분모']})"
    rows = ''
    for m in result['metrics']:
        values = [m['평가영역'], m['제공된대응수'], m['명세 일치'], m['명세 불일치'],
                  m['미등록 후보'], m['사전 충돌'], m['후보 없음'], pct(m['명세준수율']), pct(m['사전대조커버리지'])]
        rows += '<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in values)+'</tr>'
    return '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>공공표준 명세 점검</title>
<style>body{font:16px/1.7 system-ui;max-width:1200px;margin:32px auto;padding:0 20px;color:#253443}h1{font-size:26px}table{border-collapse:collapse;min-width:900px;width:100%}td,th{padding:12px;border-bottom:1px solid #ddd;text-align:left}th{background:#294560;color:white}.note{padding:16px;background:#fff2cc}.scroll{overflow-x:auto}</style>
<h1>공공표준 기반 표준화: 명세 준수 점검</h1>
<p class="note">07.8.1 평가 기준에 따른 사전 명세 점검입니다. 업무 의미 정확도·공식 표준 인증·신규 후보 승인을 뜻하지 않습니다.</p>
<div class="scroll"><table><tr><th>영역</th><th>제공 대응</th><th>일치</th><th>불일치</th><th>미등록</th><th>충돌</th><th>후보 없음</th><th>명세 준수율</th><th>대조 커버리지</th></tr>'''+rows+'''</table></div>
<h2>결과를 읽는 방법</h2><p>준수율은 사전에 단일 명세가 있는 항목만 분모로 삼습니다. 미등록·충돌·후보 없음은 따로 보고하며, 사전 미등록을 자동 오답으로 처리하지 않습니다. 이 결과는 제공된 CSV 행의 범위입니다. 출력에서 통째로 누락된 원천 컬럼의 재현율은 측정하지 않습니다.</p>
<p>용어는 이름·약어만 비교합니다. 구성단어 조합·형식단어·용어와 도메인 연결·정의의 적절성은 추가 확인 대상입니다. 도메인은 이름·타입·길이·소수점 길이를 비교하며 실제 데이터 변환 품질은 포함하지 않습니다.</p>
<p>입력·사전·평가 기준의 해시는 점검결과.json에 저장합니다. 모델·프롬프트·검색 버전은 생성 작업 기록으로 별도 보완합니다. 신뢰도 high/low를 정확도나 자동 승인으로 해석하지 않습니다.</p></html>'''


def run(ai, public_dir, out):
    predictions, inputs = ev.load_ai(ai)
    policy_path = Path(__file__).with_name('public-evaluation-policy.json')
    policy = json.loads(policy_path.read_text(encoding='utf-8'))
    result = check_records(predictions, ref.load_public(public_dir))
    result['manifest'] = {'protocol': policy['version'], 'policy_sha256': ev.sha(policy_path.read_bytes()),
                          'AI_inputs': inputs, 'public_inputs': [{'name': n, 'sha256': ev.sha((Path(public_dir)/n).read_bytes())} for n in FILES],
                          'business_accuracy_measured': False, 'new_candidates_approved': False,
                          'generation_versions': '별도 생성 기록 확인 필요'}
    target = ev.new_directory(out)
    (target/'점검결과.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    ev.write_csv(target/'상세점검.csv', [*ev.IDENTITY, '평가항목ID', 'AI결과', '사전명세', '판정', '이유', '신뢰도'], result['details'])
    (target/'보고서.html').write_text(render(result), encoding='utf-8')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='정답 CSV 없이 공공표준의 등록 명세를 점검합니다.')
    for name in ('ai', 'public-standards', 'out'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    try:
        print(run(args.ai, args.public_standards, args.out).resolve())
    except (ev.InputError, OSError, KeyError, ValueError) as exc:
        parser.exit(2, f'실행 중단: {exc}\n')
