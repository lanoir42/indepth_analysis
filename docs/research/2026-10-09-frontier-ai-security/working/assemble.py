"""Build a local reading copy without publishing or counting duplicate text."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
files = [ROOT / 'EXECUTIVE-BRIEF.md']
files += sorted(ROOT.glob('P[0-9][0-9]-*.md'))
files += sorted(ROOT.glob('LECTURE-*.md'))
header = '''# 프론티어 AI·보안·금융투자 — 중간 연구 통합 열람본

기준일: 2026-09-28. **제출용 최종본이 아닙니다.** 파트별 원문을 묶은 읽기용 사본입니다.
통계에는 중복 산출물로 제외합니다. 출처 열람 범위·미확인 항목은 각 장과 원장에 보존합니다.
원본 변경 후 이 디렉토리의 `assemble.py`를 실행해 다시 만듭니다. 외부 발행은 수행하지 않습니다.

'''
contents = '\n'.join(f'- [{f.read_text().splitlines()[0].lstrip("# ")}]({f.name})' for f in files)
body = '\n\n---\n\n'.join(f.read_text().rstrip() for f in files)
target = ROOT / 'READING-COPY.md'
target.write_text(header + contents + '\n\n---\n\n' + body + '\n')
print(f'{target.name}: {len(files)} source manuscripts; duplicate excluded from statistics')
