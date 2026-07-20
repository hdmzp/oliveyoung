"""전체 랭킹 TOP100 상품의 과거 리뷰 전량 백필 (1회성, 재개 가능).

상품×페이지 단위 커서를 저장하므로 어느 시점에 중단돼도 그 지점부터 재개된다.
GH Actions 6시간 한도는 --deadline-minutes 로 대응: 마감 도달 시 체크포인트
저장 후 정상 종료하고 .continuation_needed 마커를 남긴다 (워크플로우가 재실행).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import config, ranking, reviews
from .http_client import Client, FetchError
from .main import CONTINUATION_MARKER, REVIEW_FIELDS
from .util import CsvAppender, Deadline, atomic_write_json, kst_today, load_json

log = logging.getLogger(__name__)

MAX_PAGES_PER_PRODUCT = 5000   # 안전 상한 (페이지당 ~20건 기준 10만 리뷰)
SAVE_EVERY_PAGES = 5           # 진행위치를 디스크에 저장하는 주기(페이지)


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--deadline-minutes", type=float, default=320)
    ap.add_argument("--max-products", type=int, default=100)
    ap.add_argument("--fresh", action="store_true",
                    help="이전 진행기록을 무시하고 처음부터 새로 (완료 기록 초기화)")
    args = ap.parse_args()

    CONTINUATION_MARKER.unlink(missing_ok=True)
    deadline = Deadline(args.deadline_minutes)
    client = Client()
    cursor_path = Path(config.STATE_DIR) / "backfill_cursor.json"
    state = {} if args.fresh else load_json(cursor_path, {})
    if args.fresh:
        cursor_path.unlink(missing_ok=True)
        log.info("--fresh: 이전 백필 진행기록을 초기화합니다 (CSV는 append 되므로 필요시 직접 삭제)")

    if state.get("completed"):
        log.info("backfill already completed — nothing to do "
                 "(다시 하려면 --fresh, 그리고 data/backfill/top100_reviews.csv 삭제)")
        return

    if not state.get("order"):
        items = ranking.fetch_ranking(client, "")  # 전체 TOP100
        order = []
        for it in items[: args.max_products]:
            if it["상품번호"] not in order:
                order.append(it["상품번호"])
        state = {"order": order, "products": {}, "completed": False,
                 "started": kst_today()}
        atomic_write_json(cursor_path, state)
        log.info("backfill targets: %d products", len(order))

    out_csv = CsvAppender(Path(config.DATA_DIR) / "backfill" / "top100_reviews.csv",
                          REVIEW_FIELDS)
    total_new = 0

    try:
        for goods_no in state["order"]:
            pstate = state["products"].setdefault(
                goods_no, {"cursor_id": None, "cursor_score": None, "pages": 0, "done": False})
            if pstate["done"]:
                continue
            cid, cscore = pstate["cursor_id"], pstate["cursor_score"]
            pages = pstate["pages"]
            while pages < MAX_PAGES_PER_PRODUCT:
                if deadline.reached:
                    atomic_write_json(cursor_path, state)
                    CONTINUATION_MARKER.write_text("continue")
                    log.warning("deadline reached at %s page %d — checkpoint saved",
                                goods_no, pages)
                    sys.exit(0)
                try:
                    page_reviews, cid, cscore, has_next = reviews.fetch_review_page(
                        client, goods_no, cid, cscore)
                except FetchError as exc:
                    log.error("%s page %d failed: %s — skip product", goods_no, pages, exc)
                    break
                if not page_reviews:
                    break
                for r in page_reviews:
                    r["수집일자"] = kst_today()
                    r["상품번호"] = goods_no
                out_csv.append_rows(page_reviews)   # 리뷰는 즉시 디스크 기록(fsync)
                total_new += len(page_reviews)
                pages += 1
                # 진행위치를 메모리에 항상 반영, 디스크엔 주기적으로 저장
                pstate.update(cursor_id=cid, cursor_score=cscore, pages=pages)
                if pages % SAVE_EVERY_PAGES == 0:
                    atomic_write_json(cursor_path, state)
                if not has_next:
                    break
            pstate["done"] = True
            atomic_write_json(cursor_path, state)
            done_count = sum(1 for p in state["products"].values() if p["done"])
            log.info("product %s done (%d pages) — %d/%d products, %d reviews so far",
                     goods_no, pages, done_count, len(state["order"]), total_new)
    except KeyboardInterrupt:
        # Ctrl+C: 지금까지의 진행위치를 저장하고 깔끔히 종료 (재실행 시 이어서)
        atomic_write_json(cursor_path, state)
        log.warning("사용자 중단(Ctrl+C) — 진행상황 저장됨. 다시 실행하면 이어서 진행합니다. "
                    "(리뷰 %d건 저장됨)", total_new)
        sys.exit(0)

    state["completed"] = True
    atomic_write_json(cursor_path, state)
    log.info("backfill completed: %d reviews appended this run", total_new)


if __name__ == "__main__":
    main()
