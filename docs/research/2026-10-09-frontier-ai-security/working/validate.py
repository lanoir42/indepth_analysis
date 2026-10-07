"""Offline integrity/calculation checks; does not verify external claims or publish."""
import json
import math
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AS_OF = date(2026, 9, 28)


def read(name):
    return json.loads((ROOT / 'evidence' / f'{name}.json').read_text())


def main():
    sources = read('sources')
    ids = {s['source_id'] for s in sources}
    assert len(ids) == len(sources), 'duplicate source ID'
    assert len({s['url'] for s in sources}) == len(sources), 'duplicate source URL'
    for s in sources:
        assert s['url'].startswith('https://')
        for key in ('published_date', 'updated_date', 'accessed_date'):
            if s[key]:
                assert date.fromisoformat(s[key]) <= AS_OF, (s['source_id'], key)
    for ledger, key in [('claims', 'claim_id'), ('incidents', 'incident_id'), ('views', 'view_id'),
                        ('relationships', 'relationship_id'), ('scenarios', 'scenario_id')]:
        rows = read(ledger)
        assert len({r[key] for r in rows}) == len(rows)
        for row in rows:
            for field in ('support_source_ids', 'contradiction_source_ids', 'source_ids'):
                assert set(row.get(field, [])) <= ids
            for field in ('before_source', 'after_source'):
                if field in row:
                    assert row[field] in ids
            if 'announced_or_verified_date' in row:
                assert date.fromisoformat(row['announced_or_verified_date']) <= AS_OF
    assert len({c['id'] for c in read('calculations')}) == len(read('calculations'))
    for c in read('calculations'):
        if c.get('provenance') == 'synthetic_illustration':
            assert c['source_id'] is None
        else:
            assert c['source_id'] in ids
        if c['formula'] == 'numerator / denominator * 100':
            value = c['numerator'] / c['denominator'] * 100
        elif c['formula'] == 'numerator / denominator':
            value = c['numerator'] / c['denominator']
        elif c['formula'] == '(new / old - 1) * 100':
            value = (c['new'] / c['old'] - 1) * 100
        elif c['formula'] == 'new - old':
            value = c['new'] - c['old']
        elif c['formula'] == 'tp / (tp + fp) * 100':
            value = c['tp'] / (c['tp'] + c['fp']) * 100
        elif c['formula'] == '(arrival - service) * days':
            value = (c['arrival'] - c['service']) * c['days']
        else:
            raise AssertionError(c['formula'])
        assert math.isclose(value, c['value'], rel_tol=1e-10)
    manuscript_files = sorted(ROOT.glob('P[0-9][0-9]-*.md')) + sorted(ROOT.glob('LECTURE-*.md'))
    manuscript_files += [ROOT / 'EXECUTIVE-BRIEF.md'] if (ROOT / 'EXECUTIVE-BRIEF.md').exists() else []
    stats = []
    for f in manuscript_files:
        text = f.read_text()
        assert set(re.findall(r'\bS\d{2}\b', text)) <= ids, f.name
        for dest in re.findall(r'\]\(([^)]+)\)', text):
            if not dest.startswith(('https://', 'http://', '#')):
                assert (f.parent / dest.split('#')[0]).exists(), (f.name, dest)
        stats.append({'file': f.name, 'characters_including_spaces_and_markup': len(text),
                      'lines': len(text.splitlines()), 'words_whitespace_split': len(text.split()),
                      'headings': len(re.findall(r'^#{1,6} ', text, re.M))})
    result = {
        'as_of': str(AS_OF), 'checks': 'PASS: references/dates/calculations/local_links',
        'limitations': '출처 내용의 진실성·인과·재현 검증이나 최종 출하 승인 아님. 문자수는 URL·표·마크다운 포함.',
        'manuscripts': stats,
        'total_manuscript_characters': sum(x['characters_including_spaces_and_markup'] for x in stats),
        'source_documents': len(sources), 'claim_records': len(read('claims')),
        'incident_records_not_independent_event_count': len(read('incidents')),
        'view_records': len(read('views')),
        'verified_view_change_pairs': sum('before_source' in v and 'after_source' in v for v in read('views')),
        'relationships': len(read('relationships')),
        'scenarios': len(read('scenarios')), 'calculations': len(read('calculations')),
        'excluded_from_manuscript_count': ['RESEARCH-PLAN.md', 'README.md', 'evidence/*', 'handoff', 'READING-COPY.md', 'HTML/PDF duplicates'],
    }
    (ROOT / 'evidence' / 'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
