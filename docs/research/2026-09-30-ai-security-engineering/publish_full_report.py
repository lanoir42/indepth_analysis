"""User-authorized new Notion full-report page; resumable, no old-page updates."""
from pathlib import Path
import sys,os,json,hashlib,runpy
from dotenv import load_dotenv
from indepth_analysis.output.notion_publisher import NotionClient,markdown_to_blocks,_file_block_upload
from indepth_analysis.temporal_lint import assert_no_high
repo=Path(__file__).resolve().parents[3]; out=Path(__file__).parent
h=runpy.run_path(str(repo/'docs/research/2026-09-28-pcc-muse/publish.py'))
children,sig,validate=(h[x] for x in ('children','sig','validate'))
f=repo/'reports/ai_security_engineering_2026_09_30/FULL-REPORT.md'
t=f.read_text(); review=json.loads((out/'VALIDATION.json').read_text()); assert hashlib.sha256(t.encode()).hexdigest()==review['sha256']; assert review['temporal_lint']['high']==2
# Two historical-experiment false positives reviewed in REVIEW.md; permitted by CLAUDE.md.
rendered=t.replace('../indepth_analysis_2026_09_29/FULL-REPORT.md','https://app.notion.com/p/20260929-AI-3ea294e2c07881ccb902ec326d8e54b0')
blocks=markdown_to_blocks(rendered);validate(blocks)
print({'dry_run_blocks':len(blocks),'tables':sum(b['type']=='table' for b in blocks)},flush=True)
if '--execute' not in sys.argv:sys.exit()
load_dotenv(repo/'.env');parent=os.environ['NOTION_PAGE_ID_INDEPTH_ANALYSIS'];c=NotionClient(os.environ['NOTION_TOKEN'])
sp=out/'notion-full-report-publication.json';sha=hashlib.sha256(t.encode()).hexdigest()
state=json.loads(sp.read_text()) if sp.exists() else {'parent_id':parent,'source_sha256':sha,'status':'in_progress'}
def save():
 tmp=sp.with_suffix('.tmp');tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');tmp.replace(sp)
assert state['source_sha256']==sha and state['parent_id']==parent
try:
 c.client.get('/v1/pages/'+parent).raise_for_status()
 if 'id' not in state:
  assert not state.get('pending_create'),'Inspect unresolved page creation before retry'
  state['pending_create']=True;save()
  p=c.create_page(parent,'20260930 AI 에이전트 보안의 과학과 공학 — 풀리포트')
  state.update(id=p['id'],url=p['url']);state.pop('pending_create');save()
  print('Created',state['url'],flush=True)
 if 'upload_id' not in state:state['upload_id']=c.upload_file(f);save()
 expected=[_file_block_upload(state['upload_id'],'Download: FULL-REPORT.md'),{'object':'block','type':'table_of_contents','table_of_contents':{'color':'default'}}]+blocks
 actual=children(c,state['id'])
 assert len(actual)<=len(expected)
 assert [sig(x) for x in actual]==[sig(x) for x in expected[:len(actual)]]
 for i in range(len(actual),len(expected),100):
  c.append_blocks(state['id'],expected[i:i+100]);state['appended_through']=min(i+100,len(expected));save()
  print('Appended',state['appended_through'],'/',len(expected),flush=True)
 actual=children(c,state['id']);assert [sig(x) for x in actual]==[sig(x) for x in expected]
 for a,b in zip(expected,actual):
  if a['type']=='table':assert [sig(x) for x in a['table']['children']]==[sig(x) for x in children(c,b['id'])]
 state.update(status='verified',blocks=len(actual),tables=sum(x['type']=='table' for x in actual),attachment=True,table_of_contents=True);save()
 print(json.dumps(state,ensure_ascii=False),flush=True)
finally:c.close()
