from pathlib import Path
import requests,json,hashlib
from indepth_analysis.data.mendeley_client import get_access_token,API_BASE
out=Path(__file__).parent/'source';s=requests.Session();s.headers['Authorization']='Bearer '+get_access_token()
def getpages(url,params=None):
 result=[]
 while url:
  r=s.get(url,params=params,timeout=60);r.raise_for_status();result.extend(r.json());url=r.links.get('next',{}).get('url');params=None
 return result
folders=getpages(API_BASE+'/folders',{'limit':500});fs=[x for x in folders if x.get('name','').upper()=='QUARTERLY'];assert len(fs)==1,[(x['name'],x['id']) for x in fs]
f=fs[0];docs=getpages(API_BASE+'/folders/'+f['id']+'/documents',{'limit':500});found=[]
for entry in docs:
 r=s.get(API_BASE+'/documents/'+entry['id'],params={'view':'all'},timeout=60);r.raise_for_status();d=r.json();title=d.get('title','')
 print(title,flush=True)
 if '20261006' not in title:continue
 files=getpages(API_BASE+'/files',{'document_id':d['id']})
 for file in files:
  r=s.get(API_BASE+'/files/'+file['id'],timeout=120);r.raise_for_status();assert r.content[:4]==b'%PDF'
  path=out/'20261006_사이버보안.pdf';path.write_bytes(r.content)
  found.append({'title':title,'document_id':d['id'],'folder_id':f['id'],'file_id':file['id'],'file_name':file.get('file_name'),'path':str(path),'bytes':len(r.content),'sha256':hashlib.sha256(r.content).hexdigest()})
assert len(found)==1,found
(out/'manifest.json').write_text(json.dumps(found[0],ensure_ascii=False,indent=2)+'\n');print('MATCH',json.dumps(found[0],ensure_ascii=False))
