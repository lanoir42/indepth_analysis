"""Authorized two-report publication; dry-run by default, resumable and verified.
Uses the existing Notion client/parser. No model calls, server changes, or git writes.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
from dotenv import load_dotenv
from indepth_analysis.output.notion_publisher import NotionClient, markdown_to_blocks, _file_block_upload
from indepth_analysis.temporal_lint import assert_no_high

REPO = Path(__file__).resolve().parents[3]
ROOT = REPO / 'reports/ai_security_explainers_2026_09'
OUT = Path(__file__).resolve().parent
STATE = OUT / 'notion-publication.json'
FILES = ['2026-09-28_apple_pcc_technical_explainer.md', '2026-09-28_meta_muse_agent_technical_explainer.md']

def save(state):
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(STATE)

def rt(items):
    return ''.join(x.get('plain_text', x.get('text', {}).get('content', '')) for x in items)

def sig(b):
    kind = b['type']; v = b[kind]
    if kind == 'table': return [kind, v['table_width']]
    if kind == 'table_row': return [kind, [rt(c) for c in v['cells']]]
    if kind == 'file': return [kind, rt(v.get('caption', []))]
    return [kind, rt(v.get('rich_text', []))]

def children(client, block_id):
    items = []; cursor = None
    while True:
        params = {'page_size': 100}
        if cursor: params['start_cursor'] = cursor
        r = client.client.get(f'/v1/blocks/{block_id}/children', params=params)
        r.raise_for_status(); j = r.json(); items.extend(j['results'])
        if not j['has_more']: return items
        cursor = j['next_cursor']

def validate(blocks):
    def walk(x):
        if isinstance(x, dict):
            if x.get('type') == 'text': assert len(x['text']['content']) <= 2000
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(blocks)
    for b in blocks:
        if b['type'] == 'table': assert len(b['table']['children']) <= 100

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--execute', action='store_true'); args = ap.parse_args()
    material = {}; stats = []
    for name in FILES:
        p = ROOT / name; text = p.read_text(); assert_no_high(text, 2026)
        assert text.startswith('# ') and '참고문헌' in text
        assert 'TODO' not in text and 'turn2' not in text
        blocks = markdown_to_blocks(text); validate(blocks)
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        stat = {'file': name, 'sha256': sha, 'characters_including_references': len(text), 'whitespace_words': len(text.split()), 'sections': len(re.findall(r'^## ', text, re.M)), 'unique_references': len(set(re.findall(r'\]\((https?://[^)]+)\)', text))), 'notion_body_blocks': len(blocks), 'tables': sum(b['type'] == 'table' for b in blocks)}
        stats.append(stat); material[name] = (text, blocks, sha)
    (OUT / 'validation.json').write_text(json.dumps({'as_of': '2026-09-28', 'files': stats, 'temporal_high': 0, 'temporal_medium_review': 'Muse WhatsApp 2025 URL and historical reference; no claim that the separate system is Muse current protection.', 'not_executed': ['VRE or production penetration tests', 'Muse exploit', 'independent latency benchmarks', 'paid model calls']}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(stats, ensure_ascii=False, indent=2), flush=True)
    if not args.execute: return
    load_dotenv(REPO / '.env')
    parent = os.environ['NOTION_PAGE_ID_INDEPTH_ANALYSIS']
    state = json.loads(STATE.read_text()) if STATE.exists() else {'as_of': '2026-09-28', 'parent_id': parent, 'pages': {}, 'status': 'in_progress'}
    assert state['parent_id'] == parent
    client = NotionClient(os.environ['NOTION_TOKEN'])
    try:
        for name in FILES:
            text, blocks, sha = material[name]
            entry = state['pages'].get(name)
            if entry is None:
                if state.get('pending_create'): raise RuntimeError('Unresolved page creation; inspect before retry')
                state['pending_create'] = name; save(state)
                title = '20260928 ' + text.splitlines()[0][2:]
                page = client.create_page(parent, title)
                entry = state['pages'][name] = {'id': page['id'], 'url': page['url'], 'title': title, 'sha256': sha}
                state.pop('pending_create'); save(state)
                print('created', name, entry['url'], flush=True)
            assert entry['sha256'] == sha, 'Source changed after publication began'
            if 'upload_id' not in entry:
                entry['upload_id'] = client.upload_file(ROOT / name); save(state)
            expected = [_file_block_upload(entry['upload_id'], 'Download: ' + name)] + blocks
            actual = children(client, entry['id'])
            assert len(actual) <= len(expected)
            assert [sig(x) for x in actual] == [sig(x) for x in expected[:len(actual)]], 'Existing Notion content differs; do not overwrite'
            for i in range(len(actual), len(expected), 100):
                client.append_blocks(entry['id'], expected[i:i+100])
                entry['appended_through'] = min(i+100, len(expected)); save(state)
            actual = children(client, entry['id'])
            assert [sig(x) for x in actual] == [sig(x) for x in expected]
            tables = 0
            for want, got in zip(expected, actual):
                if want['type'] == 'table':
                    rows = children(client, got['id'])
                    assert [sig(x) for x in rows] == [sig(x) for x in want['table']['children']]
                    tables += 1
            entry.update(verified=True, verified_blocks=len(actual), verified_tables=tables, source_attachment=True)
            save(state); print('verified', name, len(actual), 'blocks', tables, 'tables', flush=True)
        state['status'] = 'verified'; save(state)
    finally:
        client.close()

if __name__ == '__main__':
    main()
