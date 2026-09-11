"""웹 리포트(index.html) 차트에 박아 넣는 시계열·분포 데이터를 다시 만든다.

보고서의 수치 절은 analysis 의 각 모듈이 txt 로 뱉지만, 차트용 배열
(assets/app.js 의 const churn / cohort / catCorr / ratingBins ...) 은 그동안
세션에서 손으로 계산해 붙여 왔다. 데이터가 쌓일 때마다 같은 계산을 다시
하려면 근거가 남아야 하므로 모듈로 고정한다.

산출 방식은 2026-09-01 판 보고서에 실린 값을 그대로 재현하도록 맞췄다
(--verify 로 확인 가능).

사용:  python -m analysis.web_series [--date YYYY-MM-DD] [--verify]
출력:  analysis/output/web_series_<date>.json + stdout(app.js 붙여넣기 형태)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

from .growth import OUT_DIR, PANEL_START, build_panel, load_rankings

OVERALL = "전체"
BANDS = [(1, 10), (11, 25), (26, 50), (51, 75), (76, 100)]
BAND_NAMES = ["1–10위", "11–25위", "26–50위", "51–75위", "76–100위"]
CHURN_FROM = "08-04"          # 카테고리 수집 직전일부터 그린다


def _band(v: float) -> int:
    for i, (lo, hi) in enumerate(BANDS):
        if lo <= v <= hi:
            return i
    return len(BANDS)


# ---------------------------------------------------------------- 그림 1

def churn_series(rank: pd.DataFrame, end: str | None) -> list[list]:
    """전체 랭킹 100위의 일별 신규 진입 수 — 직전 수집일에 없던 상품 수."""
    r = rank[rank["카테고리"] == OVERALL]
    if end:
        r = r[r["수집일자"] <= pd.Timestamp(end)]
    days = sorted(r["수집일자"].unique())
    members = {d: set(r[r["수집일자"] == d]["상품번호"]) for d in days}
    out = []
    for prev, cur in zip(days, days[1:]):
        label = pd.Timestamp(cur).strftime("%m-%d")
        if label >= CHURN_FROM:
            out.append([label, len(members[cur] - members[prev])])
    return out


# ---------------------------------------------------------------- 그림 2

def cohort_matrix(rank: pd.DataFrame, start: str, end: str | None):
    """당일 순위 구간 → 익일 순위 구간 전이 행렬(행 기준 %).

    카테고리 패널만 사용하고, 수집일이 정확히 하루 간격인 전이만 센다
    (결측일을 사이에 둔 쌍은 '익일'이 아니므로 제외).
    """
    r = rank[(rank["수집일자"] >= pd.Timestamp(start)) & (rank["카테고리"] != OVERALL)]
    if end:
        r = r[r["수집일자"] <= pd.Timestamp(end)]
    cur = r[["수집일자", "카테고리", "상품번호", "순위"]].dropna()
    nxt = cur.copy()
    nxt["수집일자"] = nxt["수집일자"] - pd.Timedelta(days=1)
    m = cur.merge(nxt, on=["수집일자", "카테고리", "상품번호"],
                  suffixes=("", "_next"), how="left")
    days = sorted(r["수집일자"].unique())
    paired = {d for d, nd in zip(days, days[1:])
              if (pd.Timestamp(nd) - pd.Timestamp(d)).days == 1}
    m = m[m["수집일자"].isin(paired)]

    M = np.zeros((len(BANDS), len(BANDS) + 1))
    src = m["순위"].map(_band).to_numpy()
    dst = np.where(m["순위_next"].isna(), len(BANDS),
                   m["순위_next"].fillna(9_999).map(_band).to_numpy())
    for i, j in zip(src, dst):
        if i < len(BANDS):
            M[i, j] += 1
    pct = M / M.sum(axis=1, keepdims=True) * 100
    return pct, M.sum(axis=1)


# ---------------------------------------------------------------- 그림 4

def category_corr(panel: pd.DataFrame, min_n: int = 20) -> list[list]:
    """카테고리별 리뷰 증가 속도–순위 Spearman ρ 의 일별 평균과 최소·최대."""
    p = panel.dropna(subset=["velocity", "순위"])
    rows = []
    for cat, g in p.groupby("카테고리"):
        if cat == OVERALL:
            continue
        rs = [stats.spearmanr(gd["velocity"], gd["순위"]).statistic
              for _, gd in g.groupby("수집일자") if len(gd) >= min_n]
        if not rs:
            continue
        rs = np.array(rs)
        rows.append([cat, round(float(rs.mean()), 2),
                     round(float(rs.min()), 2), round(float(rs.max()), 2)])
    rows.sort(key=lambda r: -r[1])
    return rows


# ---------------------------------------------------------------- 그림 5

def rating_bins(rank: pd.DataFrame, end: str | None) -> list[list]:
    """상품 평균 별점 분포 — 기간 내 등장한 전 상품의 0.1점 구간 상품 수.

    상품마다 마지막 관측 별점 하나만 센다. 별점이 없거나 4.0 미만인 상품은
    0.0 구간으로 모으고(천장효과를 보이는 그림이라 하단은 쪼갤 이유가 없다),
    만점 부근은 4.9 구간에 합친다.
    """
    r = rank if not end else rank[rank["수집일자"] <= pd.Timestamp(end)]
    last = r.sort_values("수집일자").drop_duplicates(subset=["상품번호"], keep="last")
    v = pd.to_numeric(last["리뷰별점"], errors="coerce")
    binned = np.where(v.isna() | (v < 4.05), 0.0,
                      np.minimum((v * 10).round() / 10, 4.9))
    counts = pd.Series(binned).value_counts().sort_index()
    return [[round(float(k), 1), int(n)] for k, n in counts.items()]


# ---------------------------------------------------------------- 표 11

def permanent_rankers(rank: pd.DataFrame, end: str | None, frac: float = 0.8):
    """전체 TOP100 에 기간의 frac 이상 등장한 '상시 랭커' 브랜드.

    슬롯 = 브랜드가 차지한 (날짜×순위) 칸의 수. 점유율은 전체 슬롯 대비.
    """
    r = rank[rank["카테고리"] == OVERALL]
    if end:
        r = r[r["수집일자"] <= pd.Timestamp(end)]
    ndays = r["수집일자"].nunique()
    g = r.groupby("브랜드")
    t = pd.DataFrame({"등장일수": g["수집일자"].nunique(), "슬롯": g.size(),
                      "품목": g["상품번호"].nunique(),
                      "평균순위": g["순위"].mean(), "최고순위": g["순위"].min()})
    perm = t[t["등장일수"] >= ndays * frac].sort_values("슬롯", ascending=False)
    return ndays, perm, float(perm["슬롯"].sum() / len(r) * 100)


# ---------------------------------------------------------------- 검증

VERIFY_2026_09_01 = {
    "cohort": [[60, 19, 8, 3, 3, 8], [12, 44, 22, 6, 3, 13], [3, 13, 38, 18, 8, 21],
               [1, 3, 18, 29, 17, 33], [1, 2, 8, 15, 25, 49]],
    "churn_tail": [["08-29", 41], ["08-30", 61], ["08-31", 6], ["09-01", 32]],
    "catcorr_head": ["취미/팬시", -0.26, -0.43, -0.03],
    "catcorr_tail": ["네일", -0.60, -0.74, -0.49],
    "rating_bins": [[0.0, 642], [4.1, 8], [4.2, 19], [4.3, 34], [4.4, 55], [4.5, 155],
                    [4.6, 335], [4.7, 987], [4.8, 2202], [4.9, 2492]],
    "brands": (38, 27, 43.6, ["메디힐", 38, 263, 18, 37.7, 1]),
}


def verify() -> bool:
    rank = load_rankings()
    ok = True
    churn = churn_series(rank, "2026-09-01")
    got = [list(x) for x in churn[-4:]]
    ok &= got == VERIFY_2026_09_01["churn_tail"]
    print(f"  churn 말미  {'OK' if got == VERIFY_2026_09_01['churn_tail'] else 'MISMATCH'}  {got}")

    pct, _ = cohort_matrix(rank, PANEL_START, "2026-09-01")
    got = pct.round(0).astype(int).tolist()
    ok &= got == VERIFY_2026_09_01["cohort"]
    print(f"  cohort      {'OK' if got == VERIFY_2026_09_01['cohort'] else 'MISMATCH'}")

    cc = category_corr(build_panel(end="2026-09-01"))
    ok &= cc[0] == VERIFY_2026_09_01["catcorr_head"] and cc[-1] == VERIFY_2026_09_01["catcorr_tail"]
    print(f"  catCorr     {'OK' if cc[0] == VERIFY_2026_09_01['catcorr_head'] else 'MISMATCH'}"
          f"  {cc[0]} … {cc[-1]}")

    rb = rating_bins(rank, "2026-09-01")
    hit = rb == VERIFY_2026_09_01["rating_bins"]
    ok &= hit
    print(f"  ratingBins  {'OK' if hit else 'MISMATCH'}  합계 {sum(v for _, v in rb):,}")

    nd, perm, share = permanent_rankers(rank, "2026-09-01")
    top = perm.index[0]
    row = [top, nd, int(perm.iloc[0]["슬롯"]), int(perm.iloc[0]["품목"]),
           round(float(perm.iloc[0]["평균순위"]), 1), int(perm.iloc[0]["최고순위"])]
    want_days, want_n, want_share, want_row = VERIFY_2026_09_01["brands"]
    hit = (nd == want_days and len(perm) == want_n
           and round(share, 1) == want_share and row == want_row)
    ok &= hit
    print(f"  표11 브랜드  {'OK' if hit else 'MISMATCH'}  {nd}일 {len(perm)}개사 {share:.1f}% {row}")
    return bool(ok)


# ---------------------------------------------------------------- 출력

def emit_js(data: dict) -> str:
    lines = ["  const churn = ["]
    lines += [f'    ["{d}", {v}],' for d, v in data["churn"]]
    lines.append("  ];")
    lines.append(f'  const churnMean = {data["churnMean"]};')
    lines.append("")
    lines.append("  const cohort = [")
    lines += ["    [" + ", ".join(str(x) for x in row) + "]," for row in data["cohort"]]
    lines.append("  ];")
    lines.append("")
    lines.append("  const catCorr = [")
    lines += [f'    ["{c}", {a}, {b}, {d}],' for c, a, b, d in data["catCorr"]]
    lines.append("  ];")
    lines.append("")
    lines.append("  const ratingBins = [")
    lines.append("    " + ", ".join(f"[{k}, {v}]" for k, v in data["ratingBins"]) + ",")
    lines.append("  ];")
    return "\n".join(lines)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=PANEL_START)
    ap.add_argument("--date", help="종료일 (기본: 최신)")
    ap.add_argument("--verify", action="store_true",
                    help="2026-09-01 판 보고서 수치를 재현하는지만 확인")
    args = ap.parse_args()

    if args.verify:
        print("2026-09-01 판 재현 검증")
        sys.exit(0 if verify() else 1)

    rank = load_rankings()
    end = args.date
    churn = churn_series(rank, end)
    pct, n = cohort_matrix(rank, args.start, end)
    data = {
        "generated_to": str((rank["수집일자"].max() if not end else pd.Timestamp(end)).date()),
        "churn": churn,
        "churnMean": int(round(float(np.mean([v for _, v in churn])))),
        "cohort": pct.round(0).astype(int).tolist(),
        "cohortN": n.astype(int).tolist(),
        "catCorr": category_corr(build_panel(start=args.start, end=end)),
        "ratingBins": rating_bins(rank, end),
    }
    ndays, perm, share = permanent_rankers(rank, end)
    data["panelDays"] = ndays
    data["permanentRankers"] = {
        "brands": len(perm), "slotShare": round(share, 1),
        "top": [[b, int(r["등장일수"]), int(r["슬롯"]), int(r["품목"]),
                 round(float(r["평균순위"]), 1), int(r["최고순위"])]
                for b, r in perm.head(5).iterrows()],
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"web_series_{data['generated_to']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(emit_js(data))
    print(f"\n저장: {path}")


if __name__ == "__main__":
    main()
