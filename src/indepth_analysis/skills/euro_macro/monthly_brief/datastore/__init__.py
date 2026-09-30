"""v3 결정론 데이터 계층 — 시계열 레지스트리·수집기·저장소.

- ``registry``: 계열 선언(SeriesSpec)·웹 계열 매핑·ECB 결정일 표
- ``eurostat`` / ``ecb`` / ``market`` / ``web_series``: 소스별 수집기
- ``store``: ``ROOT/data/series_store.json`` 빌더(캐시·오프라인 재실행) + 기간 유틸
"""
