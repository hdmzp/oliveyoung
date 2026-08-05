"""랭킹 크로스섹션 분석용 상품 단위 데이터셋 생성.

data/*_ranking.csv + data/*_reviews.csv + data/backfill/top100_reviews.csv 를 합쳐
스냅샷 날짜 기준 상품 1행짜리 feature 테이블을 만든다.

- 리뷰는 (상품번호, 리뷰ID) 기준으로 dedupe (일별 파일 간 중복 재수집이 많음)
- 저장된 체험단여부 컬럼은 수집 시기별 규칙이 달라 신뢰할 수 없으므로
  본문 키워드 기준으로 재계산한다 (PLAN.md §1, §4)
- 리뷰 유입 속도는 3가지 proxy: velocity_delta(일별 총리뷰수 증가분),
  velocity_span(최신 k건이 걸린 일수), recent30/90_share (PLAN.md §3)
  단, 리뷰 목록 API가 도움순 고정 반환이라 velocity_span/recent*_share는
  편향된 참고 지표이며 velocity_delta만 신뢰 가능 (PLAN.md §3 실측 참고)

사용:  python -m analysis.build_dataset [--date YYYY-MM-DD]
출력:  analysis/output/dataset_<date>.csv
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

try:
    sys.path.insert(0, ROOT)
    from scraper.config import TRIAL_KEYWORDS
except Exception:
    TRIAL_KEYWORDS = ("체험단", "무상으로 제공", "무상 제공", "제공받아", "제공 받아",
                      "협찬", "서포터즈", "무료로 제공")

SPAN_K = 30  # velocity_span에 쓰는 최신 리뷰 건수
MIN_REVIEWS_FOR_SPAN = 10


def load_rankings() -> pd.DataFrame:
    frames = []
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "*_ranking.csv"))):
        df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
        frames.append(df)
    # 07-21/22 파일엔 대표이미지URL 컬럼이 없음 → concat이 NaN으로 채움
    rank = pd.concat(frames, ignore_index=True)
    for col in ["순위", "정가", "혜택가", "리뷰수",
                "별점5비율", "별점4비율", "별점3비율", "별점2비율", "별점1비율",
                "세일", "쿠폰", "증정", "오늘드림"]:
        rank[col] = pd.to_numeric(rank[col], errors="coerce")
    rank["할인율"] = pd.to_numeric(rank["할인율"], errors="coerce")
    rank["리뷰별점"] = pd.to_numeric(rank["리뷰별점"], errors="coerce")
    rank["수집일자"] = pd.to_datetime(rank["수집일자"])
    return rank


def load_reviews() -> pd.DataFrame:
    paths = sorted(glob.glob(os.path.join(DATA_DIR, "*_reviews.csv")))
    backfill = os.path.join(DATA_DIR, "backfill", "top100_reviews.csv")
    if os.path.exists(backfill):
        paths.append(backfill)
    frames = [pd.read_csv(p, encoding="utf-8-sig", dtype=str) for p in paths]
    rv = pd.concat(frames, ignore_index=True)
    rv["수집일자"] = pd.to_datetime(rv["수집일자"], errors="coerce")
    rv = (rv.sort_values("수집일자")
            .drop_duplicates(subset=["상품번호", "리뷰ID"], keep="last"))
    rv["작성일"] = pd.to_datetime(rv["작성일"].str.strip(), format="%Y.%m.%d",
                                errors="coerce")
    rv["별점"] = pd.to_numeric(rv["별점"], errors="coerce")
    for col in ["포토여부", "재구매"]:
        rv[col] = pd.to_numeric(rv[col], errors="coerce")

    # 저장된 체험단여부는 무시하고 본문 키워드로 재계산
    body = rv["리뷰본문"].fillna("")
    pattern = "|".join(re.escape(k) for k in TRIAL_KEYWORDS)
    rv["is_trial"] = body.str.contains(pattern, regex=True).astype(int)
    return rv


def velocity_delta(rank_all: pd.DataFrame, snapshot: pd.Timestamp) -> pd.Series:
    """연속 등장 날짜쌍의 (리뷰수 증가분 / 경과일) 평균. 스냅샷 이후 데이터는 제외."""
    hist = rank_all[rank_all["수집일자"] <= snapshot]
    hist = hist.dropna(subset=["리뷰수"]).sort_values("수집일자")
    out = {}
    for goods, g in hist.groupby("상품번호"):
        if len(g) < 2:
            continue
        days = g["수집일자"].diff().dt.days.iloc[1:]
        delta = g["리뷰수"].diff().iloc[1:]
        rates = (delta / days).replace([np.inf, -np.inf], np.nan).dropna()
        if len(rates):
            out[goods] = rates.mean()
    return pd.Series(out, name="velocity_delta")


def review_features(rv: pd.DataFrame, snapshot: pd.Timestamp) -> pd.DataFrame:
    rv = rv[rv["작성일"] <= snapshot]
    rows = []
    for goods, g in rv.groupby("상품번호"):
        n = len(g)
        dated = g.dropna(subset=["작성일"]).sort_values("작성일", ascending=False)
        feat = {
            "상품번호": goods,
            "sampled_n": n,
            "trial_share": g["is_trial"].mean(),
            "offline_share": (g["리뷰타입"] == "OFFLINE").mean(),
            "gift_share": (g["리뷰타입"] == "GIFT").mean(),
            "photo_share": g["포토여부"].mean(),
            "repurchase_share": g["재구매"].mean(),
            "sampled_avg_rating": g["별점"].mean(),
        }
        if len(dated):
            age = (snapshot - dated["작성일"]).dt.days
            feat["recent30_share"] = (age <= 30).mean()
            feat["recent90_share"] = (age <= 90).mean()
            k = min(SPAN_K, len(dated))
            if len(dated) >= MIN_REVIEWS_FOR_SPAN:
                span = (snapshot - dated["작성일"].iloc[k - 1]).days
                feat["velocity_span"] = k / max(span, 1)
        rows.append(feat)
    return pd.DataFrame(rows)


def build(snapshot_str: str | None) -> str:
    rank_all = load_rankings()
    snapshot = (pd.Timestamp(snapshot_str) if snapshot_str
                else rank_all["수집일자"].max())
    snap = rank_all[rank_all["수집일자"] == snapshot].copy()
    if snap.empty:
        raise SystemExit(f"랭킹 데이터에 {snapshot.date()} 스냅샷이 없습니다.")

    rv = load_reviews()
    feats = review_features(rv[rv["상품번호"].isin(snap["상품번호"])], snapshot)
    vdelta = velocity_delta(rank_all, snapshot)

    df = snap.merge(feats, on="상품번호", how="left")
    df = df.merge(vdelta, left_on="상품번호", right_index=True, how="left")

    df["log_review_cnt"] = np.log10(1 + df["리뷰수"])
    df["avg_rating"] = df["리뷰별점"]
    df["star5_share"] = df["별점5비율"]
    df["star1_share"] = df["별점1비율"]
    df["log_price"] = np.log10(df["혜택가"].clip(lower=1))
    n = len(df)
    df["rank_pct"] = (n - df["순위"]) / max(n - 1, 1)
    # 일일 성장률: 리뷰수 규모와의 공선성을 피한 상대 속도 (PLAN.md §5-4)
    df["growth_rate"] = df["velocity_delta"] / df["리뷰수"].clip(lower=1)

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"dataset_{snapshot.date()}.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print(f"스냅샷 {snapshot.date()}: 상품 {n}개")
    print(f"  리뷰 feature 결합: {df['sampled_n'].notna().sum()}개 "
          f"(유니크 리뷰 {int(df['sampled_n'].sum())}건)")
    print(f"  velocity_delta 계산 가능: {df['velocity_delta'].notna().sum()}개")
    print(f"  velocity_span 계산 가능: {df['velocity_span'].notna().sum()}개")
    print(f"  체험단(키워드) 리뷰 보유 상품: {(df['trial_share'] > 0).sum()}개")
    print(f"저장: {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="스냅샷 날짜 YYYY-MM-DD (기본: 최신)")
    args = ap.parse_args()
    build(args.date)


if __name__ == "__main__":
    main()
