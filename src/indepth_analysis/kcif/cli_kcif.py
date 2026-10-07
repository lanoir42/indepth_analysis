"""`indepth kcif` 서브커맨드 — argparse 배선 (cli.py 침습 최소화).

    indepth kcif daily [--date D] [--skip-crawl] [--force]  # 평일 18:00 KST launchd 잡 본체
    indepth kcif find "질의" [옵션]                 # 로컬 아카이브 FTS 검색
    indepth kcif extract-backfill [--limit N]      # 기존 PDF → .md 일괄 추출
    indepth kcif topics add|list|show|run|resummarize|archive|unarchive|delete|seed
    indepth kcif schedule install|uninstall|status # launchd 잡 관리
"""

from __future__ import annotations

import json


def register_kcif_parser(subparsers) -> None:
    p = subparsers.add_parser("kcif", help="KCIF 팔로업 (일일 크롤·토픽 타임라인·검색)")
    sub = p.add_subparsers(dest="kcif_cmd", required=True)
    settings = sub.add_parser("settings", help="리포트 토픽 설정 JSON 조회/저장 (생성 실행 없음)")
    settings.add_argument("--write", action="store_true", help="stdin의 revision/topics를 저장")

    d = sub.add_parser("daily", help="일일 파이프라인: 크롤→추출→토픽→리포트 (18:00 KST 잡)")
    d.add_argument("--date", default=None, help="대상 날짜 YYYY-MM-DD (기본: 오늘 KST)")
    d.add_argument("--skip-crawl", action="store_true", help="크롤/다운로드/추출 스킵 (토픽·리포트만)")
    d.add_argument("--force", action="store_true",
                   help="주말·휴일(신규 0건) 판정을 무시하고 리포트를 만든다")

    f = sub.add_parser("find", help="로컬 KCIF 아카이브 전문 검색 (FTS5, 오프라인)")
    f.add_argument("query")
    f.add_argument("--since", default=None, help="발행일 시작 YYYY-MM-DD")
    f.add_argument("--until", default=None, help="발행일 끝 (미포함)")
    f.add_argument("--category", default=None, help="카테고리 부분일치 (예: 국제금융속보)")
    f.add_argument("-n", "--limit", type=int, default=20)

    e = sub.add_parser("extract-backfill", help="다운로드된 PDF 전체 → 텍스트 원본 .md 백필")
    e.add_argument("--limit", type=int, default=None)

    retry = sub.add_parser(
        "public-backfill", help="공개 전환 재확인·본문 백필 (LLM·보고서 생성 없음)",
    )
    retry.add_argument("--limit", type=int, default=10, help="1~117건, 기본 10건")

    t = sub.add_parser("topics", help="토픽 타임라인 관리")
    tsub = t.add_subparsers(dest="topics_cmd", required=True)
    ta = tsub.add_parser("add", help="토픽 등록 (+키워드 자동 확장)")
    ta.add_argument("title")
    ta.add_argument("--desc", default=None)
    ta.add_argument("-k", "--keyword", action="append", default=[])
    tsub.add_parser("list", help="토픽 목록")
    ts = tsub.add_parser("show", help="토픽 상세 (요약+타임라인+근거)")
    ts.add_argument("slug")
    tsub.add_parser("run", help="전 활성 토픽 증분 업데이트 1회")
    tsub.add_parser("resummarize",
                    help="전 활성 토픽의 '현재 상황'을 기존 타임라인으로 재생성 "
                         "(요약 프롬프트를 바꾼 뒤 소급 적용용)")
    tsub.add_parser("seed", help="시드 토픽 6개 등록 (기존 것은 스킵)")
    for name in ("archive", "unarchive", "delete"):
        tp = tsub.add_parser(name)
        tp.add_argument("slug")

    s = sub.add_parser("schedule", help="launchd 평일 18:00 KST 잡 관리")
    s.add_argument("schedule_cmd", choices=["install", "uninstall", "status"])


def run_kcif(args) -> int:
    from indepth_analysis.kcif import store

    if args.kcif_cmd == "settings":
        from indepth_analysis.kcif.settings import run_cli
        return run_cli(args.write)

    if args.kcif_cmd == "daily":
        from indepth_analysis.kcif.report import run_daily
        res = run_daily(args.date, skip_crawl=args.skip_crawl,
                        force=getattr(args, "force", False))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.kcif_cmd == "public-backfill":
        from indepth_analysis.kcif.download_retry import run_public_backfill
        result = run_public_backfill(limit=args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["stopped"] else 0

    if args.kcif_cmd == "find":
        rows = store.search_texts(args.query, since=args.since, until=args.until,
                                  category=args.category, limit=args.limit)
        if not rows:
            print("검색 결과 없음")
            return 0
        from indepth_analysis.kcif.paths import PROJECT_ROOT
        print(f"검색 결과 {len(rows)}건:\n")
        for r in rows:
            print(f"  [{r.get('category') or '?'}] {r.get('published_date') or '?'} — {r['title']}")
            if r.get("md_path"):
                print(f"  {PROJECT_ROOT / r['md_path']}")
        return 0

    if args.kcif_cmd == "extract-backfill":
        from indepth_analysis.data.kcif_client import KCIFScraper
        from indepth_analysis.db import ReferenceDB
        from indepth_analysis.kcif.extract_md import backfill_all
        from indepth_analysis.kcif.paths import PROJECT_ROOT
        db = ReferenceDB(db_path=PROJECT_ROOT / "references" / "references.db")
        source = db.get_or_create_source(KCIFScraper.source_name, KCIFScraper.base_url)
        res = backfill_all(db, source.id, limit=args.limit)
        print(f"추출 완료: 성공 {res['ok']} / 실패 {res['fail']} / 대상 {res['total']}")
        return 0

    if args.kcif_cmd == "topics":
        from indepth_analysis.kcif import topics as topics_mod
        cmd = args.topics_cmd
        if cmd == "add":
            t = topics_mod.register_topic(args.title, args.desc, args.keyword)
            print(f"등록: {t['slug']} — 키워드: {', '.join(t['keywords'])}")
        elif cmd == "list":
            for t in store.list_topics():
                ev = store.evidence_stats(t["slug"])
                print(f"  [{t['status']}] {t['title']} ({t['slug']}) — 근거 {ev['total']}건")
        elif cmd == "show":
            t = store.get_topic(args.slug)
            if not t:
                print("없는 토픽")
                return 1
            print(f"# {t['title']} ({t['slug']})")
            print(f"키워드: {', '.join(t.get('keywords') or [])}")
            print(f"\n{t.get('summary_text') or '(요약 대기)'}\n")
            for e in store.timeline(args.slug):
                print(f"  {e['event_date']} — {e['headline']}")
        elif cmd == "run":
            for r in topics_mod.update_all():
                print(f"  {r['slug']}: {r['reason']} (+이벤트 {r['events_added']}, "
                      f"+근거 {r['evidence_added']})")
        elif cmd == "resummarize":
            for r in topics_mod.resummarize_all():
                print(f"  {r['slug']}: {'재생성' if r['ok'] else '실패(기존 유지)'} "
                      f"({r['chars']}자)")
        elif cmd == "seed":
            added = topics_mod.seed_topics()
            print(f"시드 등록: {', '.join(added) if added else '(전부 이미 존재)'}")
        elif cmd == "archive":
            store.set_status(args.slug, "archived")
            print("아카이브됨")
        elif cmd == "unarchive":
            store.set_status(args.slug, "active")
            print("활성화됨")
        elif cmd == "delete":
            print("삭제됨" if store.delete_topic(args.slug) else "없는 토픽")
        return 0

    if args.kcif_cmd == "schedule":
        from indepth_analysis.kcif import schedule
        if args.schedule_cmd == "install":
            print(f"설치됨: {schedule.install()} (평일 월~금 18:00 KST)")
        elif args.schedule_cmd == "uninstall":
            print("제거됨" if schedule.uninstall() else "미설치 상태")
        else:
            print(schedule.status())
        return 0
    return 1
