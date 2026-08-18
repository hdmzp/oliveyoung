"""크로스섹션 상관/회귀 리포트 (PLAN.md §5의 1~3단계).

1) 기술통계 + 순위와의 Spearman 상관
2) 표준화 OLS: 순위 ~ z(변수들)  (표준화 베타, t-stat, R²)
3) 설명력 분해: 변수군별 단독 R² / 전체 모형에서 뺐을 때 ΔR²

사용:  python -m analysis.crosssection [--date YYYY-MM-DD]
       (해당 날짜의 analysis/output/dataset_*.csv 가 먼저 있어야 함)
출력:  analysis/output/report_<date>.txt + stdout
"""
from __future__ import annotations

import argparse
import glob
import math
import os

import numpy as np
import pandas as pd

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

DV = "순위"  # 작을수록 상위


def spearman(a: pd.Series, b: pd.Series) -> float:
    """동률 평균순위 후 Pearson — scipy 없이 계산하는 Spearman rho."""
    return a.rank().corr(b.rank())

# 변수군: Q3(리뷰수 vs 평점 vs 속도)의 설명력 분해 단위
GROUPS = {
    "규모(리뷰수)": ["log_review_cnt"],
    "평점": ["avg_rating", "star1_share"],
    "유입속도": ["velocity_delta"],
    "체험단/리뷰구성": ["trial_share", "offline_share", "photo_share"],
    "가격/프로모션": ["log_price", "할인율", "증정", "오늘드림"],
}
EXTRA_CORR_VARS = ["star5_share", "velocity_span", "growth_rate",
                   "recent30_share", "recent90_share", "repurchase_share",
                   "gift_share", "sampled_avg_rating", "세일", "쿠폰"]


def ols(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """표준화 입력 가정 없이 상수항 포함 OLS. (beta, t, R²) 반환."""
    n = len(y)
    Xc = np.column_stack([np.ones(n), X])
    beta, *_ = np.linalg.lstsq(Xc, y, rcond=None)
    resid = y - Xc @ beta
    dof = n - Xc.shape[1]
    sigma2 = resid @ resid / dof
    cov = sigma2 * np.linalg.pinv(Xc.T @ Xc)
    t = beta / np.sqrt(np.diag(cov))
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1 - (resid @ resid) / ss_tot
    return beta, t, r2


def p_approx(t: float) -> float:
    """정규 근사 양측 p-value (N이 크지 않으면 참고용)."""
    return math.erfc(abs(t) / math.sqrt(2))


def fit_report(df: pd.DataFrame, ivs: list[str]) -> tuple[str, float, int]:
    sub = df[[DV] + ivs].dropna()
    # dropna 후 상수가 된 변수(예: 전 상품 오늘드림=1)는 표준화 불가 → 제외
    used = [v for v in ivs if sub[v].std(ddof=0) > 0]
    dropped = [v for v in ivs if v not in used]
    n = len(sub)
    y = sub[DV].to_numpy(dtype=float)
    X = sub[used].to_numpy(dtype=float)
    X = (X - X.mean(axis=0)) / X.std(axis=0, ddof=0)
    beta, t, r2 = ols(y, X)
    lines = [f"  N={n}, R²={r2:.3f}   (종속변수: 순위 — 베타가 음수일수록 상위권과 연관)"]
    for name, b, tv in zip(used, beta[1:], t[1:]):
        lines.append(f"    {name:<18} beta={b:+7.2f}  t={tv:+5.2f}  p≈{p_approx(tv):.3f}")
    if dropped:
        lines.append(f"    (분산 0으로 제외: {', '.join(dropped)})")
    return "\n".join(lines), r2, n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="스냅샷 날짜 YYYY-MM-DD (기본: 최신 dataset)")
    args = ap.parse_args()

    if args.date:
        path = os.path.join(OUT_DIR, f"dataset_{args.date}.csv")
    else:
        cands = sorted(glob.glob(os.path.join(OUT_DIR, "dataset_*.csv")))
        if not cands:
            raise SystemExit("먼저 python -m analysis.build_dataset 을 실행하세요.")
        path = cands[-1]
    df = pd.read_csv(path, encoding="utf-8-sig")
    date = os.path.basename(path)[len("dataset_"):-len(".csv")]

    rep = [f"랭킹 크로스섹션 리포트 — 스냅샷 {date}, 상품 {len(df)}개",
           "(주의: TOP100 절단 표본 / 역인과 가능 → 연관성으로만 해석. PLAN.md §2)",
           ""]

    all_ivs = [v for vs in GROUPS.values() for v in vs]
    corr_vars = all_ivs + [v for v in EXTRA_CORR_VARS if v in df.columns]

    rep.append("■ 1. 순위와의 Spearman 상관 (음수 = 값이 클수록 상위권)")
    rows = []
    for v in corr_vars:
        s = df[[DV, v]].dropna()
        if len(s) < 10 or s[v].nunique() < 3:
            continue
        rho = spearman(s[DV], s[v])
        rows.append((v, rho, len(s)))
    for v, rho, n in sorted(rows, key=lambda r: abs(r[1]), reverse=True):
        rep.append(f"    {v:<20} rho={rho:+.3f}  (N={n})")
    rep.append("")

    rep.append("■ 2. 표준화 OLS — 전체 모형")
    full_txt, full_r2, _ = fit_report(df, all_ivs)
    rep.append(full_txt)
    rep.append("")

    # R² 비교는 표본이 같아야 공정 → 전체 변수 완전사례로 고정
    cc = df[[DV] + all_ivs].dropna()
    rep.append(f"■ 3. 설명력 분해 (변수군별, 완전사례 N={len(cc)}로 고정)")
    rep.append(f"    {'변수군':<14} {'단독 R²':>8} {'제외시 ΔR²':>10}")
    for gname, ivs in GROUPS.items():
        _, solo_r2, _ = fit_report(cc, ivs)
        rest = [v for v in all_ivs if v not in ivs]
        _, rest_r2, _ = fit_report(cc, rest)
        rep.append(f"    {gname:<14} {solo_r2:8.3f} {full_r2 - rest_r2:10.3f}")
    rep.append("")
    rep.append("  단독 R² = 그 변수군만 넣은 모형 / ΔR² = 전체 모형에서 뺐을 때 감소분")

    text = "\n".join(rep)
    out = os.path.join(OUT_DIR, f"report_{date}.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
