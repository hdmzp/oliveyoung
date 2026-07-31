"""index.html 뷰어가 읽을 JSON 을 생성한다 (CSV → JSON).

- data/manifest.json          : 조회 가능한 날짜 목록 + 리뷰 있는 상품 목록
- data/ranking/{날짜}.json     : 그 날짜의 랭킹(1~100)
- data/reviews/{상품번호}.json : 그 상품의 '누적 전체' 리뷰 (모든 일자 + 백필, 중복 제거)

매일 수집 후 실행:  python -m scraper.build_site
"""
from __future__ import annotations

import csv
import glob
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path

from . import config

DATA = Path(config.DATA_DIR)


def _read(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except (FileNotFoundError, OSError):
        return []


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _ranking_files() -> dict[str, str]:
    """날짜 -> ranking csv 경로. 신규(플랫)·구(폴더) 둘 다 지원."""
    out: dict[str, str] = {}
    for p in glob.glob(str(DATA / "*_ranking.csv")):
        date = Path(p).name[:-len("_ranking.csv")]
        out[date] = p
    for p in glob.glob(str(DATA / "*" / "ranking.csv")):
        out.setdefault(Path(p).parent.name, p)
    return dict(sorted(out.items()))


def _review_files() -> list[str]:
    return (glob.glob(str(DATA / "*_reviews.csv"))
            + glob.glob(str(DATA / "*" / "reviews.csv"))
            + glob.glob(str(DATA / "backfill" / "*.csv")))


def main():
    ranks = _ranking_files()
    dates = list(ranks.keys())

    # 날짜별 랭킹 JSON
    for date, path in ranks.items():
        _write_json(DATA / "ranking" / f"{date}.json", _read(path))

    # 상품별 누적 리뷰 JSON (모든 일자 + 백필, 리뷰ID 로 중복 제거)
    by_goods: dict[str, dict[str, dict]] = defaultdict(dict)
    for rf in _review_files():
        for r in _read(rf):
            g, rid = r.get("상품번호"), r.get("리뷰ID")
            if g and rid:
                by_goods[g][rid] = r
    for g, revmap in by_goods.items():
        revs = sorted(revmap.values(), key=lambda x: x.get("작성일", ""), reverse=True)
        _write_json(DATA / "reviews" / f"{g}.json", revs)

    _write_json(DATA / "manifest.json", {
        "dates": dates,
        "goodsWithReviews": sorted(by_goods.keys()),
        "reviewCount": sum(len(v) for v in by_goods.values()),
    })
    print(f"site build 완료: 날짜 {len(dates)}개, 리뷰 상품 {len(by_goods)}개, "
          f"총 리뷰 {sum(len(v) for v in by_goods.values())}개")


if __name__ == "__main__":
    main()
