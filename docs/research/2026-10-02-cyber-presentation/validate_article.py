from pathlib import Path
import hashlib,json,re
from indepth_analysis.temporal_lint import assert_no_high,scan_temporal_issues,render_report
out=Path(__file__).resolve().parent;repo=out.parents[2]
f=repo/'reports/cyber_presentation_2026_10_06/FULL-ARTICLE.md';t=f.read_text()
assert_no_high(t,2026);findings=scan_temporal_issues(t,2026)
(out/'temporal.txt').write_text(render_report(findings,2026))
n=json.loads((out/'NUMBERS.json').read_text())
rows=n['scenario_matrix']['rows']
for k,v in n['scenario_matrix']['counts'].items():assert sum(r[k] for r in rows)==v
assert round(57679.7/116550.3*100,1)==49.5
assert round(57679.7/214953.7*100,2)==26.83
assert round(58.2+26.9-41.1-27.5,1)==16.5
assert not [k for k in range(520) if round(k/519*100,1)==14.7]
assert 100*(1-(60-30))==-2900
assert round(9/(9+99990*.001)*100,2)==8.26
assert round((1-.05**.01)*100,2)==2.95
ids=re.findall(r'^### ([TM]\d\d)\.',t,re.M)
assert len(ids)==len(set(ids))==34
assert t.count('```')%2==0
refs={}
for label,url in re.findall(r'\[([^\]\n]+)\]\((https?://[^)\s]+)\)',t):refs.setdefault(url,label)
assert len(refs)==40
speeches=[re.search(r'“(.*?)”',x,re.S).group(1) for x in t.split('**발표 원고**')[1:]]
assert len(speeches)==16
manifest=json.loads((out/'source/manifest.json').read_text())
assert hashlib.sha256(Path(manifest['path']).read_bytes()).hexdigest()==manifest['sha256']
result={'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'characters':len(t),'source_pages':19,'speech_sections':16,'speech_characters':sum(map(len,speeches)),'qa_count':len(ids),'unique_references':len(refs),'tables':sum(x.startswith('|---') for x in t.splitlines()),'temporal_lint':{s:sum(x.severity==s for x in findings) for s in ['high','medium','low']},'arithmetic':'passed; source-data availability remains qualified in article','source_pdf_unchanged':True,'actual_rehearsal':False,'product_performance_testing':False,'investment_workbook_validated':False}
(out/'VALIDATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
(out/'SOURCES.json').write_text(json.dumps([{'title':v,'url':k} for k,v in refs.items()],ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
