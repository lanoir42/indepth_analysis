from pathlib import Path
from dotenv import dotenv_values
import httpx,json,hashlib
root=Path('/Users/lanoir42/projects'); out=root/'indepth_analysis/docs/research/2026-10-02-cyber-presentation';file=root/'indepth_analysis/reports/cyber_presentation_2026_10_06/FULL-ARTICLE.md'
token=dotenv_values(root/'orchestrator/.env')['BRIEFING_SERVER_TOKEN']
with httpx.Client(base_url='http://127.0.0.1:8012',headers={'Authorization':'Bearer '+token},timeout=60,trust_env=False) as c:
 r=c.get('/finder/ls',params={'project':'indepth_analysis','path':'cyber_presentation_2026_10_06'}); print('finder',r.status_code);r.raise_for_status();j=r.json()
 matches=[x for x in j.get('files',[]) if x['name']=='FULL-ARTICLE.md']; print('matches',matches)
 if not matches: print('listing keys',list(j));raise SystemExit(1)
 item=matches[0]; doc=item['doc_id'];r=c.get('/reports/'+doc);r.raise_for_status();body=r.json();print('body keys',list(body))
 local=file.read_text();field=next((k for k,v in body.items() if v==local),None)
 r=c.get('/journal/today');r.raise_for_status();journal=r.json()
 hits=[]
 def find(x,path=''):
  if isinstance(x,dict):
   if x.get('doc_id')==doc:hits.append({'section':path,'item':x})
   for k,v in x.items():find(v,path+'/'+k)
  elif isinstance(x,list):
   for i,v in enumerate(x):find(v,path+'/'+str(i))
 find(journal)
 result={'doc_id':doc,'finder_openable':item.get('openable'),'body_matches':field is not None,'body_field':field,'journal_date':journal.get('date'),'journal_matches':hits,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'device_ui_tested':False}
 (out/'briefing-publication.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
 if not field:print({k:len(v) for k,v in body.items() if isinstance(v,str)})
