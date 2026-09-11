"""KCIF topic settings for Briefing. No LLM, crawl, publish, or scheduler changes."""
from __future__ import annotations

import hashlib
import fcntl
import json
import time
from datetime import datetime, timedelta

from indepth_analysis.kcif import store
from indepth_analysis.kcif.paths import KST, LOCK_PATH


class SettingsError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def snapshot(conn=None) -> dict:
    conn = conn or store.get_conn()
    topics = []
    for row in conn.execute("SELECT * FROM kcif_topics ORDER BY id"):
        topics.append({"slug": row["slug"], "title": row["title"],
                       "description": row["description"] or "",
                       "keywords": json.loads(row["keywords_json"] or "[]"),
                       "enabled": row["status"] == "active"})
    revision = hashlib.sha256(json.dumps(topics, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {"revision": revision, "topics": topics, "active_limit": store.ACTIVE_TOPIC_CAP,
            "applies_on": "next_run"}


def save(payload: dict) -> dict:
    # The regular run holds this same lock. Do not change parameters halfway
    # through a report and describe them as applying to the next run.
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SettingsError("busy", "KCIF 정기 실행 중입니다. 완료 후 저장해 주세요.") from None
        try:
            return _save(payload)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _save(payload: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) != {"revision", "topics"}:
        raise SettingsError("malformed", "revision과 topics가 필요합니다.")
    topics = payload["topics"]
    if not isinstance(topics, list) or len(topics) > 100:
        raise SettingsError("malformed", "토픽은 최대 100개입니다.")
    clean = []
    seen = set()
    for item in topics:
        if not isinstance(item, dict) or set(item) != {"slug", "title", "description", "keywords", "enabled"}:
            raise SettingsError("malformed", "토픽 필드가 올바르지 않습니다.")
        title, description = item["title"], item["description"]
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            raise SettingsError("malformed", "토픽 제목은 1~120자입니다.")
        if not isinstance(description, str) or len(description) > 1000:
            raise SettingsError("malformed", "설명은 1,000자 이하여야 합니다.")
        keywords = item["keywords"]
        if (not isinstance(keywords, list) or not 1 <= len(keywords) <= 20 or
                any(not isinstance(k, str) or not 2 <= len(k.strip()) <= 80 for k in keywords)):
            raise SettingsError("malformed", "키워드는 2~80자 문자열 1~20개가 필요합니다.")
        if not isinstance(item["enabled"], bool) or not isinstance(item["slug"], str):
            raise SettingsError("malformed", "토픽 식별자와 사용 여부를 확인하세요.")
        slug = item["slug"] or store.slugify(title)
        if len(slug) > 160 or slug != store.slugify(slug) or slug in seen:
            raise SettingsError("malformed", "토픽 식별자가 잘못되었거나 중복되었습니다.")
        seen.add(slug)
        clean.append({**item, "slug": slug, "title": title.strip(), "description": description.strip(),
                      "keywords": list(dict.fromkeys(k.strip().lower() for k in keywords))})
    if sum(item["enabled"] for item in clean) > store.ACTIVE_TOPIC_CAP:
        raise SettingsError("malformed", f"활성 토픽은 최대 {store.ACTIVE_TOPIC_CAP}개입니다.")
    conn = store.get_conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = snapshot(conn)
        if payload["revision"] != current["revision"]:
            raise SettingsError("conflict", "다른 곳에서 설정이 바뀌었습니다. 다시 불러온 뒤 저장하세요.")
        old = {item["slug"] for item in current["topics"]}
        if not old <= seen:
            raise SettingsError("malformed", "기존 토픽을 삭제할 수 없습니다. 사용 여부를 꺼 주세요.")
        cutoff = (datetime.now(KST) - timedelta(days=90)).strftime("%Y-%m-%d")
        watermark = store.text_id_before_date(cutoff)
        for item in clean:
            status = "active" if item["enabled"] else "archived"
            values = (item["title"], item["description"], json.dumps(item["keywords"], ensure_ascii=False), status)
            if item["slug"] in old:
                conn.execute("UPDATE kcif_topics SET title=?,description=?,keywords_json=?,status=?,"
                             "archived_ts=CASE WHEN ?='active' THEN NULL ELSE COALESCE(archived_ts,?) END WHERE slug=?",
                             (*values, status, time.time(), item["slug"]))
            else:
                conn.execute("INSERT INTO kcif_topics (title,description,keywords_json,status,slug,created_ts,archived_ts,watermark_id) VALUES (?,?,?,?,?,?,?,?)",
                             (*values, item["slug"], time.time(), None if item["enabled"] else time.time(), watermark))
        result = snapshot(conn)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def run_cli(write: bool) -> int:
    import sys
    try:
        if not store.DB_PATH.is_file():
            raise SettingsError("unavailable", "KCIF 데이터베이스가 준비되지 않았습니다.")
        if write:
            raw = sys.stdin.read(65537)
            if len(raw) > 65536:
                raise SettingsError("malformed", "설정이 너무 큽니다.")
            result = save(json.loads(raw))
        else:
            result = snapshot()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (SettingsError, json.JSONDecodeError) as error:
        print(json.dumps({"error": {"code": getattr(error, "code", "malformed"),
                                    "message": str(error)}}, ensure_ascii=False))
        return 2
