"""Publish the authorized 2026-09-28 report. Dry run by default; resumable read-back.
Uses the repository Notion client/parser, with temporal gate and source attachments.
Never prints credentials. No CLI inference, messages, server changes, or public sharing.
"""
from pathlib import Path
import argparse,hashlib,json,re,zipfile
from dotenv import load_dotenv
import os
from indepth_analysis.output.notion_publisher import NotionClient,markdown_to_blocks,_file_block_upload
from indepth_analysis.temporal_lint import assert_no_high
REPO=Path(__file__).resolve().parents[4]
ROOT=REPO/'reports/frontier_ai_security_2026_09_28'
OUT=Path(__file__).resolve().parent
STATE=ROOT/'evidence/publication-manifest.json'
GROUPS={
 '01':('01 경영진 판단·사건·능력·AI Safety',['EXECUTIVE-BRIEF.md','P01-INCIDENTS.md','P02-CAPABILITY.md','P03-SAFETY.md']),
 '02':('02 보안 아키텍처·방어 자동화·렉처노트',['P04-SECURITY-FOR-AI.md','P05-AI-FOR-SECURITY.md','LECTURE-01-TRUST-BOUNDARIES.md','LECTURE-02-FROM-CAPABILITY-TO-VALUE.md','LECTURE-03-LEGACY-AND-DECISIONS.md']),
 '03':('03 전문가 논쟁·국가와 시민사회',['P06-EXPERT-DEBATE.md','P07-POLICY-RESPONSE.md']),
 '04':('04 기업 관계·경제성·금융투자·시나리오',['P08-COMPANY-RELATIONSHIPS.md','P09-ECONOMICS-FINANCIAL-VIEWS.md','P10-SCENARIOS-PLAYBOOK.md']),
 '05':('05 경영진 문답·용어·장표 구성',['MANAGEMENT-QA.md','GLOSSARY.md','SLIDE-OUTLINE.md']),
 '06':('06 출처 원장·검증과 조사 범위',['SOURCES.md','VALIDATION.md']),
}

def text_for(key,links):
    if key=='index':
        s=(ROOT/'README.md').read_text()
        s+='\n\n## Notion 분권 열람\n\n'+'\n\n'.join(f'[{title}]({links[k]})' for k,(title,_) in GROUPS.items())+'\n'
    else:
        title,files=GROUPS[key]
        s=f'# {title}\n\n정보 기준일: 2026-09-28 · v1.0\n\n'
        s+='\n\n---\n\n'.join((ROOT/n).read_text() for n in files)
    mapping={'README.md':links['index'],'READING-COPY.md':links['index']}
    for k,(_,files) in GROUPS.items():
        for n in files: mapping[n]=links[k]
    def convert(m):
        label,url=m.groups()
        if url.startswith(('https://','http://')): return m.group()
        return f'[{label}]({mapping[url]})' if url in mapping else label
    s=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',convert,s)
    assert_no_high(s,2026)
    return s

def richtext(xs):
    return ''.join(x.get('plain_text',x.get('text',{}).get('content','')) for x in xs)

def sig(b):
    typ=b['type']; obj=b.get(typ,{})
    if typ=='table': return ['table',obj['table_width']]
    if typ=='table_row': return ['table_row',[richtext(c) for c in obj['cells']]]
    if typ=='file': return ['file',richtext(obj.get('caption',[]))]
    if typ=='divider': return ['divider']
    return [typ,richtext(obj.get('rich_text',[]))]

def children(client,pid):
    rows=[]; cursor=None
    while True:
        p={'page_size':100}
        if cursor:p['start_cursor']=cursor
        response=client.client.get(f'/v1/blocks/{pid}/children',params=p)
        response.raise_for_status(); body=response.json(); rows+=body['results']
        if not body['has_more']:return rows
        cursor=body['next_cursor']

def save(state):
    tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');tmp.replace(STATE)

def preflight(blocks):
    def walk(x):
        if isinstance(x,dict):
            if x.get('type')=='text': assert len(x['text']['content'])<=2000
            for v in x.values():walk(v)
        elif isinstance(x,list):
            for v in x:walk(v)
    walk(blocks)
    for b in blocks:
        if b['type']=='table':assert len(b['table']['children'])<=100


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    dummy={k:f'https://www.notion.so/{k}' for k in ['index',*GROUPS]}
    for k in dummy:
        b=markdown_to_blocks(text_for(k,dummy));preflight(b)
        print('preflight',k,len(b),'blocks',flush=True)
    if not args.execute:return
    load_dotenv(REPO/'.env')
    token=os.environ['NOTION_TOKEN'];parent=os.environ['NOTION_PAGE_ID_INDEPTH_ANALYSIS']
    state=json.loads(STATE.read_text()) if STATE.exists() else {'as_of':'2026-09-28','authorized_scope':'User requested final Markdown and Notion publication','parent_id':parent,'pages':{},'status':'in_progress'}
    assert state['parent_id']==parent
    client=NotionClient(token)
    try:
        for k in ['index',*GROUPS]:
            if k in state['pages']:continue
            if state.get('pending_create'):raise RuntimeError('Unresolved create; inspect Notion before retry')
            state['pending_create']=k;save(state)
            title='20260928 프론티어 AI·보안·금융투자 연구보고서 v1.0' if k=='index' else GROUPS[k][0]
            p=client.create_page(parent if k=='index' else state['pages']['index']['id'],title)
            state['pages'][k]={'id':p['id'],'url':p['url'],'title':title}
            state.pop('pending_create');save(state)
            print('created',k,p['url'],flush=True)
        links={k:p['url'] for k,p in state['pages'].items()}
        (OUT/'volumes').mkdir(exist_ok=True)
        archive=ROOT/'frontier-ai-security-20260928-md.zip'
        if not archive.exists():
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
                for p in sorted(ROOT.rglob('*')):
                    if p.is_file() and p.suffix in ('.md','.json','.py','.txt') and p!=STATE:
                        z.write(p,p.relative_to(ROOT))
        # Children first, then index so landing page points to verified content.
        for k in [*GROUPS,'index']:
            p=state['pages'][k]
            s=text_for(k,links);local=OUT/'volumes'/f'{k}.md';local.write_text(s)
            digest=hashlib.sha256(s.encode()).hexdigest()
            if p.get('source_sha256') and p['source_sha256']!=digest:raise RuntimeError('Published source changed; explicit update needed')
            p['source_sha256']=digest;save(state)
            attachments=[local]+([archive] if k=='index' else [])
            blocks=[]
            for att in attachments:
                p.setdefault('uploads',{})
                if att.name not in p['uploads']:
                    uid=client.upload_file(att)
                    p['uploads'][att.name]={'id':uid,'sha256':hashlib.sha256(att.read_bytes()).hexdigest()};save(state)
                blocks.append(_file_block_upload(p['uploads'][att.name]['id'],f'Download: {att.name}'))
            blocks+=markdown_to_blocks(s);preflight(blocks)
            existing=[x for x in children(client,p['id']) if x['type']!='child_page']
            assert len(existing)<=len(blocks),(k,'unexpected extra blocks')
            assert [sig(b) for b in existing]==[sig(b) for b in blocks[:len(existing)]],(k,'remote content mismatch')
            for i in range(len(existing),len(blocks),50):
                p['pending_append']={'offset':i,'count':len(blocks[i:i+50])};save(state)
                client.append_blocks(p['id'],blocks[i:i+50])
                p.pop('pending_append');p['appended']=min(i+50,len(blocks));save(state)
            actual=[x for x in children(client,p['id']) if x['type']!='child_page']
            assert [sig(b) for b in actual]==[sig(b) for b in blocks],(k,'readback differs')
            tables=0
            for a,b in zip(actual,blocks):
                if b['type']=='table':
                    assert [sig(x) for x in children(client,a['id'])]==[sig(x) for x in b['table']['children']],(k,'table differs')
                    tables+=1
            p['verified']={'top_level_blocks':len(actual),'tables':tables,'attachments':len(attachments),'text_and_table_cells_match':True}
            save(state);print('verified',k,len(actual),'blocks',tables,'tables',flush=True)
        state['status']='published_and_readback_verified';save(state)
        print('DONE',links['index'],flush=True)
    finally:client.close()

if __name__=='__main__':main()
