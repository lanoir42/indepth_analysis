"""User-authorized two-report publication with attachments and read-back."""
import runpy,json,os,re,hashlib,sys
from pathlib import Path
from dotenv import load_dotenv
from indepth_analysis.output.notion_publisher import NotionClient,markdown_to_blocks,_file_block_upload
from indepth_analysis.temporal_lint import assert_no_high
repo=Path(__file__).resolve().parents[3]; out=Path(__file__).parent
helpers=runpy.run_path(str(repo/'docs/research/2026-09-28-pcc-muse/publish.py'))
children,sig,validate=(helpers[k] for k in ['children','sig','validate'])
root=repo/'reports/nvidia_agent_safety_2026_09'; names=['TECHNICAL-REPORT.md','LECTURE-NOTES.md']; sp=out/'notion-publication.json'
def save():
 tmp=sp.with_suffix('.tmp');tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');tmp.replace(sp)
texts={n:(root/n).read_text() for n in names}
for t in texts.values():assert_no_high(t,2026);validate(markdown_to_blocks(t))
if '--execute' not in sys.argv:
 print('dry-run PASS', {n:len(markdown_to_blocks(t)) for n,t in texts.items()});sys.exit()
load_dotenv(repo/'.env');parent=os.environ['NOTION_PAGE_ID_INDEPTH_ANALYSIS']; c=NotionClient(os.environ['NOTION_TOKEN'])
state=json.loads(sp.read_text()) if sp.exists() else {'parent_id':parent,'pages':{},'status':'in_progress'}
assert state['parent_id']==parent
try:
 c.client.get('/v1/pages/'+parent).raise_for_status()
 for n,t in texts.items():
  sha=hashlib.sha256(t.encode()).hexdigest()
  if n not in state['pages']:
   assert not state.get('pending_create'),'Inspect ambiguous previous create before retry'
   state['pending_create']=n;save(); p=c.create_page(parent,'20260929 '+t.splitlines()[0][2:]);state['pages'][n]={'id':p['id'],'url':p['url'],'sha256':sha};state.pop('pending_create');save()
  assert state['pages'][n]['sha256']==sha
 old=json.loads((repo/'docs/research/2026-09-28-pcc-muse/notion-publication.json').read_text())['pages']
 def link(m):
  label,u=m.groups()
  if u.startswith(('http://','https://')):return m.group(0)
  name=Path(u).name
  if name in state['pages']:return '['+label+']('+state['pages'][name]['url']+')'
  if name in old:return '['+label+']('+old[name]['url']+')'
  if 'frontier_ai_security' in u:return '['+label+'](https://app.notion.com/p/3e9294e2c0788136b5c5c063c05b2c61)'
  raise ValueError('Unmapped relative link '+u)
 for n,t in texts.items():
  e=state['pages'][n]; rendered=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',link,t);blocks=markdown_to_blocks(rendered);validate(blocks)
  if 'upload_id' not in e:e['upload_id']=c.upload_file(root/n);save()
  expected=[_file_block_upload(e['upload_id'],'Download: '+n)]+blocks;actual=children(c,e['id'])
  assert [sig(x) for x in actual]==[sig(x) for x in expected[:len(actual)]]
  assert len(actual)<=len(expected)
  for i in range(len(actual),len(expected),100):c.append_blocks(e['id'],expected[i:i+100]);save()
  actual=children(c,e['id']);assert [sig(x) for x in actual]==[sig(x) for x in expected]
  for a,b in zip(expected,actual):
   if a['type']=='table':assert [sig(x) for x in a['table']['children']]==[sig(x) for x in children(c,b['id'])]
  e.update(verified=True,blocks=len(actual),tables=sum(x['type']=='table' for x in actual));save();print(n,e['url'],e['blocks'],flush=True)
 state['status']='verified';save()
finally:c.close()
