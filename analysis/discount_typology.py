"""할인율–판매 반응의 유형학 (보고서 5.5절).

5.4절은 "프로모션이 붙은 날 순위가 오르는가"를 평균 효과 하나로 답했다. 이 모듈은
그 평균 뒤에 숨은 **형태(shape)** 를 본다. 할인율을 올릴 때 판매가 어떻게 반응하는지
는 상품군마다 다르며, 그 곡선의 모양이 곧 프로모션 설계의 규칙이 되기 때문이다.

판매 지표
--------
판매 수량은 공개되지 않는다. 5.3절에서 랭킹이 매출액 기준임을 확인했고, 리뷰 유입
(velocity = 일 리뷰 증가분)이 판매 **수량**의 대리지표라는 것도 같은 절에서 세웠다.
따라서 수량 반응은 ln(1+velocity), 금액 반응은 ln(1+velocity×혜택가)로 본다.

설계
----
1) 할인율을 6구간(0 / 1–10 / 10–20 / 20–30 / 30–40 / 40%+)으로 끊고,
   **카테고리 × 가격 3분위** 셀마다 반응 곡선을 추정한다.
     ln(1+velocity) ~ 할인구간 더미 + log(전기 리뷰 재고), 날짜 고정효과
   0% 구간이 기준선이므로 계수는 "비할인 대비 판매 로그 차이"로 읽는다.
2) 곡선을 진폭으로 나눠 **형태만** 남긴 뒤 k-means 로 유형을 찾는다.
   진폭을 지우는 이유: 반응의 크기가 아니라 모양(가속형·임계형·역행형)으로 묶기 위해서다.
3) 유형별로 소속 상품의 가격·배지·리뷰 규모·썸네일 색채를 프로파일링한다.

⚠ 식별의 한계: 같은 상품이 할인율을 바꾸는 폭이 26일 창에서는 작다(상품 내 할인율
   표준편차 중앙값 0). 따라서 곡선은 상품 내 변화가 아니라 **같은 카테고리·같은 날
   서로 다른 할인율의 상품들을 가로로 비교**해 얻은 것이다. 할인 편성 자체가 상품의
   기대 수요에 따라 정해지므로 인과가 아니라 연관으로만 읽어야 한다.

사용:  python -m analysis.discount_typology
출력:  analysis/output/discount_typology_<date>.txt + stdout
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score

from .growth import OUT_DIR, build_panel, fe_ols

BANDS = [-0.01, 0.001, 10, 20, 30, 40, 101]
LABELS = ["0%", "1-10%", "10-20%", "20-30%", "30-40%", "40%+"]
BAND_COLS = [f"b_{l}" for l in LABELS[1:]]
MIN_CELL_ROWS = 400      # 셀 곡선을 추정할 최소 관측 수
MIN_BAND_ROWS = 25       # 구간 더미를 살릴 최소 관측 수
K = 4                    # 유형 수
TYPE_NAMES = {}          # 클러스터 → 이름 (형태 보고 사후 부여)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def prep(start: str = "2026-08-05") -> pd.DataFrame:
    p = build_panel(start)
    d = (p[p["카테고리"] != "전체"]
         .drop_duplicates(subset=["수집일자", "상품번호"]).copy())
    d = d.dropna(subset=["velocity", "할인율", "혜택가", "리뷰수"])
    d = d[(d["velocity"] >= 0) & (d["혜택가"] > 0)]
    d["y_qty"] = np.log1p(d["velocity"])
    d["y_rev"] = np.log1p(d["velocity"] * d["혜택가"])
    d["day"] = d["수집일자"].dt.strftime("%Y-%m-%d")
    d["band"] = pd.cut(d["할인율"], BANDS, labels=LABELS)
    dummies = pd.get_dummies(d["band"], prefix="b").astype(float)
    dummies.index = d.index
    d = pd.concat([d, dummies], axis=1)
    price = d.groupby("상품번호")["혜택가"].median()
    d["price_med"] = d["상품번호"].map(price)
    d["tier"] = d.groupby("카테고리")["price_med"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 3,
                          labels=["저가", "중가", "고가"]))
    return d


def cell_curves(d: pd.DataFrame) -> pd.DataFrame:
    """카테고리 × 가격 3분위 셀별 할인 반응 곡선."""
    rows = {}
    for (cat, tier), s in d.groupby(["카테고리", "tier"], observed=True):
        if len(s) < MIN_CELL_ROWS:
            continue
        live = [c for c in BAND_COLS if s[c].sum() >= MIN_BAND_ROWS]
        if len(live) < 3:
            continue
        r = fe_ols(s, live + ["log_review_prev"], y_col="y_qty",
                   group="day", standardize=False)
        coef = dict(zip(r.names, r.beta))
        rows[(cat, tier)] = ([coef.get(c, np.nan) for c in BAND_COLS]
                             + [len(s), s["price_med"].median()])
    C = pd.DataFrame(rows, index=BAND_COLS + ["N", "price"]).T
    C.index = pd.MultiIndex.from_tuples(C.index, names=["카테고리", "tier"])
    return C


def shapes(C: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """곡선을 0% 기준선 포함 6점으로 만들고, 진폭으로 나눠 형태만 남긴다."""
    X = C[BAND_COLS].ffill(axis=1).bfill(axis=1).clip(-1.5, 1.5)
    X.insert(0, "b_0%", 0.0)
    V = X.to_numpy(float)
    amp = np.abs(V).max(axis=1, keepdims=True)
    amp[amp == 0] = 1.0
    return V, V / amp


def name_types(S: np.ndarray, labels: np.ndarray) -> dict[int, str]:
    """형태 평균으로 유형 이름을 자동 부여한다 (해석은 리포트에서)."""
    names = {}
    for k in sorted(set(labels)):
        m = S[labels == k].mean(axis=0)
        shallow, deep = m[1:3].mean(), m[4:].mean()
        if deep > 0.3 and shallow >= -0.1:
            names[k] = "가속형"
        elif deep > 0.2 and shallow < -0.1:
            names[k] = "데스밸리형"
        elif shallow > 0.3 and deep <= 0.2:
            names[k] = "소액반응형"
        else:
            names[k] = "무반응·역행형"
    # 이름이 겹치면 뒤에 번호를 붙여 구분 가능하게
    seen: dict[str, int] = {}
    for k in sorted(names):
        base = names[k]
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            names[k] = f"{base}{seen[base]}"
    return names


def image_features() -> pd.DataFrame:
    path = os.path.join(OUT_DIR, "image_bank.csv")
    if not os.path.exists(path):
        return pd.DataFrame(columns=["key", "brightness", "saturation",
                                     "colorfulness"])
    ib = pd.read_csv(path, encoding="utf-8-sig")
    ib["key"] = ib["file"].str.replace(r"\.\w+$", "", regex=True)
    return ib[["key", "brightness", "saturation", "colorfulness"]]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-05")
    args = ap.parse_args()

    d = prep(args.start)
    C = cell_curves(d)
    V, S = shapes(C)
    km = KMeans(K, n_init=200, random_state=1).fit(S)
    C["cluster"] = km.labels_
    names = name_types(S, km.labels_)
    C["type"] = [names[k] for k in km.labels_]

    R: list[str] = []
    def out(s: str = "") -> None:
        R.append(s)

    out("할인율–판매 반응의 유형학")
    out(f"표본 {len(d):,}행 · 상품 {d['상품번호'].nunique():,}개 · "
        f"{d['day'].min()} ~ {d['day'].max()}")
    out("판매 대리지표: ln(1+리뷰 유입) = 수량 · ln(1+리뷰 유입×혜택가) = 금액")
    out("=" * 78)
    out()

    out("■ 1. 상품 내 할인율 변동만으로는 곡선을 못 그린다 (설계 근거)")
    g = d.groupby("상품번호")["할인율"]
    span = (g.max() - g.min())
    out(f"    상품 내 할인율 표준편차 중앙값 {g.std().median():.2f}%p · "
        f"변동 폭 0 인 상품 {100*(span == 0).mean():.1f}%")
    out(f"    관측 8일 이상 + 서로 다른 할인율 3개 이상인 상품은 "
        f"{int(((g.size() >= 8) & (g.nunique() >= 3) & (span >= 5)).sum()):,}개뿐")
    out("    → 곡선은 카테고리×가격대 셀 안에서 상품 간 비교로 추정한다.")
    out()

    out("■ 2. 셀별 반응 곡선 (0% 구간 대비 ln 판매량 차이)")
    out(f"    {'셀':<20}" + "".join(f"{l:>9}" for l in LABELS[1:]) + f"{'N':>7}")
    for (cat, tier), r in C.sort_values("type").iterrows():
        vals = "".join("      —  " if pd.isna(r[c]) else f"{r[c]:>9.2f}"
                       for c in BAND_COLS)
        out(f"    {cat + '·' + tier:<20}{vals}{int(r['N']):>7}   [{r['type']}]")
    out()

    sil = silhouette_score(S, km.labels_)
    ari = [adjusted_rand_score(km.labels_,
                               KMeans(K, n_init=200, random_state=s)
                               .fit_predict(S)) for s in (2, 7, 11, 23, 99)]
    out("■ 3. 유형 분류의 안정성")
    out(f"    셀 {len(C)}개 → {K}개 유형 · 실루엣 {sil:.3f}")
    out(f"    시드를 바꿔도 같은 분할인가 (ARI): "
        f"{', '.join(f'{a:.2f}' for a in ari)}")
    out("    실루엣은 높지 않다. 곡선이 뚜렷한 덩어리로 갈라진다기보다 "
        "연속적으로 변하기 때문이며,")
    out("    같은 분할이 시드와 무관하게 재현된다는 점(ARI≈1)이 유형 자체의 근거다.")
    out()

    out("■ 4. 유형별 평균 곡선 — 수량과 금액")
    d = d.merge(C.reset_index()[["카테고리", "tier", "type"]],
                on=["카테고리", "tier"], how="left").dropna(subset=["type"])
    curves: dict[str, dict[str, list[float]]] = {}
    for t, s in d.groupby("type"):
        curves[t] = {}
        out(f"    [{t}] 셀 {int((C['type'] == t).sum())}개 · "
            f"상품 {s['상품번호'].nunique():,}개 · 관측 {len(s):,}행")
        for tag, ycol in (("수량", "y_qty"), ("금액", "y_rev")):
            live = [c for c in BAND_COLS if s[c].sum() >= MIN_BAND_ROWS]
            r = fe_ols(s, live + ["log_review_prev"], y_col=ycol,
                       standardize=False)
            coef = dict(zip(r.names, r.beta))
            tstat = dict(zip(r.names, r.tc))
            curves[t][tag] = [coef.get(c, np.nan) for c in BAND_COLS]
            out(f"        {tag}  " + "  ".join(
                f"{c[2:]}:{coef.get(c, float('nan')):+.2f}"
                f"({tstat.get(c, float('nan')):+.1f})" for c in BAND_COLS))
    out()

    out("■ 5. 유형별 배지 효과 (할인율·리뷰 재고 통제, 종속변수 = 판매수량)")
    for t, s in d.groupby("type"):
        r = fe_ols(s, ["세일", "쿠폰", "증정", "할인율", "log_review_prev"],
                   y_col="y_qty", standardize=False)
        coef = dict(zip(r.names, r.beta))
        tstat = dict(zip(r.names, r.tc))
        out(f"    [{t}] " + "  ".join(
            f"{k}:{coef[k]:+.3f}({tstat[k]:+.1f})"
            for k in ("세일", "쿠폰", "증정", "할인율")))
    out()

    out("■ 6. 유형별 상품 프로파일 — 무엇이 유형을 가르는가")
    ib = image_features()
    d["key"] = d["대표이미지URL"].fillna("").map(
        lambda u: hashlib.md5(u.encode()).hexdigest()[:16] if u else None)
    d = d.merge(ib, on="key", how="left")
    prod = (d.groupby(["type", "상품번호"])
              .agg(price=("price_med", "first"), disc=("할인율", "mean"),
                   sale=("세일", "mean"), coupon=("쿠폰", "mean"),
                   gift=("증정", "mean"), reviews=("리뷰수", "max"),
                   rating=("리뷰별점", "mean"), rank=("순위", "mean"),
                   brand=("브랜드", "first"), sat=("saturation", "mean"),
                   bright=("brightness", "mean"), colorful=("colorfulness", "mean"))
              .reset_index())
    for t, s in prod.groupby("type"):
        cells = C[C["type"] == t].reset_index()
        out(f"    [{t}] 상품 {len(s):,}개 · 브랜드 {s['brand'].nunique()}개")
        out(f"        가격 중앙 {s['price'].median():,.0f}원 "
            f"(p25 {s['price'].quantile(.25):,.0f} / "
            f"p75 {s['price'].quantile(.75):,.0f}) · "
            f"평균 할인율 {s['disc'].mean():.1f}%")
        out(f"        배지 상시성 — 세일 {s['sale'].mean()*100:.0f}% · "
            f"쿠폰 {s['coupon'].mean()*100:.0f}% · 증정 {s['gift'].mean()*100:.0f}%")
        out(f"        리뷰수 중앙 {s['reviews'].median():,.0f}건 · "
            f"평점 {s.loc[s['rating'] > 3, 'rating'].mean():.2f} · "
            f"평균 순위 {s['rank'].mean():.0f}위")
        out(f"        썸네일 채도 {s['sat'].mean():.3f} · "
            f"명도 {s['bright'].mean():.0f} · 색 다양성 {s['colorful'].mean():.1f}")
        out(f"        카테고리 {', '.join(sorted(set(cells['카테고리'])))}")
        tiers = cells["tier"].value_counts()
        out("        가격대 구성 " + " · ".join(
            f"{k} {int(v)}셀" for k, v in tiers.items()))
    out()

    os.makedirs(OUT_DIR, exist_ok=True)
    last = d["day"].max()
    path = os.path.join(OUT_DIR, f"discount_typology_{last}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(R))
    C.to_csv(os.path.join(OUT_DIR, f"discount_cells_{last}.csv"),
             encoding="utf-8-sig")
    print("\n".join(R))
    print(f"\n저장: {path}")


if __name__ == "__main__":
    main()
