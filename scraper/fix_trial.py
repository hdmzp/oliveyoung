"""기존에 수집한 CSV의 '체험단여부' 컬럼을 최신 규칙으로 다시 계산한다.

재수집 불필요 — CSV에 이미 있는 '리뷰타입'·'리뷰본문'으로 체험단여부를 재계산해
파일을 제자리 갱신한다. 리뷰타입 분포도 출력한다.

사용:
  python -m scraper.fix_trial                 # data 폴더의 모든 reviews/백필 CSV
  python -m scraper.fix_trial 파일1.csv ...   # 지정 파일만
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import os
import tempfile
from collections import Counter

from . import reviews


def fix_file(path: str) -> None:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print(f"  (빈 파일) {path}")
        return
    cols = rows[0].keys()
    if "체험단여부" not in cols or "리뷰타입" not in cols:
        print(f"  (대상 아님) {path}")
        return

    types = Counter(r.get("리뷰타입", "") for r in rows)
    changed = 0
    for r in rows:
        new = str(reviews.is_trial(r.get("리뷰타입", ""), r.get("리뷰본문", "")))
        if r.get("체험단여부", "") != new:
            r["체험단여부"] = new
            changed += 1
    trial_now = sum(1 for r in rows if r.get("체험단여부") == "1")

    # atomic 저장
    fieldnames = list(rows[0].keys())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
        f.write(buf.getvalue())
    os.replace(tmp, path)

    print(f"  {path}")
    print(f"    {len(rows)}행 중 {changed}행 갱신 | 체험단여부=1: {trial_now}개")
    print(f"    리뷰타입 분포: {dict(types)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="대상 CSV (없으면 data 폴더 전체)")
    args = ap.parse_args()
    paths = args.paths or sorted(set(
        glob.glob("data/*_reviews.csv")                    # 신규: data/2026-07-21_reviews.csv
        + glob.glob("data/**/reviews.csv", recursive=True)  # 구: data/2026-07-21/reviews.csv
        + glob.glob("data/backfill/*.csv")))
    if not paths:
        print("대상 CSV 를 찾지 못했습니다.")
        return
    print(f"대상 {len(paths)}개 파일:")
    for p in paths:
        fix_file(p)
    print("완료.")


if __name__ == "__main__":
    main()
