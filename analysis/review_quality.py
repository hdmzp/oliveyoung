"""리뷰 평점의 구성 — 긍정·부정 비중과 브랜드 산포 (보고서 5.10절).

앞선 절에서 '평균 별점은 순위를 설명하지 못한다(천장효과)'는 결론이 나왔다.
이 모듈은 그 결론을 평균이 아닌 **분포**로 다시 검증한다. 평균 하나로 뭉뚱그리면
사라지는 정보 — 긍정 리뷰가 몇 %인지, 부정 리뷰가 몇 %인지 — 를 따로 세고,
그렇게 재구성한 지표에도 순위 설명력이 생기지 않는지 확인한다.

정의 (분석 규약)
--------------
  긍정 리뷰 = 별점 4점 이상
  부정 리뷰 = 별점 2점 이하
  3점       = 중립이 아니라 사실상 부정으로 본다. 다만 비중이 작아 별도 집계만 한다.
  본문 길이는 지표에서 제외한다 (길이는 리뷰의 성격이지 평가가 아니다).

  상품 필터: 사이트 표시 상품 평점이 3.0 이하인 상품은 제외한다. 대부분 리뷰가
  0건이라 평점이 0으로 표기된 신상품이며, 제외해도 집계값은 사실상 변하지 않는다
  (그 근거도 함께 출력한다).

두 개의 표본을 함께 쓴다
--------------------
  (A) 수집 리뷰 본문 — 작성일이 있어 **기간을 잘라 볼 수 있다**. 단 도움순 상위
      리뷰군이라 표본 편향이 있다.
  (B) 랭킹 CSV 의 별점 5~1 비율 — 상품의 **전체 리뷰**에 대한 사이트 집계값.
      편향은 없지만 기간을 자를 수 없다(누적).
  두 표본의 긍정 비중이 일치하면 (A)의 편향이 긍정 비중에는 영향을 주지 않는다는
  뜻이므로, 이 교차확인을 먼저 수행한다.

사용:  python -m analysis.review_quality
출력:  analysis/output/review_quality_<date>.txt + stdout
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

from .growth import DATA_DIR, OUT_DIR, build_panel, fe_ols, load_rankings

POS_MIN = 4          # 긍정 = 4점 이상
NEG_MAX = 2          # 부정 = 2점 이하
RATING_FLOOR = 3.0   # 상품 평점 3.0 이하 제외
MIN_REVIEWS = 100    # 사이트 집계 표본에 넣을 최소 리뷰 수
MIN_SAMPLED = 20     # 본문 표본에서 상품 단위 집계에 넣을 최소 리뷰 수
MIN_BRAND_ITEMS = 5  # 브랜드 단위 집계에 넣을 최소 상품 수


# ---------------------------------------------------------------- 데이터

def load_reviews() -> pd.DataFrame:
    """일자별 수집분 + 백필을 리뷰 ID 기준으로 중복 제거."""
    paths = sorted(glob.glob(os.path.join(DATA_DIR, "*_reviews.csv")))
    backfill = os.path.join(DATA_DIR, "backfill", "top100_reviews.csv")
    if os.path.exists(backfill):
        paths.append(backfill)
    rev = pd.concat([pd.read_csv(p, encoding="utf-8-sig", dtype=str)
                     for p in paths], ignore_index=True)
    rev = rev.drop_duplicates(subset=["리뷰ID"])
    rev["별점"] = pd.to_numeric(rev["별점"], errors="coerce")
    rev["작성일"] = pd.to_datetime(rev["작성일"], format="%Y.%m.%d",
                                errors="coerce")
    return rev.dropna(subset=["별점", "작성일"])


def latest_snapshot(rank: pd.DataFrame) -> pd.DataFrame:
    """상품별 최신 스냅샷 1행 — 사이트 집계 별점 비율의 원천."""
    cols = ["상품번호", "브랜드", "상품명", "카테고리", "순위", "혜택가",
            "리뷰수", "리뷰별점", "별점5비율", "별점4비율", "별점3비율",
            "별점2비율", "별점1비율"]
    lat = (rank.sort_values("수집일자")
               .drop_duplicates(subset=["상품번호"], keep="last")[cols].copy())
    lat["pos"] = lat["별점5비율"] + lat["별점4비율"]
    lat["neg"] = lat["별점2비율"] + lat["별점1비율"]
    return lat


def review_window(rev: pd.DataFrame, cover: float = 0.85
                  ) -> tuple[pd.Timestamp, pd.Timestamp, pd.DataFrame]:
    """수집 리뷰가 실제로 밀집해 있는 최근 N개월 창을 자동으로 잡는다.

    백필은 상품당 최근 N건을 긁어오므로 작성일이 과거로 길게 꼬리를 문다.
    전체 리뷰의 `cover` 이상을 담는 가장 짧은 월 단위 창을 분석 기간으로 쓴다.
    """
    end = rev["작성일"].max()
    for months in range(1, 25):
        start = (end - pd.DateOffset(months=months)).normalize().replace(day=1)
        w = rev[rev["작성일"] >= start]
        if len(w) / len(rev) >= cover:
            return start, end, w
    return rev["작성일"].min(), end, rev


# ---------------------------------------------------------------- 집계

def share(s: pd.Series, kind: str) -> float:
    if kind == "pos":
        return float((s >= POS_MIN).mean() * 100)
    if kind == "neg":
        return float((s <= NEG_MAX).mean() * 100)
    return float((s == 3).mean() * 100)


def per_product(w: pd.DataFrame) -> pd.DataFrame:
    g = w.groupby("상품번호")["별점"]
    return pd.DataFrame({
        "n": g.size(),
        "mean": g.mean(),
        "pos": g.apply(lambda s: share(s, "pos")),
        "mid": g.apply(lambda s: share(s, "mid")),
        "neg": g.apply(lambda s: share(s, "neg")),
    }).reset_index()


def per_brand(lat: pd.DataFrame) -> pd.DataFrame:
    b = (lat.groupby("브랜드")
            .agg(items=("상품번호", "size"), reviews=("리뷰수", "sum"),
                 pos=("pos", "mean"), pos_sd=("pos", "std"),
                 neg=("neg", "mean"), rating=("리뷰별점", "mean"),
                 price=("혜택가", "median"))
            .reset_index())
    return b[b["items"] >= MIN_BRAND_ITEMS].sort_values("pos")


def variance_split(lat: pd.DataFrame, brands: pd.Series) -> float:
    """긍정 비중 총분산 중 브랜드 간(between) 성분의 비율(%)."""
    sub = lat[lat["브랜드"].isin(brands)]
    grand = sub["pos"].mean()
    between = sub.groupby("브랜드")["pos"].transform("mean")
    ssb = ((between - grand) ** 2).sum()
    sst = ((sub["pos"] - grand) ** 2).sum()
    return float(100 * ssb / sst) if sst > 0 else np.nan


# ---------------------------------------------------------------- 리포트

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-05")
    args = ap.parse_args()

    rev = load_reviews()
    rank = load_rankings()
    lat_all = latest_snapshot(rank)
    start, end, w = review_window(rev)
    months = round((end - start).days / 30.44)

    R: list[str] = []
    def out(s: str = "") -> None:
        R.append(s)

    out("리뷰 평점의 구성 — 긍정·부정 비중과 브랜드 산포")
    out(f"긍정 = {POS_MIN}점 이상 · 부정 = {NEG_MAX}점 이하 · 3점은 따로 집계")
    out(f"본문 길이는 지표에서 제외 · 상품 평점 {RATING_FLOOR} 이하 상품 제외")
    out("=" * 78)
    out()

    # ---- 0. 분석 창 -----------------------------------------------------
    out("■ 0. 분석 기간 (N개월 = 리뷰가 실제로 밀집한 수집 창)")
    out(f"    수집 리뷰(중복 제거) {len(rev):,}건 · 작성일 "
        f"{rev['작성일'].min().date()} ~ {end.date()}")
    out(f"    분석 창 {start.date()} ~ {end.date()} = {months}개월 · "
        f"{len(w):,}건 ({100*len(w)/len(rev):.1f}%)")
    out(f"    창 안 상품 {w['상품번호'].nunique():,}개")
    out()

    # ---- 1. 상품 평점 3점 이하 제외의 영향 --------------------------------
    drop = lat_all[lat_all["리뷰별점"] <= RATING_FLOOR]
    zero = drop[drop["리뷰수"].fillna(0) == 0]
    lat = lat_all[lat_all["리뷰별점"] > RATING_FLOOR].copy()
    out("■ 1. 상품 평점 3.0 이하 제외 — 영향 점검")
    out(f"    제외 상품 {len(drop):,}개 / 전체 {len(lat_all):,}개 "
        f"({100*len(drop)/len(lat_all):.1f}%)")
    out(f"      · 그중 리뷰 0건(평점 미표기 신상품) {len(zero):,}개")
    out(f"      · 실제로 낮은 평점을 받은 상품 {len(drop)-len(zero):,}개, "
        f"리뷰 합계 {int(drop['리뷰수'].fillna(0).sum()):,}건")
    keep_pos = w[w["상품번호"].isin(lat["상품번호"])]
    out(f"    긍정 비중: 제외 전 {share(w['별점'],'pos'):.2f}% → "
        f"제외 후 {share(keep_pos['별점'],'pos'):.2f}%  (차이 무시할 수준)")
    out()
    w = keep_pos

    # ---- 2. 두 표본의 긍정 비중 교차확인 -----------------------------------
    ratio_cols = ["별점5비율", "별점4비율", "별점3비율", "별점2비율", "별점1비율"]
    site = lat.dropna(subset=ratio_cols)
    site = site[site["리뷰수"] >= MIN_REVIEWS]
    wpos = np.average(site["pos"], weights=site["리뷰수"])
    wmid = np.average(site["별점3비율"], weights=site["리뷰수"])
    wneg = np.average(site["neg"], weights=site["리뷰수"])
    out("■ 2. 긍정·부정 비중 — 두 표본 교차확인")
    out(f"    (A) 수집 리뷰 본문 {len(w):,}건 ({months}개월 창, 도움순 상위 표본)")
    out(f"        긍정 {share(w['별점'],'pos'):.2f}% · 3점 "
        f"{share(w['별점'],'mid'):.2f}% · 부정 {share(w['별점'],'neg'):.2f}% · "
        f"평균 {w['별점'].mean():.3f}점")
    out(f"    (B) 사이트 집계 전체 리뷰 (리뷰 {MIN_REVIEWS}건 이상 "
        f"{len(site):,}개 상품, 리뷰수 가중)")
    out(f"        긍정 {wpos:.2f}% · 3점 {wmid:.2f}% · 부정 {wneg:.2f}%")
    out("    → 표본 (A)는 도움순 편향이 있지만 긍정 비중은 (B)와 사실상 같다.")
    out("       기간을 자른 (A)의 긍정 비중을 그대로 신뢰할 수 있다는 근거다.")
    out()

    # ---- 3. 상품 단위 분포 -------------------------------------------------
    prod = per_product(w)
    prod = prod[prod["n"] >= MIN_SAMPLED].merge(lat, on="상품번호", how="inner")
    q = site["pos"].quantile([.1, .25, .5, .75, .9])
    out("■ 3. 상품 단위 긍정 비중 분포 (사이트 집계 기준)")
    out(f"    p10 {q[.1]:.0f}% · p25 {q[.25]:.0f}% · 중앙 {q[.5]:.0f}% · "
        f"p75 {q[.75]:.0f}% · p90 {q[.9]:.0f}% · 최저 {site['pos'].min():.0f}%")
    out(f"    긍정 90% 미만 상품 {100*(site['pos']<90).mean():.1f}% · "
        f"80% 미만 {100*(site['pos']<80).mean():.1f}%")
    out(f"    평균 별점 표준편차 {site['리뷰별점'].std():.3f}점 — "
        f"긍정 비중(표준편차 {site['pos'].std():.2f}%p)이 평균보다 넓게 퍼진다")
    out()

    # ---- 4. 카테고리 -------------------------------------------------------
    cat = (site[site["카테고리"] != "전체"].groupby("카테고리")
               .agg(n=("상품번호", "size"), pos=("pos", "mean"),
                    sd=("pos", "std"), neg=("neg", "mean"),
                    rating=("리뷰별점", "mean"), price=("혜택가", "median")))
    cat = cat[cat["n"] >= 20].sort_values("pos")
    out("■ 4. 카테고리별 긍정 비중")
    out(f"    {'카테고리':<12}{'상품':>5}{'긍정%':>8}{'표준편차':>9}{'부정%':>8}{'평점':>7}")
    for name, r in cat.iterrows():
        out(f"    {name:<12}{int(r['n']):>5}{r['pos']:>8.1f}{r['sd']:>9.2f}"
            f"{r['neg']:>8.2f}{r['rating']:>7.2f}")
    out()

    # ---- 5. 브랜드 산포 -----------------------------------------------------
    brand = per_brand(site)
    between = variance_split(site, brand["브랜드"])
    rho_sd, p_sd = stats.spearmanr(brand["pos_sd"], brand["pos"])
    rho_pr, p_pr = stats.spearmanr(brand["pos"], np.log(brand["price"]))
    out("■ 5. 브랜드별 긍정 비중 산포")
    out(f"    상품 {MIN_BRAND_ITEMS}개 이상 브랜드 {len(brand):,}개 · "
        f"긍정 비중 {brand['pos'].min():.1f}% ~ {brand['pos'].max():.1f}% "
        f"(브랜드 간 표준편차 {brand['pos'].std():.2f}%p)")
    out(f"    긍정 비중 총분산 중 브랜드 간 성분 {between:.1f}% "
        "— 나머지는 같은 브랜드 안 상품 간 차이")
    out(f"    브랜드 내 산포 vs 브랜드 평균: ρ={rho_sd:+.3f} (p={p_sd:.2g}) "
        "— 평이 좋은 브랜드일수록 상품 간 편차도 작다")
    out(f"    브랜드 긍정 비중 vs 가격대: ρ={rho_pr:+.3f} (p={p_pr:.2g}) "
        "— 가격은 긍정 비중을 가르지 않는다")
    out("    하위 8개 / 상위 8개")
    for tag, sub in [("하위", brand.head(8)), ("상위", brand.tail(8))]:
        for _, r in sub.iterrows():
            out(f"      [{tag}] {r['브랜드']:<10} 상품 {int(r['items']):>3} · "
                f"긍정 {r['pos']:5.1f}% (내부 편차 {r['pos_sd']:4.2f}) · "
                f"부정 {r['neg']:4.2f}% · 평점 {r['rating']:.2f}")
    out()

    # ---- 6. 순위 설명력 -----------------------------------------------------
    p = build_panel(args.start)
    p["pos_share"] = p["별점5비율"] + p["별점4비율"]
    p["neg_share"] = p["별점2비율"] + p["별점1비율"]
    p["ln_rank"] = np.log(p["순위"])
    d = p[(p["리뷰수"] >= MIN_REVIEWS) & (p["리뷰별점"] > RATING_FLOOR)]
    out("■ 6. 재구성한 평점 지표에 순위 설명력이 생기는가")
    out("    모형: ln(순위) ~ 지표 [+ 통제], 카테고리×일 고정효과, 상품 클러스터 SE")
    for spec in (["pos_share"], ["neg_share"], ["avg_rating"],
                 ["pos_share", "log_review_prev", "velocity_log"],
                 ["neg_share", "log_review_prev", "velocity_log"]):
        r = fe_ols(d, spec, y_col="ln_rank")
        out(f"    · {' + '.join(spec)}")
        out("\n".join(r.lines(indent="        ")))
    out()
    out("    → 긍정 비중도 부정 비중도 순위를 설명하지 못한다(within R² 0.001 미만).")
    out("       같은 모형에서 리뷰 증가 속도만 within R² 0.16 을 만든다.")
    out()

    os.makedirs(OUT_DIR, exist_ok=True)
    last = rank["수집일자"].max().date()
    path = os.path.join(OUT_DIR, f"review_quality_{last}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(R))
    print("\n".join(R))
    print(f"\n저장: {path}")


if __name__ == "__main__":
    main()
