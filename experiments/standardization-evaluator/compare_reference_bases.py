"""Two explicitly non-independent reference checks; never approve a gold label."""
import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

import evaluate as ev


def index(rows, name, payload):
    result = defaultdict(set)
    for row in rows:
        if row.get('개정구분명(폐기 또는 변경)', '') == '폐기':
            continue
        result[row[name]].add(ev.canonical(payload(row)))
    return result


def load_public(folder):
    def read(name):
        return ev.read_csv_bytes((Path(folder) / name).read_bytes(), name)[1]
    words = index(read('공통표준단어_20251101.csv'), '공통표준단어명',
                  lambda r: {'단어명': r['공통표준단어명'], '약어': r['공통표준단어영문약어명']})
    terms = index(read('공통표준용어_20251101.csv'), '공통표준용어명',
                  lambda r: {'용어명': r['공통표준용어명'], '약어': r['공통표준용어영문약어명']})
    domains = index(read('공통표준도메인_20251101.csv'), '공통표준도메인명',
                    lambda r: {'도메인명': r['공통표준도메인명'], '타입': r['데이터타입'],
                               '길이': r['데이터길이'], '소수점길이': r['데이터소수점길이']})
    return {'표준단어': (words, '단어명'), '표준용어': (terms, '용어명'), '표준도메인': (domains, '도메인명')}


def compare(predictions, target_gold, public):
    # The target CSV freezes the population, so missing predictions cannot disappear.
    pm, gm = ev.unique(predictions, 'AI 결과'), ev.unique(target_gold, '2차 참조 후보')
    rows = []
    for k, g in gm.items():
        p = pm.get(k)
        predicted = p['AI결과'] if p else ''
        for basis in ('2차 이관 타겟 기준', '공공표준 사전 기준'):
            expected, state, reason = '', '미측정', ''
            if basis == '2차 이관 타겟 기준':
                expected = g['정답']
                if not expected:
                    reason = '연결된 참조 후보 없음; 정답 누락을 오답으로 세지 않음'
                else:
                    reason = '기존 기준의 후보와 명세 문자열 대조; 이번 평가 정답 승인 아님'
            elif k[0] not in public:
                reason = '제공된 공공 단어·용어·도메인 사전으로 이 영역의 정답을 만들 수 없음'
            elif not predicted:
                reason = 'AI가 후보를 내지 않아 사전 선택 정합성을 비교할 수 없음'
            else:
                dictionary, field = public[k[0]]
                values = dictionary.get(json.loads(predicted)[field], set())
                if len(values) == 1:
                    expected = next(iter(values))
                    reason = 'AI가 고른 이름으로 공공사전 조회; 해당 선택의 업무 의미 정확도는 미검증'
                elif not values:
                    reason = '공공사전 미등록/신규 후보; 오답 확정 아님'
                else:
                    reason = '동일 이름에 서로 다른 사전 명세가 있어 추가 확인 필요'
            if expected:
                state = '일치' if p and predicted and predicted == expected else '차이'
            rows.append({**dict(zip(ev.IDENTITY, k)), '기준': basis, 'AI결과': predicted,
                         '참조값': expected, '참고판정': state, '이유': reason,
                         '정답상태': g['정답상태'], '독립성': g['독립성']})
    metrics = []
    for basis in ('2차 이관 타겟 기준', '공공표준 사전 기준'):
        for area in ev.AREAS:
            subset = [r for r in rows if r['기준'] == basis and r['평가영역'] == area]
            counts = {s: sum(r['참고판정'] == s for r in subset) for s in ('일치', '차이', '미측정')}
            n = counts['일치'] + counts['차이']
            metrics.append({'기준': basis, '영역': area, '전체': len(subset), '참고비교가능': n,
                            **counts, '참고문자열일치율': counts['일치'] / n if n else None,
                            '참고커버리지': n / len(subset) if subset else None})
    return rows, metrics, [p for k, p in pm.items() if k not in gm]


def run(ai, target_gold, public_dir, out):
    predictions, inputs = ev.load_ai(ai)
    gold, gold_hash = ev.load_gold(target_gold)
    public = load_public(public_dir)
    details, metrics, extras = compare(predictions, gold, public)
    out = ev.new_directory(out)
    ev.write_csv(out / '두기준_참고비교.csv', list(metrics[0]), metrics)
    ev.write_csv(out / '두기준_상세.csv', list(details[0]), details)
    ev.write_csv(out / '범위밖예측.csv', ev.AI_FIELDS, extras)
    paths = sorted(Path(public_dir).glob('공통표준*_20251101.csv'))
    result = {'measurement': 'reference agreement only, not independent accuracy', 'metrics': metrics,
              'AI_inputs': inputs, 'target_candidates_sha256': gold_hash,
              'public_inputs': [{'name': p.name, 'sha256': ev.sha(p.read_bytes())} for p in paths],
              'gold_approval_changed': False}
    (out / '두기준_결과.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    def esc(value):
        return html.escape(str(value))
    body = ''
    for m in metrics:
        pct = '미측정' if m['참고문자열일치율'] is None else f'{m["참고문자열일치율"]:.1%}'
        body += '<tr>' + ''.join(f'<td>{esc(v)}</td>' for v in [m['기준'], m['영역'], m['전체'],
            m['참고비교가능'], m['일치'], m['차이'], m['미측정'], pct]) + '</tr>'
    (out / '두기준_보고서.html').write_text('''<!doctype html><html lang="ko"><meta charset="utf-8"><title>MAPS 두 기준 참고 비교</title>
<style>body{font:16px/1.6 system-ui;max-width:1300px;margin:40px auto;padding:20px;color:#253443}table{border-collapse:collapse;width:100%}th,td{padding:10px;border-bottom:1px solid #ddd;text-align:left}th{background:#294560;color:white}.note{background:#fff2cc;padding:18px}</style>
<h1>찬기님 1차 결과: 두 기준 참고 비교</h1><p class="note">아래는 독립 정확도가 아닙니다. 정답 승인 상태를 바꾸지 않고 기존 타겟 후보와 공공표준 사전의 명세를 대조했습니다.</p>
<p>2차 기준은 기존 이관 기준과의 일치를, 공공표준 기준은 AI가 선택한 이름의 사전 명세 일치를 봅니다. 대상과 질문이 달라 두 점수를 빼서 우열이나 개선 효과를 말할 수 없습니다.</p>
<table><tr><th>기준</th><th>영역</th><th>전체</th><th>비교 가능</th><th>일치</th><th>차이</th><th>미측정</th><th>참고 일치율</th></tr>''' + body + '''</table>
<p>‘차이’는 의미 오류 확정이 아닙니다. 코드 체계·약어·도메인 정책 차이가 포함됩니다. 승인된 의미 동등성은 별도 정답지에 기록해야 합니다.</p>
<p>공공사전 미등록 신규 단어·용어·도메인은 자동 오답으로 세지 않았습니다. 사전에 등록됐다는 사실만으로 원천 컬럼에 맞게 선택했다고 입증되지는 않습니다.</p>
<p>컬럼 연결과 개별 코드 대응의 공공표준 정답은 제공 자료만으로 만들지 못해 미측정입니다. 단어는 구성 순번 기준의 부분 대조입니다. 두기준_상세.csv에서 이유와 미측정 항목을 확인하세요.</p>
<p><a href="두기준_참고비교.csv">집계 CSV</a> / <a href="두기준_상세.csv">상세와 확인 이유</a></p></html>''', encoding='utf-8')
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='두 기준 참고 대조. 독립 정답을 승인하거나 정확도를 산출하지 않음.')
    for name in ('ai', 'target-gold', 'public-standards', 'out'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        print(run(args.ai, args.target_gold, args.public_standards, args.out).resolve())
    except (ev.InputError, OSError, KeyError, ValueError) as exc:
        parser.exit(2, f'실행 중단: {exc}\n')
