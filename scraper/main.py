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

from . import config, images, ranking, reviews
from .http_client import Client, FetchError
from .util import (CsvAppender, Deadline, atomic_write_json, kst_now, kst_today,
                   load_json, write_csv_atomic)

log = logging.getLogger(__name__)

RANKING_FIELDS = ["수집일자", "카테고리", "순위", "브랜드", "상품명", "상품페이지링크",
                  "대표이미지URL",
                  "정가", "혜택가", "할인율", "리뷰수", "리뷰별점",
                  "별점5비율", "별점4비율", "별점3비율", "별점2비율", "별점1비율",
                  "세일", "쿠폰", "증정", "오늘드림", "상품번호", "카테고리ID"]
REVIEW_FIELDS = ["수집일자", "상품번호", "리뷰ID", "작성일", "별점", "체험단여부",
                 "리뷰타입", "옵션", "피부타입", "피부톤", "피부고민",
                 "도움수", "유용점수", "포토여부", "재구매", "닉네임", "리뷰본문"]
ERROR_FIELDS = ["수집일자", "상품번호", "단계", "오류"]

CONTINUATION_MARKER = Path(".continuation_needed")
SAVE_EVERY = 20


class DailyRun:
    def __init__(self, date: str, deadline: Deadline, max_products: int | None,
                 collect_review_text: bool = True, overall_only: bool = False,
                 collect_images: bool = True, review_text_overall_only: bool = False):
        self.date = date
        self.deadline = deadline
        self.max_products = max_products
        self.collect_review_text = collect_review_text
        # review_text_overall_only: 전 카테고리 랭킹+리뷰수/별점(stats)은 수집하되,
        # 무거운 리뷰 본문(cursor)은 전체 TOP100 상품만 — 카테고리 확장 시 실행시간 억제
        self.review_text_overall_only = review_text_overall_only
        self.collect_images = collect_images
        # overall_only: 전체 랭킹(TOP100)만 수집 → www 요청 1건, 429 회피 + 가벼움
        self.categories = {"": "전체"} if overall_only else dict(config.CATEGORIES)
        self.client = Client()

        self.progress_path = Path(config.STATE_DIR) / "run_progress.json"
        self.cursor_path = Path(config.STATE_DIR) / "review_cursor.json"
        # data/2026-07-21_ranking.csv 형태 (한 폴더에 날짜 접두사 → 병합 용이)
        self.data_dir = Path(config.DATA_DIR)

        self.progress = load_json(self.progress_path, {})
        if self.progress.get("date") != date:
            self.progress = {"date": date, "ranking_cats": {}, "ranking_rows": None,
                             "summaries": {}, "products_done": [], "completed": False}
        self.progress.setdefault("ranking_cats", {})
        self.cursors = load_json(self.cursor_path, {})

        self.reviews_csv = CsvAppender(self.data_dir / f"{date}_reviews.csv", REVIEW_FIELDS)
        self.errors_csv = CsvAppender(self.data_dir / f"{date}_errors.csv", ERROR_FIELDS)
        self.stats = {"new_reviews": 0, "summary_fail": 0, "review_fail": 0}
        self.rate_limited = False  # 랭킹 단계에서 rate limit 으로 중단됐는지

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

    def phase_ranking(self) -> bool:
        """카테고리별로 즉시 저장하며 수집. 이미 받은 카테고리는 건너뜀(재개).

        반환: True=전체 완료, False=중단(데드라인/rate limit — 재실행 시 이어서).
        """
        done = self.progress["ranking_cats"]  # cat_id -> items (수집완료)
        total = len(self.categories)
        consecutive_fail = 0
        for cat_id, cat_name in self.categories.items():
            if cat_id in done:
                continue
            if self.deadline.reached:
                log.warning("deadline reached in ranking — checkpoint")
                self.save_state()
                return False
            try:
                items = ranking.fetch_ranking(self.client, cat_id)
                if not items:
                    raise ValueError("0 items parsed")
                for r in items:
                    r["수집일자"] = self.date
                done[cat_id] = items
                self.save_state()  # 카테고리 하나 성공할 때마다 즉시 저장
                consecutive_fail = 0
                log.info("ranking [%s] %d items (%d/%d 카테고리 완료)",
                         cat_name, len(items), len(done), total)
            except Exception as exc:
                consecutive_fail += 1
                self.record_error(cat_id, "ranking", exc)
                log.error("ranking [%s] 실패: %s", cat_name, exc)
                if consecutive_fail >= config.RANKING_ABORT_AFTER_FAILS:
                    log.error("연속 %d개 카테고리 실패 (rate limit 추정) — 랭킹 중단. "
                              "%d/%d 완료. 10~30분 후 다시 실행하면 이어서 진행합니다.",
                              consecutive_fail, len(done), total)
                    self.rate_limited = True
                    self.save_state()
                    return False
        # 전체 카테고리 완료 → ranking_rows 구성
        self.progress["ranking_rows"] = [r for items in done.values() for r in items]
        self.save_state()
        log.info("ranking 완료: %d rows / %d 카테고리",
                 len(self.progress["ranking_rows"]), total)
        return True

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
            summary = reviews.fetch_product_stats(self.client, goods_no)
        except (FetchError, ValueError) as exc:
            self.stats["summary_fail"] += 1
            self.record_error(goods_no, "stats", exc)
            summary = {"리뷰수": None, "리뷰별점": None}
        self.progress["summaries"][goods_no] = summary

        collect_text = self.collect_review_text and (
            not self.review_text_overall_only or goods_no in self._overall_goods)
        if collect_text:
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
        self._overall_goods = {r["상품번호"] for r in self.progress["ranking_rows"]
                               if r.get("카테고리ID") == "ALL"}
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
            if i % 20 == 0 or i == len(todo):
                log.info("진행 %d/%d (요청 %d회, 신규리뷰 %d개)",
                         i, len(todo), self.client.request_count,
                         self.stats["new_reviews"])
        self.save_state()
        return True

    def phase_images(self):
        """대표이미지 다운로드(중복 제거). 실패해도 수집 전체엔 영향 없음."""
        if not self.collect_images:
            return
        rows = self.progress.get("ranking_rows") or []
        if not rows:
            return
        try:
            images.download_new_images(self.client, rows, deadline=self.deadline)
        except Exception as exc:
            log.error("이미지 단계 실패(무시하고 계속): %s", exc)

    def write_ranking_csv(self):
        rows = []
        for r in self.progress["ranking_rows"]:
            summary = self.progress["summaries"].get(r["상품번호"], {})
            row = dict(r)
            row.update(summary)  # 리뷰수·리뷰별점·별점분포 병합
            rows.append(row)
        path = self.data_dir / f"{self.date}_ranking.csv"
        write_csv_atomic(path, RANKING_FIELDS, rows)
        log.info("wrote %s (%d rows)", path, len(rows))

    # ------------------------------------------------------------ run

    def run(self) -> bool:
        if self.progress.get("completed"):
            log.info("today's run already completed — nothing to do")
            return True
        ranking_ok = self.phase_ranking()
        if not ranking_ok:
            # 랭킹이 미완료(데드라인/rate limit)면 상품 단계로 넘어가지 않는다.
            self.write_summary(False)
            return False
        try:
            finished = self.phase_products()
        finally:
            # 상품 단계가 중간에 죽어도(파일잠금 등) 지금까지의 랭킹은 저장
            try:
                self.write_ranking_csv()
            except Exception as exc:
                log.error("ranking.csv 저장 실패: %s", exc)
            self.phase_images()  # 대표이미지 다운로드(중복 제거)
        if finished:
            self.progress["completed"] = True
            # CSV에 이미 기록된 데이터를 state에 중복 보관하지 않는다 (커밋 크기 절감)
            self.progress["ranking_rows"] = None
            self.progress["summaries"] = {}
            self.progress["ranking_cats"] = {}
            self.save_state()
        self.write_summary(finished)
        return finished

    def write_summary(self, finished: bool):
        cats_done = len(self.progress.get("ranking_cats") or {})
        n_rank = len(self.progress["ranking_rows"] or
                     [r for items in (self.progress.get("ranking_cats") or {}).values()
                      for r in items])
        n_done = len(self.progress["products_done"])
        summary_ok = sum(1 for s in self.progress["summaries"].values()
                         if s.get("리뷰수") is not None)
        if finished:
            status = "완료"
        elif self.rate_limited:
            status = "rate limit 중단 → 10~30분 후 다시 실행 (이어서 진행)"
        else:
            status = "데드라인 중단 → 이어서 실행 예정"
        lines = [
            f"## 올리브영 수집 결과 ({self.date})",
            f"- 상태: {status}",
            f"- 랭킹 카테고리: {cats_done}/{len(self.categories)} 완료",
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
    ap.add_argument("--overall-only", action="store_true",
                    help="전체 랭킹(TOP100)만 수집 — 카테고리별 랭킹 생략 (빠르고 가벼움)")
    ap.add_argument("--no-images", action="store_true",
                    help="대표이미지 다운로드 생략 (URL 은 그래도 CSV에 기록됨)")
    ap.add_argument("--review-text-overall-only", action="store_true",
                    help="리뷰 본문은 전체 TOP100 상품만 수집 — 카테고리 상품은 "
                         "랭킹+리뷰수/별점(stats)만. 전 카테고리 일일 수집을 "
                         "1~2시간 안으로 유지하는 권장 모드")
    args = ap.parse_args()

    CONTINUATION_MARKER.unlink(missing_ok=True)
    run = DailyRun(args.date or kst_today(), Deadline(args.deadline_minutes),
                   args.max_products, collect_review_text=not args.no_review_text,
                   overall_only=args.overall_only, collect_images=not args.no_images,
                   review_text_overall_only=args.review_text_overall_only)
    try:
        finished = run.run()
    except Exception:
        # 예기치 못한 오류도 지금까지의 진행을 남긴다
        run.save_state()
        raise
    if not finished and not run.rate_limited:
        # 데드라인 중단만 즉시 이어서 실행 (rate limit 은 즉시 재실행하면 더 막히므로 제외)
        CONTINUATION_MARKER.write_text("continue")
        log.info("continuation marker written")
    sys.exit(0)


if __name__ == "__main__":
    main()
