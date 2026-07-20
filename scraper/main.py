"""일일 수집 오케스트레이터.

흐름:
  1. 전체 + 20개 카테고리 랭킹 수집 (결과는 state 에 캐시 — 재실행 시 재요청 안 함)
  2. 상품 중복 제거 후 상품별 리뷰 요약(리뷰수·별점) + 신규 리뷰 증분 수집
  3. data/YYYY-MM-DD/ranking.csv, reviews.csv, errors.csv 기록

장시간 실행 내구성:
  - N건마다 state 저장 → 중단 후 재실행하면 끝난 상품은 건너뜀
  - 리뷰는 수집 즉시 CSV append (죽어도 데이터 보존)
  - --deadline-minutes 도달 시 체크포인트 저장 후 정상 종료하고
    .continuation_needed 마커를 남김 (워크플로우가 자기 자신을 재실행)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import config, ranking, reviews
from .http_client import Client, FetchError
from .util import (CsvAppender, Deadline, atomic_write_json, kst_now, kst_today,
                   load_json, write_csv_atomic)

log = logging.getLogger(__name__)

RANKING_FIELDS = ["수집일자", "카테고리", "순위", "브랜드", "상품명", "상품페이지링크",
                  "정가", "혜택가", "할인율", "리뷰수", "리뷰별점",
                  "세일", "쿠폰", "증정", "오늘드림", "상품번호", "카테고리ID"]
REVIEW_FIELDS = ["수집일자", "상품번호", "리뷰ID", "작성일", "별점", "체험단여부",
                 "뱃지", "피부타입", "옵션", "리뷰본문", "도움수"]
ERROR_FIELDS = ["수집일자", "상품번호", "단계", "오류"]

CONTINUATION_MARKER = Path(".continuation_needed")
SAVE_EVERY = 20


class DailyRun:
    def __init__(self, date: str, deadline: Deadline, max_products: int | None,
                 collect_review_text: bool = True, cf_bootstrap: bool = False):
        self.date = date
        self.deadline = deadline
        self.max_products = max_products
        self.collect_review_text = collect_review_text
        self.client = Client(cf_bootstrap=cf_bootstrap)

        self.progress_path = Path(config.STATE_DIR) / "run_progress.json"
        self.cursor_path = Path(config.STATE_DIR) / "review_cursor.json"
        self.out_dir = Path(config.DATA_DIR) / date

        self.progress = load_json(self.progress_path, {})
        if self.progress.get("date") != date:
            self.progress = {"date": date, "ranking_rows": None,
                             "summaries": {}, "products_done": [], "completed": False}
        self.cursors = load_json(self.cursor_path, {})

        self.reviews_csv = CsvAppender(self.out_dir / "reviews.csv", REVIEW_FIELDS)
        self.errors_csv = CsvAppender(self.out_dir / "errors.csv", ERROR_FIELDS)
        self.stats = {"new_reviews": 0, "summary_fail": 0, "review_fail": 0}

    # ------------------------------------------------------------ state

    def save_state(self):
        atomic_write_json(self.progress_path, self.progress)
        atomic_write_json(self.cursor_path, self.cursors)

    def record_error(self, goods_no: str, stage: str, exc: Exception):
        self.errors_csv.append_rows([{
            "수집일자": self.date, "상품번호": goods_no,
            "단계": stage, "오류": str(exc)[:500],
        }])

    # ------------------------------------------------------------ phases

    def phase_ranking(self):
        if self.progress["ranking_rows"] is not None:
            log.info("ranking: cached from state (%d rows)", len(self.progress["ranking_rows"]))
            return
        rows = ranking.collect_all_rankings(self.client)
        for r in rows:
            r["수집일자"] = self.date
        self.progress["ranking_rows"] = rows
        self.save_state()
        log.info("ranking: %d rows across %d categories", len(rows),
                 len({r["카테고리ID"] for r in rows}))

    def unique_products(self) -> list[str]:
        seen, ordered = set(), []
        for r in self.progress["ranking_rows"]:
            g = r["상품번호"]
            if g not in seen:
                seen.add(g)
                ordered.append(g)
        if self.max_products:
            ordered = ordered[: self.max_products]
        return ordered

    def process_product(self, goods_no: str):
        try:
            summary = reviews.fetch_review_summary(self.client, goods_no)
        except FetchError as exc:
            self.stats["summary_fail"] += 1
            self.record_error(goods_no, "summary", exc)
            summary = {"리뷰수": None, "리뷰별점": None}
        self.progress["summaries"][goods_no] = summary

        if self.collect_review_text:
            try:
                cursor = self.cursors.get(goods_no, {})
                new_reviews, new_cursor = reviews.collect_new_reviews(
                    self.client, goods_no, cursor)
                for r in new_reviews:
                    r["수집일자"] = self.date
                    r["상품번호"] = goods_no
                self.reviews_csv.append_rows(new_reviews)
                self.cursors[goods_no] = new_cursor
                self.stats["new_reviews"] += len(new_reviews)
            except FetchError as exc:
                self.stats["review_fail"] += 1
                self.record_error(goods_no, "reviews", exc)

        self.progress["products_done"].append(goods_no)

    def phase_products(self) -> bool:
        """True = 전부 완료, False = 데드라인으로 중단."""
        products = self.unique_products()
        done = set(self.progress["products_done"])
        todo = [g for g in products if g not in done]
        log.info("products: %d unique, %d already done, %d todo",
                 len(products), len(done), len(todo))
        for i, goods_no in enumerate(todo, start=1):
            if self.deadline.reached:
                log.warning("deadline reached — checkpointing (%d/%d remaining)",
                            len(todo) - i + 1, len(todo))
                self.save_state()
                return False
            self.process_product(goods_no)
            if i % SAVE_EVERY == 0:
                self.save_state()
            if i % 100 == 0:
                log.info("progress %d/%d (requests=%d, new_reviews=%d, "
                         "deadline remaining=%.0fmin)",
                         i, len(todo), self.client.request_count,
                         self.stats["new_reviews"], self.deadline.remaining_minutes)
        self.save_state()
        return True

    def write_ranking_csv(self):
        rows = []
        for r in self.progress["ranking_rows"]:
            summary = self.progress["summaries"].get(r["상품번호"], {})
            row = dict(r)
            row["리뷰수"] = summary.get("리뷰수")
            row["리뷰별점"] = summary.get("리뷰별점")
            rows.append(row)
        write_csv_atomic(self.out_dir / "ranking.csv", RANKING_FIELDS, rows)
        log.info("wrote %s (%d rows)", self.out_dir / "ranking.csv", len(rows))

    # ------------------------------------------------------------ run

    def run(self) -> bool:
        if self.progress.get("completed"):
            log.info("today's run already completed — nothing to do")
            return True
        self.phase_ranking()
        finished = self.phase_products()
        self.write_ranking_csv()  # 데드라인 중단 시에도 부분 데이터 기록
        if finished:
            self.progress["completed"] = True
            # CSV에 이미 기록된 데이터를 state에 중복 보관하지 않는다 (커밋 크기 절감)
            self.progress["ranking_rows"] = None
            self.progress["summaries"] = {}
            self.save_state()
        self.write_summary(finished)
        return finished

    def write_summary(self, finished: bool):
        n_rank = len(self.progress["ranking_rows"] or [])
        n_done = len(self.progress["products_done"])
        summary_ok = sum(1 for s in self.progress["summaries"].values()
                         if s.get("리뷰수") is not None)
        lines = [
            f"## 올리브영 수집 결과 ({self.date})",
            f"- 상태: {'완료' if finished else '데드라인 중단 → 이어서 실행 예정'}",
            f"- 랭킹 행: {n_rank}",
            f"- 처리 상품: {n_done} (리뷰요약 성공 {summary_ok}, 실패 {self.stats['summary_fail']})",
            f"- 신규 리뷰: {self.stats['new_reviews']} (수집 실패 상품 {self.stats['review_fail']})",
            f"- 총 요청 수: {self.client.request_count}",
            f"- 종료 시각(KST): {kst_now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        text = "\n".join(lines)
        print(text)
        step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if step_summary:
            with open(step_summary, "a", encoding="utf-8") as f:
                f.write(text + "\n")


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="수집일자 (기본: KST 오늘)")
    ap.add_argument("--deadline-minutes", type=float, default=None,
                    help="이 시간이 지나면 체크포인트 저장 후 정상 종료")
    ap.add_argument("--max-products", type=int, default=None,
                    help="상품 수 제한 (스모크 테스트용)")
    ap.add_argument("--no-review-text", action="store_true",
                    help="리뷰 본문 수집 생략 (리뷰수/별점만)")
    ap.add_argument("--cf-bootstrap", action="store_true",
                    help="시작 시 브라우저로 Cloudflare 검증 쿠키 확보 (로컬 실행 권장)")
    args = ap.parse_args()

    CONTINUATION_MARKER.unlink(missing_ok=True)
    run = DailyRun(args.date or kst_today(), Deadline(args.deadline_minutes),
                   args.max_products, collect_review_text=not args.no_review_text,
                   cf_bootstrap=args.cf_bootstrap)
    try:
        finished = run.run()
    except Exception:
        # 예기치 못한 오류도 지금까지의 진행을 남긴다
        run.save_state()
        raise
    if not finished:
        CONTINUATION_MARKER.write_text("continue")
        log.info("continuation marker written")
    sys.exit(0)


if __name__ == "__main__":
    main()
