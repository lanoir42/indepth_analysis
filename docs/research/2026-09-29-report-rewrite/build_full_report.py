"""Assemble the reader edition without summarizing or changing chapter content."""
from pathlib import Path
import re,json,hashlib
repo=Path(__file__).resolve().parents[3]
root=repo/'reports/indepth_analysis_2026_09_29'
files=sorted(root.glob('[0-9][0-9]-*.md'))
assert len(files)==10
names=['경영진 종합 보고서']+[f'{i}장. '+f.read_text().splitlines()[0].split('. ',1)[1] for i,f in enumerate(files[1:9],1)]+['부록 A. 기술·계산 해설서','부록 B. 참고문헌']
full='# 프론티어 AI와 안전·보안 산업 — 풀리포트 (2026-09-29)\n\n정보 기준일 2026-09-29\n\n경영진 종합 보고서, 본편 8장, 기술·계산 해설서와 참고문헌을 한 문서에서 이어 읽는 통합본입니다.\n\n## 목차\n\n'+'\n'.join('- '+n for n in names)+'\n\n'
manifest=[]
for i,f in enumerate(files+[root/'REFERENCES.md']):
 raw=f.read_text(); lines=raw.splitlines(); body='\n'.join(lines[1:]).strip()
 # A single chapter/date header is sufficient for the integrated edition.
 body=re.sub(r'^정보 기준일[^\n]*\n\n','',body)
 body=re.sub(r'^정보 확인일[^\n]*\n\n','',body)
 if f.name=='REFERENCES.md':
  body=re.sub(r'\[([^\]]+)\]\(([0-9][0-9]-[^)]+\.md)\)',lambda m:'종합 보고서' if m[1]=='00' else m[1],body)
 body=re.sub(r'^(#{2,5}) ',lambda m:'#'+m[1]+' ',body,flags=re.M)
 part='## '+names[i]+'\n\n'+body+'\n'
 full+=part+'\n---\n\n'
 manifest.append({'file':f.name,'sha256':hashlib.sha256(raw.encode()).hexdigest(),'assembled_section_sha256':hashlib.sha256(part.encode()).hexdigest(),'included':part in full})
assert len(re.findall(r'^# ',full,re.M))==1
assert len(set(re.findall(r'\]\((https?://[^)]+)\)',full)))==50
assert not re.search(r'\]\((?!https?://)[^)]+\)',full)
(root/'FULL-REPORT.md').write_text(full)
Path(__file__).with_name('full-report-assembly.json').write_text(json.dumps({'sources':manifest,'output':'FULL-REPORT.md','characters':len(full),'sha256':hashlib.sha256(full.encode()).hexdigest(),'assembly':'Full source bodies preserved; headings/date preambles and reference chapter labels normalized.'},ensure_ascii=False,indent=2)+'\n')
f=root/'README.md';t=f.read_text();marker='## 읽는 순서\n'
t=t if '## 풀리포트 한 파일로 읽기' in t else t.replace(marker,'## 풀리포트 한 파일로 읽기\n\n**[풀리포트 — 요약·본편 8장·해설서·참고문헌](FULL-REPORT.md)**을 기본 읽기 문서로 사용합니다. 아래 분할본은 장별 참조용입니다. 통합본은 기존 본문을 모두 포함하며 별도 추가 연구 분량으로 중복 집계하지 않습니다.\n\n'+marker)
f.write_text(t)
print({'chars':len(full),'source_documents':len(manifest),'external_sources':50})
