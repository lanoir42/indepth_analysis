"""KCIF 팔로업 서브시스템 — 일일 크롤·텍스트 원본 .md·토픽 타임라인·리포트.

orchestrator 저널과의 계약: 산출 리포트는 ``reports/kcif/``(저널 라벨
``indepth_analysis/kcif``, mtime 스캔)로, 원본 .md·토픽 덤프는 스캔 밖인
``references/KCIF_md/``로 나눠 떨어뜨린다.
"""
