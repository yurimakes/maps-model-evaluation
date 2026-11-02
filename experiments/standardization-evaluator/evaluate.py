"""MAPS CSV evaluator. Python 3.10+; standard library only; no LLM/network calls."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

AREAS = ('컬럼 연결', '표준단어', '표준용어', '표준도메인', '표준코드')
IDENTITY = ('평가영역', '원천표', '원천컬럼', '평가항목')
AI_FIELDS = (*IDENTITY, 'AI결과', '신뢰도')
GOLD_FIELDS = (*IDENTITY, '정답', '의미상허용값', '정답상태', '독립성', '정답버전', '근거', '검토자')
PROTOCOL = {
    'version': '1.0',
    'key': list(IDENTITY),
    'normalization': 'JSON object key order only; preserve string case, spaces and leading zeros',
    'column_link': 'source column -> selected standard term; not metadata linkage accuracy',
    'word': 'ordered constituent slot -> word name + abbreviation; freeze segmentation protocol',
    'term': 'term name + abbreviation',
    'domain': 'domain name + data type + length + scale; actual value/transform validity not measured',
    'code': 'standard code group name + code value; no row-frequency weighting',
    'abstention': 'blank or missing predictions are wrong when an approved gold answer exists',
    'semantic': 'only aliases pre-approved in gold CSV; no fuzzy or LLM judge',
    'population': 'gold CSV defines fixed evaluation population; extra predictions reported separately',
}


class InputError(ValueError):
    pass


def canonical(value):
    """Only structural JSON equality; do not coerce 001 to 1 or change identifier case."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value
        if not isinstance(parsed, (dict, list)):
            return value
        value = parsed
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def validate_payload(area, value, label):
    if value == '':
        return
    fields = {'표준단어': {'단어명', '약어'}, '표준용어': {'용어명', '약어'},
              '표준도메인': {'도메인명', '타입', '길이', '소수점길이'}, '표준코드': {'코드그룹', '코드값'}}
    if area == '컬럼 연결':
        if not isinstance(value, str):
            raise InputError(f'{label}: 컬럼 연결 결과는 표준용어명 문자열이어야 합니다.')
        return
    try:
        obj = json.loads(value) if isinstance(value, str) else value
    except ValueError as exc:
        raise InputError(f'{label}: {area} 결과는 지정된 필드의 JSON 객체여야 합니다.') from exc
    if not isinstance(obj, dict) or set(obj) != fields[area] or any(not isinstance(v, str) for v in obj.values()):
        raise InputError(f'{label}: {area} 필드 {sorted(fields[area])}를 문자열 값으로 제공하세요.')
    required = fields[area] - ({'길이', '소수점길이'} if area == '표준도메인' else set())
    if any(obj[x] == '' for x in required):
        raise InputError(f'{label}: {area}의 필수 값이 비었습니다. 미결정은 결과 칸 전체를 공란으로 두세요.')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_csv_bytes(data, label):
    for encoding in ('utf-8-sig', 'cp949'):
        try:
            content = data.decode(encoding)
            break
        except UnicodeDecodeError:
            pass
    else:
        raise InputError(f'{label}: UTF-8 또는 CP949 CSV가 아닙니다.')
    reader = csv.DictReader(io.StringIO(content, newline=''))
    fields = reader.fieldnames or []
    if not fields or len(fields) != len(set(fields)):
        raise InputError(f'{label}: 헤더가 없거나 같은 헤더가 중복됩니다.')
    rows = []
    for i, row in enumerate(reader, 2):
        if None in row or any(v is None for v in row.values()):
            raise InputError(f'{label} {i}행: 열 개수가 헤더와 다릅니다.')
        if any(row.values()):
            rows.append(row)
    return fields, rows


def require(fields, needed, label):
    missing = set(needed) - set(fields)
    if missing:
        raise InputError(f'{label}: 필요한 열이 없습니다: {", ".join(sorted(missing))}')


def key(row):
    require(row, IDENTITY, '평가 키')
    if row['평가영역'] not in AREAS:
        raise InputError(f'알 수 없는 평가영역: {row["평가영역"]}')
    if not row['원천표'] or not row['원천컬럼']:
        raise InputError('원천표·원천컬럼은 비울 수 없습니다.')
    if row['평가영역'] == '표준단어' and not re.fullmatch(r'[1-9][0-9]*', row['평가항목']):
        raise InputError('표준단어 평가항목은 구성단어 순번(1, 2, ...)이어야 합니다.')
    return tuple(row[name] for name in IDENTITY)


def unique(rows, label):
    result = {}
    for row in rows:
        k = key(row)
        if k in result:
            raise InputError(f'{label}: 평가 키 중복: {k}')
        result[k] = row
    return result


def record(area, table, column, item, prediction, confidence=''):
    return dict(zip(AI_FIELDS, (area, table, column, item, canonical(prediction), confidence)))


def load_ai(path):
    path = Path(path)
    if not path.exists():
        raise InputError(f'AI 결과 파일을 찾을 수 없습니다: {path}')
    if path.is_file() and path.suffix.lower() == '.csv':
        data = path.read_bytes()
        fields, rows = read_csv_bytes(data, path.name)
        require(fields, AI_FIELDS[:-1], path.name)
        for row in rows:
            row['AI결과'] = canonical(row['AI결과'])
            row.setdefault('신뢰도', '')
            key(row)
            validate_payload(row['평가영역'], row['AI결과'], 'AI CSV')
        unique(rows, 'AI CSV')
        if not rows:
            raise InputError('AI CSV가 비었습니다. 없는 예측은 해당 행의 AI결과를 공란으로 남기세요.')
        return rows, [{'name': path.name, 'sha256': sha(data)}]

    names = ('1.표준단어사전.csv', '2.표준도메인사전.csv', '3.표준용어사전.csv',
             '4.표준코드.csv', '5.비표준_표준_매핑.csv', '6.원천코드_표준코드_매핑.csv')
    contents = {}
    if path.is_dir():
        for name in names:
            matches = list(path.rglob(name))
            if len(matches) != 1:
                raise InputError(f'{name}: 파일이 정확히 1개 있어야 합니다. 발견 {len(matches)}개')
            contents[name] = matches[0].read_bytes()
    elif path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                name = entry.filename
                if not entry.flag_bits & 2048:
                    try:
                        name = name.encode('cp437').decode('cp949')
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        pass
                name = name.replace('\\', '/').split('/')[-1]
                if name in names:
                    if name in contents:
                        raise InputError(f'ZIP에 같은 이름의 CSV가 여러 개 있습니다: {name}')
                    contents[name] = archive.read(entry)
            # Never extract or execute files; requests/logs are not read.
    else:
        raise InputError('AI 입력은 11/2 형식의 ZIP·폴더 또는 공통 형식 CSV여야 합니다.')
    missing = set(names) - set(contents)
    if missing:
        raise InputError('AI 결과에 필요한 CSV가 없습니다: ' + ', '.join(sorted(missing)))
    parsed = {name: read_csv_bytes(contents[name], name) for name in names}
    needed = [
        ('표준단어명', '영문약어명'),
        ('도메인명', '소수점길이'),
        ('표준용어명', '영문약어명(컬럼명)', '구성단어'),
        ('한글코드명', '코드값', '코드값의미'),
        ('원천표', '원천컬럼', '표준용어명', '표준영문약어명', '도메인명', '데이터타입', '데이터길이'),
        ('원천표', '원천컬럼', '원천값', '표준코드명', '표준코드값', '표준코드값의미', '신뢰도'),
    ]
    for name, fields in zip(names, needed):
        require(parsed[name][0], fields, name)

    def dictionary(rows, fields, label):
        result = {}
        for row in rows:
            k = tuple(row[x] for x in fields)
            if k in result:
                raise InputError(f'{label}: 사전 키 중복 {k}')
            result[k] = row
        return result

    words = dictionary(parsed[names[0]][1], ('표준단어명',), names[0])
    domains = dictionary(parsed[names[1]][1], ('도메인명',), names[1])
    terms = dictionary(parsed[names[2]][1], ('표준용어명',), names[2])
    codes = dictionary(parsed[names[3]][1], ('한글코드명', '코드값'), names[3])
    rows = []
    for source in parsed[names[4]][1]:
        table, column, term = source['원천표'], source['원천컬럼'], source['표준용어명']
        link = term if term else '__EXCLUDE__'
        rows.append(record('컬럼 연결', table, column, '', link))
        rows.append(record('표준용어', table, column, '',
                           {'용어명': term, '약어': source['표준영문약어명']} if term else ''))
        domain = domains.get((source['도메인명'],))
        if term and domain is None:
            raise InputError(f'생성 도메인사전에 없는 도메인: {source["도메인명"]}')
        rows.append(record('표준도메인', table, column, '',
                           {'도메인명': source['도메인명'], '타입': source['데이터타입'],
                            '길이': source['데이터길이'], '소수점길이': domain['소수점길이']} if term else ''))
        if not term:
            continue
        if (term,) not in terms:
            raise InputError(f'생성 용어사전에 없는 용어: {term}')
        termrow = terms[(term,)]
        if termrow['영문약어명(컬럼명)'] != source['표준영문약어명']:
            raise InputError(f'매핑과 용어사전의 약어가 다릅니다: {table}.{column}')
        for position, token in enumerate(termrow['구성단어'].split('+'), 1):
            if (token,) not in words:
                raise InputError(f'생성 단어사전에 없는 단어: {token}')
            rows.append(record('표준단어', table, column, str(position),
                               {'단어명': token, '약어': words[(token,)]['영문약어명']}))
    for source in parsed[names[5]][1]:
        value, group = source['표준코드값'], source['표준코드명']
        if value:
            if (group, value) not in codes:
                raise InputError(f'코드사전에 없는 확정 후보 코드: {group}/{value}')
            if codes[(group, value)]['코드값의미'] != source['표준코드값의미']:
                raise InputError(f'코드대응과 사전의 의미 충돌: {group}/{value}')
        rows.append(record('표준코드', source['원천표'], source['원천컬럼'], source['원천값'],
                           {'코드그룹': group, '코드값': value} if value else '', source['신뢰도']))
    if not rows:
        raise InputError('AI 결과 CSV에 평가할 행이 없습니다.')
    unique(rows, 'AI 결과')
    return rows, [{'name': name, 'sha256': sha(contents[name])} for name in names]


def load_gold(path):
    data = Path(path).read_bytes()
    fields, rows = read_csv_bytes(data, str(path))
    require(fields, GOLD_FIELDS, '정답 CSV')
    if not rows:
        raise InputError('정답 CSV가 비었습니다.')
    unique(rows, '정답 CSV')
    for row in rows:
        if row['정답상태'] not in ('미확정', '확정', '제외'):
            raise InputError('정답상태는 미확정·확정·제외 중 하나여야 합니다.')
        if row['독립성'] not in ('미확인', '확인', '입력노출'):
            raise InputError('독립성은 미확인·확인·입력노출 중 하나여야 합니다.')
        aliases = row['의미상허용값']
        try:
            values = json.loads(aliases) if aliases else []
        except ValueError as exc:
            raise InputError('의미상허용값은 JSON 목록이어야 합니다.') from exc
        if not isinstance(values, list) or any(not isinstance(v, (str, dict)) or not v for v in values):
            raise InputError('의미상허용값에는 빈 값 없이 문자열·객체의 목록을 넣으세요.')
        row['정답'] = canonical(row['정답'])
        validate_payload(row['평가영역'], row['정답'], '정답 CSV')
        for value in values:
            validate_payload(row['평가영역'], value, '의미상허용값')
        row['_aliases'] = [canonical(v) for v in values]
    return rows, sha(data)


def eligible(gold):
    if gold['정답상태'] == '미확정':
        return False, '정답 미확정'
    if not all(gold[x] for x in ('정답버전', '근거', '검토자')):
        return False, '정답 승인 근거 부족'
    if gold['정답상태'] == '제외':
        return False, '승인된 평가 제외'
    if not gold['정답']:
        return False, '정답값 없음'
    if gold['독립성'] != '확인':
        return False, '독립성 미확인/입력노출'
    return True, ''


def rate(numerator, denominator):
    return {'분자': numerator, '분모': denominator,
            '비율': numerator / denominator if denominator else None}


def evaluate(predictions, golds, areas=AREAS):
    predictions = [p for p in predictions if p['평가영역'] in areas]
    golds = [g for g in golds if g['평가영역'] in areas]
    if not golds:
        raise InputError('선택한 영역에 정답 평가대상이 없습니다.')
    pm, gm = unique(predictions, 'AI 결과'), unique(golds, '정답')
    details = []
    for k, g in gm.items():
        p = pm.get(k)
        predicted = p['AI결과'] if p else ''
        ok, why = eligible(g)
        judgment = '판정 불가'
        if why == '승인된 평가 제외':
            judgment = '평가 제외'
        elif ok:
            if p is None or predicted == '':
                judgment = '불일치'
            elif predicted == g['정답']:
                judgment = '정확 일치'
            elif predicted in g['_aliases']:
                judgment = '의미상 일치'
            else:
                judgment = '불일치'
        diagnostic = '대조 불가'
        if g['정답'] and p and predicted:
            diagnostic = '문자열 일치' if predicted == g['정답'] else '문자열 차이'
        details.append({**dict(zip(IDENTITY, k)), 'AI결과': predicted, '정답': g['정답'],
                        '판정': judgment, '이유': why or ('AI 행 누락' if p is None else ('AI 미결정' if predicted == '' else '')),
                        '신뢰도': p.get('신뢰도', '') if p else '', 'AI행누락': p is None,
                        'AI미결정': p is None or predicted == '', '참고대조': diagnostic})
    metrics = []
    confidence = []
    for area in areas:
        rows = [d for d in details if d['평가영역'] == area]
        if not rows:
            continue
        counts = Counter(d['판정'] for d in rows)
        exact, semantic, wrong = (counts[s] for s in ('정확 일치', '의미상 일치', '불일치'))
        comparable = exact + semantic + wrong
        pending = sum(d['AI미결정'] for d in rows)
        total = len(rows)
        metrics.append({'평가영역': area, '전체': total, '비교가능': comparable,
                        '정확일치': exact, '의미상일치': semantic, '불일치': wrong,
                        '판정불가': counts['판정 불가'], '평가제외': counts['평가 제외'],
                        'AI행누락': sum(d['AI행누락'] for d in rows), '미결정': pending,
                        '엄격일치율': rate(exact, comparable),
                        '승인기준수용률': rate(exact + semantic, comparable),
                        '오류율': rate(wrong, comparable), '평가커버리지': rate(comparable, total),
                        '미결정률': rate(pending, total),
                        '참고일치': sum(d['참고대조'] == '문자열 일치' for d in rows),
                        '참고대조가능': sum(d['참고대조'] != '대조 불가' for d in rows)})
        for level in sorted({d['신뢰도'] for d in rows}):
            subset = [d for d in rows if d['신뢰도'] == level]
            valid = [d for d in subset if d['판정'] in ('정확 일치', '의미상 일치', '불일치')]
            confidence.append({'평가영역': area, '신뢰도': level or '미제공', '전체': len(subset),
                               '비교가능': len(valid), '불일치': sum(d['판정'] == '불일치' for d in valid),
                               '오류율': rate(sum(d['판정'] == '불일치' for d in valid), len(valid))})
    extras = [p for k, p in pm.items() if k not in gm]
    return {'metrics': metrics, 'details': details, 'extras': extras, 'confidence': confidence}


def write_csv(path, fields, rows):
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def new_directory(path):
    p = Path(path)
    if p.exists() and any(p.iterdir()):
        raise InputError(f'결과 폴더가 이미 차 있습니다. 새 폴더를 지정하세요: {p}')
    p.mkdir(parents=True, exist_ok=True)
    return p


def html_report(result):
    def e(value):
        return html.escape(str(value))

    def pct(value):
        return '정답 확인 전' if value['비율'] is None else f'{value["비율"]:.1%} ({value["분자"]}/{value["분모"]})'

    rows = ''.join('<tr>' + ''.join(f'<td>{e(v)}</td>' for v in [m['평가영역'], m['전체'], m['정확일치'],
        m['의미상일치'], m['불일치'], m['판정불가'], m['평가제외'], pct(m['엄격일치율']),
        pct(m['승인기준수용률']), pct(m['평가커버리지'])]) + '</tr>' for m in result['metrics'])
    valid = sum(m['비교가능'] for m in result['metrics'])
    state = '채점에 사용할 확정 정답이 없어 성능 점수는 계산하지 않았습니다.' if not valid else '확정 정답이 있는 범위를 자동 채점했습니다. 영역별 범위를 확인하세요.'
    dataset = result.get('manifest', {}).get('dataset_id') or '원천 버전 표시 미지정'
    sample = '<p class="status">작동 확인용 가상 예제입니다. 실제 MAPS 프로젝트 성능이 아닙니다.</p>' if dataset.startswith('가상예제') else ''
    links = [('틀린항목.csv', '정답과 다른 항목'), ('확인필요.csv', '정답·검토가 더 필요한 항목'),
             ('상세결과.csv', '전체 항목의 판정'), ('신뢰도별.csv', 'high·low별 오류'), ('범위밖예측.csv', '정답지 범위 밖의 AI 결과')]
    return f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>MAPS 자동 성능평가</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;max-width:1450px;margin:40px auto;padding:0 24px;color:#253443}}h1{{font-size:28px}}table{{border-collapse:collapse;width:100%;font-size:14px}}th{{background:#294560;color:white}}th,td{{padding:12px;border-bottom:1px solid #d9e0e7;text-align:left}}.status{{padding:16px;background:#fff2cc}}a{{color:#17549c}}</style>
<h1>MAPS 자동 성능평가</h1>{sample}<p class="status">{e(state)}</p><p>평가 입력 버전: {e(dataset)}</p>
<p>AI 결과 파일과 정답 CSV를 키로 연결해 자동 채점했습니다. 정답 없는 항목은 틀린 것으로 처리하지 않습니다.</p>
<div style="overflow-x:auto"><table><tr><th>영역</th><th>대상</th><th>같음</th><th>뜻 같음</th><th>다름</th><th>판정 불가</th><th>제외</th><th>엄격 일치율</th><th>승인 기준 수용률</th><th>확인한 범위</th></tr>{rows}</table></div>
<p>‘뜻 같음’은 정답지에 미리 승인한 허용값만 인정합니다. 이번 실행에서 새로 사람이 승인했다는 뜻은 아닙니다.</p>
<p>직접 검토자가 이번 AI 출력을 승인하는 ‘검토자 수용률’은 별도 측정이 필요합니다. 위 수용률은 승인된 정답·허용값에 대한 자동 수용률입니다.</p>
<p>컬럼 연결은 선택한 표준용어의 연결 결과를, 도메인은 이름·타입·길이 명세를 비교합니다. 메타데이터 연결 타당성이나 실제 데이터 변환 품질을 대신하지 않습니다.</p>
<h2>이제 확인할 파일</h2><ul>{''.join(f'<li><a href="{name}">{label}</a></li>' for name,label in links)}</ul>
<p>평가대상 밖 예측 {len(result['extras'])}건은 분모에 섞지 않고 따로 기록했습니다. 누락된 AI 예측은 정답이 있는 경우 불일치로 셉니다.</p>
<p>기존 입력 사전과의 단순 문자열 대조는 요약 CSV의 참고대조에 별도로 기록했습니다. 독립 정확도로 해석하지 않습니다.</p></html>'''


def save_result(out, result, manifest):
    out = new_directory(out)
    result['manifest'] = manifest
    (out / '평가결과.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    flat = []
    for metric in result['metrics']:
        row = {k: v for k, v in metric.items() if not isinstance(v, dict)}
        for name, value in metric.items():
            if isinstance(value, dict):
                row.update({name + '_분자': value['분자'], name + '_분모': value['분모'],
                            name + '_비율': '' if value['비율'] is None else value['비율']})
        flat.append(row)
    write_csv(out / '요약.csv', list(flat[0]), flat)
    fields = [*IDENTITY, 'AI결과', '정답', '판정', '이유', '신뢰도', 'AI행누락', 'AI미결정', '참고대조']
    write_csv(out / '상세결과.csv', fields, result['details'])
    write_csv(out / '틀린항목.csv', fields, [d for d in result['details'] if d['판정'] == '불일치'])
    write_csv(out / '확인필요.csv', fields, [d for d in result['details'] if d['판정'] in ('판정 불가', '의미상 일치')])
    write_csv(out / '범위밖예측.csv', AI_FIELDS, result['extras'])
    write_csv(out / '신뢰도별.csv', ['평가영역', '신뢰도', '전체', '비교가능', '불일치', '오류율_분자', '오류율_분모', '오류율'],
              [{**x, '오류율_분자': x['오류율']['분자'], '오류율_분모': x['오류율']['분모'],
                '오류율': '' if x['오류율']['비율'] is None else x['오류율']['비율']} for x in result['confidence']])
    (out / '보고서.html').write_text(html_report(result), encoding='utf-8')
    return out


def prepare(ai, out, legacy=None, reference_dir=None):
    predictions, inputs = load_ai(ai)
    candidates = {}
    if legacy:
        # The prior local audit is evidence for draft candidates, never approved gold.
        source = json.loads(Path(legacy).read_text(encoding='utf-8'))
        tables = {'SALESFORCE': '세일즈포스_원천_상담_1000행', 'OUTBOUND': '아웃바운드_원천_TM상담_1000행',
                  'INBOUND': '인바운드_원천_상담_1000행', 'HOMEPAGE': '홈페이지_원천_민원_1000행', 'CHATBOT': '챗봇_원천_세션_1005건'}
        legacy_terms = {}
        for c in source['columns']:
            table, column = tables[c['system']], c['source_column']
            if c['candidate_status'] == '기존 승인 타겟·용어 연결':
                candidates[('컬럼 연결', table, column, '')] = c['legacy_term']
                # Name + abbreviation: name alone must not fabricate a complete gold label.
                legacy_terms[(table, column)] = c
                dtype = re.fullmatch(r'([A-Z0-9]+)(?:\((\d+)(?:,(\d+))?\))?', c['legacy_type'])
                if dtype:
                    candidates[('표준도메인', table, column, '')] = canonical({'도메인명': c['legacy_domain'], '타입': dtype[1], '길이': dtype[2] or '', '소수점길이': dtype[3] or ''})
        # Physical target column names are recoverable from uniquely linked legacy targets.
        for (table, column), c in legacy_terms.items():
            candidates[('표준용어', table, column, '')] = canonical({'용어명': c['legacy_term'], '약어': c['legacy_target'].split('.')[1]})
        code_group_names = {}
        old_words = {}
        old_terms = []
        if reference_dir:
            folder = Path(reference_dir)
            _, coderefs = read_csv_bytes((folder / '5.MAPS_TO-BE_표준코드사전_v1.1_최종.csv').read_bytes(), '기존 표준코드')
            for c in coderefs:
                group, name = c['CODE_GROUP_ID'], c['CODE_GROUP_NAME']
                if group in code_group_names and code_group_names[group] != name:
                    raise InputError('기존 코드그룹 이름이 중복 정의돼 있습니다.')
                code_group_names[group] = name
            _, old_terms = read_csv_bytes((folder / '3.MAPS_표준용어사전_v1.0_확정.csv').read_bytes(), '기존 표준용어')
            _, old_word_rows = read_csv_bytes((folder / '2.MAPS_표준단어사전_v1.0_확정.csv').read_bytes(), '기존 표준단어')
            for w in old_word_rows:
                if w['표준단어명'] in old_words:
                    raise InputError('기존 표준단어명이 중복됩니다.')
                old_words[w['표준단어명']] = w['표준단어약어']
        for p in predictions:
            if p['평가영역'] != '표준단어':
                continue
            c = legacy_terms.get((p['원천표'], p['원천컬럼']))
            if c is None:
                continue
            entity, column = c['legacy_target'].split('.')
            ts = [t for t in old_terms if t['표준용어영문명_물리컬럼명'] == column and entity in t['적용Entity'].split('/')]
            if len(ts) == 1:
                tokens = ts[0]['구성표준단어'].split('+')
                i = int(p['평가항목']) - 1
                if i < len(tokens) and tokens[i] in old_words:
                    candidates[key(p)] = canonical({'단어명': tokens[i], '약어': old_words[tokens[i]]})
        for c in source['codes']:
            if c['candidate_status'] == '기존 승인 코드대응':
                # Do not silently compare an old group ID to a new Korean group name.
                group_name = code_group_names.get(c['legacy_group'])
                if group_name:
                    candidates[('표준코드', tables[c['system']], c['source_column'], c['source_value'])] = canonical({'코드그룹': group_name, '코드값': c['legacy_code']})
    golds = []
    for p in predictions:
        k = key(p)
        expected = candidates.get(k, '')
        golds.append({**dict(zip(IDENTITY, k)), '정답': expected, '의미상허용값': '',
                      '정답상태': '미확정', '독립성': '미확인', '정답버전': '2차 참조 후보' if expected else '',
                      '근거': '기존 승인 매핑에서 자동 연결한 후보. 이번 평가 기준·독립성 확인 필요.' if expected else '', '검토자': ''})
    out = new_directory(out)
    write_csv(out / 'AI결과_공통형식.csv', AI_FIELDS, predictions)
    write_csv(out / '정답후보_미확정.csv', GOLD_FIELDS, golds)
    (out / '준비기록.json').write_text(json.dumps({'inputs': inputs, 'rows': len(golds), 'candidate_values': sum(bool(g['정답']) for g in golds), 'approved': 0, 'protocol': PROTOCOL}, ensure_ascii=False, indent=2), encoding='utf-8')
    return out


def word_shape(predictions):
    counts = Counter((p['원천표'], p['원천컬럼']) for p in predictions if p['평가영역'] == '표준단어')
    return sorted([list(k) + [v] for k, v in counts.items()])


def run(ai, gold, out, dataset_id='', areas=AREAS):
    predictions, inputs = load_ai(ai)
    golds, gold_hash = load_gold(gold)
    result = evaluate(predictions, golds, areas)
    manifest = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'gold_sha256': gold_hash,
                'protocol': PROTOCOL, 'protocol_sha256': sha(canonical(PROTOCOL).encode()),
                'areas': list(areas), 'dataset_id': dataset_id,
                'dataset_id_basis': 'operator-supplied input-version label; source dataset itself not loaded',
                'inputs': inputs, 'word_shape': word_shape(predictions),
                'gold_population_sha256': sha(canonical(sorted([list(key(g)) for g in golds if g['평가영역'] in areas])).encode())}
    return save_result(out, result, manifest)


def compare(before, after, out):
    def read(p):
        p = Path(p)
        return json.loads((p / '평가결과.json' if p.is_dir() else p).read_text(encoding='utf-8'))
    a, b = read(before), read(after)
    for field in ('gold_sha256', 'protocol_sha256', 'areas', 'gold_population_sha256'):
        if a['manifest'][field] != b['manifest'][field]:
            raise InputError(f'비교 조건이 다릅니다: {field}. 같은 정답·범위·평가 방법으로 다시 실행하세요.')
    if not a['manifest']['dataset_id'] or a['manifest']['dataset_id'] != b['manifest']['dataset_id']:
        raise InputError('같은 원천 입력 버전(dataset-id)을 지정해야 개선 전후를 비교할 수 있습니다.')
    if '표준단어' in a['manifest']['areas'] and a['manifest']['word_shape'] != b['manifest']['word_shape']:
        raise InputError('구성단어 분해 개수가 달라 단어 평가 단위가 바뀌었습니다. 분해 기준을 고정하거나 단어를 빼고 별도 비교하세요.')
    amap = {key(d): d for d in a['details']}
    changes = [{**dict(zip(IDENTITY, key(d))), '개선전': amap[key(d)]['판정'], '개선후': d['판정']}
               for d in b['details'] if amap[key(d)]['판정'] != d['판정']]
    metrics = []
    for left, right in zip(a['metrics'], b['metrics']):
        assert left['평가영역'] == right['평가영역']
        for name in ('엄격일치율', '승인기준수용률', '오류율', '평가커버리지', '미결정률'):
            x, y = left[name]['비율'], right[name]['비율']
            metrics.append({'평가영역': left['평가영역'], '지표': name,
                            '개선전': '' if x is None else x, '개선후': '' if y is None else y,
                            '차이': '' if x is None or y is None else y - x})
    out = new_directory(out)
    write_csv(out / '개선전후.csv', ['평가영역', '지표', '개선전', '개선후', '차이'], metrics)
    write_csv(out / '판정변화.csv', [*IDENTITY, '개선전', '개선후'], changes)
    (out / '비교조건.json').write_text(json.dumps({'checks': 'same gold, protocol, areas, keys, input-version label',
        'source_data_content_verified': False, 'dataset_id': a['manifest']['dataset_id']}, ensure_ascii=False, indent=2), encoding='utf-8')
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description='AI CSV + 정답 CSV 자동 성능평가. 새 API 호출 없음.')
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare', help='AI 파일을 공통 형식으로 바꾸고 정답 양식 생성')
    prep.add_argument('--ai', required=True)
    prep.add_argument('--out', required=True)
    prep.add_argument('--legacy-evidence', help='선택: 기존 로컬 예비 대조 evaluation.json. 후보만 채우고 승인하지 않음.')
    prep.add_argument('--reference-dir', help='선택: 기존 확정 단어·용어·코드 CSV 폴더. 단어·코드그룹 후보 생성용.')
    runner = commands.add_parser('run', help='AI 결과와 확정 정답 자동 비교')
    runner.add_argument('--ai', required=True)
    runner.add_argument('--gold', required=True)
    runner.add_argument('--out', required=True)
    runner.add_argument('--dataset-id', default='')
    runner.add_argument('--areas', default=','.join(AREAS))
    comp = commands.add_parser('compare', help='같은 조건의 실행 결과 비교')
    comp.add_argument('--before', required=True)
    comp.add_argument('--after', required=True)
    comp.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            out = prepare(args.ai, args.out, args.legacy_evidence, args.reference_dir)
        elif args.command == 'run':
            areas = tuple(x.strip() for x in args.areas.split(','))
            if not areas or len(set(areas)) != len(areas) or not set(areas) <= set(AREAS):
                raise InputError('areas에는 평가영역을 중복 없이 쉼표로 구분해 넣으세요.')
            out = run(args.ai, args.gold, args.out, args.dataset_id, areas)
        else:
            out = compare(args.before, args.after, args.out)
    except (InputError, OSError, zipfile.BadZipFile) as exc:
        print(f'실행 중단: {exc}', file=sys.stderr)
        return 2
    print(f'완료: {out.resolve()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
