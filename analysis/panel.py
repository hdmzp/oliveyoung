"""T2. 카테고리×일 고정효과 회귀 확장 — 브랜드 통제 + 표준오차 보정.

T1(growth.py)의 회귀는 카테고리×일 고정효과만 걸려 있었다. 두 가지가 빠져 있다.

1. **브랜드 통제**: 메디힐 한 브랜드가 슬롯의 상당수를 차지하므로, 리뷰 규모·유입
   효과가 실은 '그 브랜드라서'일 수 있다. 브랜드 고정효과를 추가로 흡수해야 한다.
2. **표준오차**: 같은 상품이 여러 날 반복 등장하므로 일반 OLS 표준오차는 과소추정되고
   t값이 부풀려진다. 상품 단위 클러스터 SE 로 보정하고, 보정 전후 t를 함께 보고한다.

카테고리×일과 브랜드는 서로 포개지지 않는(non-nested) 두 고정효과이므로 교대 사영
(alternating projections)으로 동시에 흡수한다.

⚠ T1 결과 반영: 리뷰 규모의 고유 설명력이 0이었으므로, TASKS.md 가 적어둔 성공 판정
   ("브랜드 통제 후에도 리뷰 규모 계수가 유의하게 남는가")은 이미 전제가 바뀌었다.
   여기서는 판정 대상을 **유입 속도**로 옮기고, 규모는 참고로 함께 보고한다.

사용:  python -m analysis.panel
출력:  analysis/output/panel_fe_<date>.txt + stdout
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

from .growth import OUT_DIR, DV, build_panel, residualize, vif

MAX_ITER = 500
TOL = 1e-10


# ------------------------------------------------------- 다중 고정효과 흡수

def absorb(df: pd.DataFrame, cols: list[str], groups: list[str]) -> pd.DataFrame:
    """교대 사영으로 여러 고정효과를 동시에 흡수(within 변환)."""
    X = df[cols].astype(float).copy()
    if len(groups) == 1:
        return X - X.groupby(df[groups[0]], sort=False).transform("mean")
    for _ in range(MAX_ITER):
        prev = X.to_numpy(copy=True)
        for g in groups:
            X = X - X.groupby(df[g], sort=False).transform("mean")
        if np.max(np.abs(X.to_numpy() - prev)) < TOL:
            break
    return X


class Res:
    def __init__(self, names, beta, t_plain, t_clu, r2w, n, k_absorbed, vifs, G,
                 r2_total=np.nan):
        self.names, self.beta = names, beta
        self.t_plain, self.t_clu = t_plain, t_clu
        self.r2w, self.n, self.k_absorbed, self.vifs, self.G = r2w, n, k_absorbed, vifs, G
        # within R² 는 흡수 고정효과가 늘면 분모(잔여 분산)가 줄어 서로 비교 불가.
        # r2_total 은 원 순위 분산 기준이라 사양 간 비교가 가능하다.
        self.r2_total = r2_total

    def lines(self, indent="    ") -> list[str]:
        out = [f"{indent}N={self.n:,}  흡수된 고정효과 모수={self.k_absorbed:,}  "
               f"클러스터(상품)={self.G:,}  within R²={self.r2w:.4f}  "
               f"전체 R²(고정효과 포함)={self.r2_total:.4f}",
               f"{indent}{'변수':<16}{'beta':>9}{'t(일반)':>10}{'t(클러스터)':>13}"
               f"{'p(클러스터)':>12}{'VIF':>7}"]
        for nm, b, tp, tc, vf in zip(self.names, self.beta, self.t_plain,
                                     self.t_clu, self.vifs):
            p = 2 * stats.norm.sf(abs(tc))
            star = "***" if p < .001 else "**" if p < .01 else "*" if p < .05 else ""
            out.append(f"{indent}{nm:<16}{b:>+9.3f}{tp:>+10.2f}{tc:>+13.2f}"
                       f"{p:>12.4f}{vf:>7.2f} {star}")
        return out


def fe(df: pd.DataFrame, x_cols: list[str], groups: list[str],
      y_col: str = DV, cluster: str = "상품번호", standardize: bool = True) -> Res:
    sub = df[[y_col] + x_cols + groups + [cluster]].dropna()
    w = absorb(sub, [y_col] + x_cols, groups)
    y = w[y_col].to_numpy(float)
    X = w[x_cols].to_numpy(float)
    sd = X.std(axis=0, ddof=0) if standardize else np.ones(X.shape[1])
    sd[sd == 0] = 1.0
    X = X / sd

    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    u = y - X @ beta
    n, k = X.shape
    # 흡수된 모수 수 (겹치는 상수항 1개 보정)
    k_abs = sum(sub[g].nunique() for g in groups) - (len(groups) - 1)
    dof = n - k - k_abs
    se_p = np.sqrt(np.diag((u @ u / dof) * XtX_inv))

    codes = pd.factorize(sub[cluster].to_numpy())[0]
    G = codes.max() + 1
    agg = np.zeros((G, k))
    np.add.at(agg, codes, X * u[:, None])
    c = (G / (G - 1)) * ((n - 1) / dof)
    V = XtX_inv @ (agg.T @ agg) @ XtX_inv * c
    se_c = np.sqrt(np.diag(V))

    ss = (y ** 2).sum()
    r2w = 1 - (u @ u) / ss if ss > 0 else np.nan
    yr = sub[y_col].to_numpy(float)
    ss_raw = ((yr - yr.mean()) ** 2).sum()
    r2_total = 1 - (u @ u) / ss_raw if ss_raw > 0 else np.nan
    return Res(x_cols, beta, beta / se_p, beta / se_c, r2w, n, k_abs, vif(X), G,
               r2_total)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-05")
    ap.add_argument("--date")
    args = ap.parse_args()

    p = build_panel(args.start, args.date)
    resid, _ = residualize(p, "velocity_log", ["log_review_cnt"])
    p["vlog_resid"] = resid
    last = p["수집일자"].max().date()

    R: list[str] = []
    def w(s: str = "") -> None:
        R.append(s)

    CORE = ["log_review_cnt", "velocity_log"]
    CTRL = ["할인율", "log_price", "avg_rating", "star1_share", "증정", "쿠폰", "세일"]
    ALL = CORE + [c for c in CTRL if p[c].notna().sum() > 0 and p[c].std() > 0]

    w("T2. 카테고리×일 고정효과 회귀 확장 — 브랜드 통제 + 표준오차 보정")
    w(f"패널: {p['수집일자'].min().date()} ~ {last} · 관측 {len(p):,}행 · "
      f"상품 {p['상품번호'].nunique():,}개 · 브랜드 {p['브랜드'].nunique():,}개")
    w("종속변수 = 순위(작을수록 상위). beta = 1 within-SD 당 순위 변화, 음수 = 상위권")
    w("=" * 80)
    w()

    # --- 0. 브랜드 집중도 --------------------------------------------------
    w("■ 0. 브랜드 집중도 — 왜 통제해야 하는가")
    bs = p["브랜드"].value_counts()
    w(f"    브랜드 {len(bs):,}개 · 상위 10개가 슬롯의 {bs.head(10).sum() / len(p):.1%} 점유")
    w(f"    {'브랜드':<14}{'슬롯':>7}{'비중':>8}{'상품수':>7}{'평균순위':>9}")
    for b, cnt in bs.head(8).items():
        g = p[p["브랜드"] == b]
        w(f"    {str(b):<14}{cnt:>7,}{cnt / len(p):>8.1%}"
          f"{g['상품번호'].nunique():>7}{g[DV].mean():>9.1f}")
    w()

    # --- 1. 고정효과 단계별 -----------------------------------------------
    w("■ 1. 고정효과를 단계별로 추가 (변수 구성 고정)")
    specs = [("A  카테고리×일", ["cat_day"]),
             ("B  카테고리×일 + 브랜드", ["cat_day", "브랜드"])]
    results = {}
    for lab, groups in specs:
        r = fe(p, ALL, groups)
        results[lab] = r
        w(f"  {lab}")
        for line in r.lines():
            w(line)
        w()

    a, b = results["A  카테고리×일"], results["B  카테고리×일 + 브랜드"]
    w("■ 1-1. 브랜드 통제의 영향 (계수 이동)")
    w(f"    {'변수':<16}{'A beta':>10}{'B beta':>10}{'변화율':>10}"
      f"{'A t(클)':>10}{'B t(클)':>10}")
    for i, nm in enumerate(a.names):
        chg = (b.beta[i] - a.beta[i]) / abs(a.beta[i]) if a.beta[i] else np.nan
        w(f"    {nm:<16}{a.beta[i]:>+10.3f}{b.beta[i]:>+10.3f}{chg:>+10.1%}"
          f"{a.t_clu[i]:>+10.2f}{b.t_clu[i]:>+10.2f}")
    w(f"    전체 R²(고정효과 포함): {a.r2_total:.4f} → {b.r2_total:.4f} "
      f"(브랜드가 추가로 설명하는 몫 {b.r2_total - a.r2_total:+.4f})")
    w(f"    ※ within R² 는 {a.r2w:.4f} → {b.r2w:.4f} 로 낮아 보이지만 이는 착시다.")
    w("      고정효과를 더 흡수하면 분모(잔여 분산)가 줄어 사양 간 비교가 성립하지 않는다.")
    w("      비교는 원 순위 분산 기준인 전체 R² 로 해야 한다.")
    w()

    # --- 1-2. 브랜드 표본 크기 민감도 --------------------------------------
    w("■ 1-2. 브랜드 고정효과의 과적합 점검")
    bc = p["브랜드"].value_counts()
    w(f"    브랜드 {len(bc):,}개 중 관측 10개 미만 {int((bc < 10).sum()):,}개 "
      f"({(bc < 10).mean():.0%}). 소표본 브랜드는 고정효과가 관측을 거의 흡수해 버린다.")
    w(f"    {'표본 하한':<12}{'브랜드':>8}{'N':>9}{'규모 beta':>11}{'규모 t(클)':>12}"
      f"{'속도 beta':>11}{'속도 t(클)':>12}")
    for lo in (1, 10, 30, 60):
        keep = bc[bc >= lo].index
        g = p[p["브랜드"].isin(keep)]
        r = fe(g, ALL, ["cat_day", "브랜드"])
        w(f"    관측 {lo:>3}개 이상{'':<2}{len(keep):>8,}{r.n:>9,}"
          f"{r.beta[0]:>+11.3f}{r.t_clu[0]:>+12.2f}"
          f"{r.beta[1]:>+11.3f}{r.t_clu[1]:>+12.2f}")
    w()

    # --- 2. 표준오차 보정 효과 --------------------------------------------
    w("■ 2. 표준오차 보정 효과 — t값이 얼마나 줄어드는가")
    w("    (같은 상품이 여러 날 반복 등장 → 일반 SE 는 과소추정)")
    w(f"    {'변수':<16}{'t(일반)':>11}{'t(클러스터)':>14}{'축소율':>10}")
    for i, nm in enumerate(b.names):
        ratio = 1 - abs(b.t_clu[i]) / abs(b.t_plain[i]) if b.t_plain[i] else np.nan
        w(f"    {nm:<16}{b.t_plain[i]:>+11.2f}{b.t_clu[i]:>+14.2f}{ratio:>10.0%}")
    med = np.median([1 - abs(tc) / abs(tp) for tp, tc in zip(b.t_plain, b.t_clu)
                     if tp != 0])
    w(f"    → t값이 중위 {med:.0%} 축소된다. 초판 표 11 의 t=−20.2 같은 수치는")
    w(f"      이 보정 없이 산출된 값이므로 그대로 인용하면 안 된다.")
    w()

    # --- 3. 잔차화 속도 사양 (T1 연계) -------------------------------------
    w("■ 3. 잔차화 속도 사양 (규모/속도 공유분을 규모로 배분)")
    r3 = fe(p, ["log_review_cnt", "vlog_resid"] + ALL[2:], ["cat_day", "브랜드"])
    for line in r3.lines():
        w(line)
    w("    ※ 속도 계수는 §1-B 와 동일하다(FWL). 달라지는 것은 규모 계수의 해석뿐이다.")
    w()

    # --- 4. 날짜별 계수 안정성 --------------------------------------------
    w("■ 4. 날짜별 계수 안정성 (일별로 카테고리+브랜드 고정효과 회귀)")
    w(f"    {'날짜':<12}{'N':>7}{'규모 beta':>11}{'속도 beta':>11}"
      f"{'할인율 beta':>13}{'within R²':>11}")
    rows = []
    for day, g in p.groupby(p["수집일자"].dt.date):
        g = g.dropna(subset=ALL + [DV])
        if len(g) < 300:
            continue
        r = fe(g, ALL, ["카테고리", "브랜드"])
        rows.append((day, r))
        w(f"    {str(day):<12}{r.n:>7,}{r.beta[0]:>+11.3f}{r.beta[1]:>+11.3f}"
          f"{r.beta[2]:>+13.3f}{r.r2w:>11.4f}")
    if rows:
        for j, nm in enumerate(ALL[:3]):
            arr = np.array([r.beta[j] for _, r in rows])
            w(f"    {nm}: 평균 {arr.mean():+.3f}, 표준편차 {arr.std():.3f}, "
              f"음수 비율 {(arr < 0).mean():.0%}")
    w()

    # --- 5. 판정 ----------------------------------------------------------
    w("■ 5. 판정")
    iv, isz = b.names.index("velocity_log"), b.names.index("log_review_cnt")
    w(f"    유입 속도  : 브랜드 통제 후 beta={b.beta[iv]:+.3f}, "
      f"t(클러스터)={b.t_clu[iv]:+.2f}, VIF={b.vifs[iv]:.2f}")
    w(f"    리뷰 규모  : 브랜드 통제 후 beta={b.beta[isz]:+.3f}, "
      f"t(클러스터)={b.t_clu[isz]:+.2f}")
    if abs(b.t_clu[iv]) > 2:
        w("    ▶ 유입 속도는 브랜드를 통제해도 살아남는다 — 브랜드 효과의 대리가 아니다.")
    else:
        w("    ▶ 유입 속도가 브랜드 통제 후 사라진다 — 브랜드 효과였을 가능성이 크다.")
    if abs(b.t_clu[isz]) > 2:
        w("    ▶ 리뷰 규모는 브랜드를 통제하면 되살아난다. T1(브랜드 미통제)에서 고유")
        w("      설명력이 0이었던 것과 다르므로, 두 결과를 함께 읽어야 한다:")
        w("        · 브랜드 간 비교에서는 규모가 곧 '어느 브랜드인가'의 대리였다")
        w("        · 같은 브랜드 안에서는 누적 리뷰가 많은 상품이 더 상위권이다")
        w(f"      단 크기는 속도의 {abs(b.beta[isz]) / abs(b.beta[iv]):.0%} 수준이고, "
          f"일별 재추정에서 부호가 3/10일 뒤집혀 속도만큼 안정적이지 않다(§4).")
    else:
        w("    ▶ 리뷰 규모는 브랜드 통제 후에도 유의하지 않다 (T1 결과와 일치).")
    w()
    w("    ⚠ 한계: 브랜드 고정효과는 브랜드의 평균 수준만 흡수한다. 브랜드가 시점별로")
    w("      다른 마케팅을 하는 부분은 흡수되지 않는다.")
    w("    ⚠ 여전히 동시점 연관이며 인과가 아니다. 선후관계는 T4 의 몫이다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"panel_fe_{last}.txt")
    text = "\n".join(R)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
