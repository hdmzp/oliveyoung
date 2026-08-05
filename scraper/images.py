"""대표이미지 다운로드 (URL 기준 중복 제거, 재개 안전).

- 파일명 = URL 의 md5 앞 16자 + 확장자 → 같은 URL(=같은 이미지)은 한 번만 저장
- 이미 디스크에 있으면 건너뜀 → 매일 100장이 아니라 '새로 등장한 이미지'만 받음
- 프로모 이미지가 바뀌면 URL 도 바뀌므로 변경분은 자동으로 새 파일로 보존됨
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

_ALLOWED_EXT = {"jpg", "jpeg", "png", "gif", "webp"}


def filename_for(url: str) -> str:
    """URL → 로컬 파일명(중복 제거 키). 분석 시 CSV의 URL로 동일하게 역산 가능."""
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
    tail = url.split("?")[0].rsplit(".", 1)
    ext = tail[1].lower() if len(tail) == 2 else ""
    if ext not in _ALLOWED_EXT:
        ext = "jpg"
    return f"{h}.{ext}"


def download_new_images(client, rows, deadline=None, out_dir: str | None = None) -> dict:
    """랭킹 rows 의 대표이미지URL 중 아직 저장 안 된 것만 다운로드."""
    out = Path(out_dir or config.IMAGE_DIR)
    out.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    got = cached = failed = 0
    for r in rows:
        url = (r.get("대표이미지URL") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        dest = out / filename_for(url)
        if dest.exists():
            cached += 1
            continue
        if deadline is not None and deadline.reached:
            log.warning("deadline reached in image download — %d개 남기고 중단", 0)
            break
        try:
            resp = client.get(url, referer=config.BEST_LIST_URL)
            data = resp.content
            if not data or len(data) < 100:
                raise ValueError(f"빈/손상 응답 ({len(data)}B)")
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(dest)
            got += 1
        except Exception as exc:  # 이미지 1장 실패가 전체를 막지 않게
            failed += 1
            log.warning("image download 실패 %s: %s", url, str(exc)[:120])
    log.info("images: 신규 %d, 캐시(스킵) %d, 실패 %d — 총 고유 %d",
             got, cached, failed, len(seen))
    return {"new": got, "cached": cached, "failed": failed, "unique": len(seen)}
