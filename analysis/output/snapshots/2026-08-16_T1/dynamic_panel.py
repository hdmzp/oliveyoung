"""T4. 동적 패널 — 선후관계 접근.

지금까지의 분석은 전부 동시점 상관이다. "리뷰가 몰린 다음에 순위가 오르는가, 순위가
오른 다음에 리뷰가 몰리는가"를 구분해야 Q1 이 인과에 가까워진다.

  방향 A:  Δ순위_t   = f(유입_{t−1}, 순위_{t−1}, 통제변수)
  방향 B:  유입_t     = f(순위_{t−1}, 유입_{t−1}, 통제변수)

두 방향의 계수 크기를 비교해 피드백 루프의 상대적 강도를 서술한다. Granger 스타일이지만
**인과 주장은 하지 않는다**.

⚠ 선행 조건 미충족: TASKS.md 는 카테고리 패널 3주치(8/26 이후)를 권장한다. 현재는
   8/5~8/18 중 카테고리 수집일 기준 약 2주다. 시차 변수의 검정력이 부족할 수 있으므로
   결과는 잠정치로 취급하고, 데이터가 쌓이면 재실행한다.

⚠ Nickell bias: 시차 종속변수를 고정효과와 함께 넣으면 T가 짧을수록 계수가 편향된다.
   T≈10 이므로 편향 크기가 무시할 수준이 아니다. 본 모듈은 편향 방향을 명시하고,
   시차 종속변수를 뺀 사양도 함께 보고한다.

사용:  python -m analysis.dynamic_panel
출력:  analysis/output/dynamic_panel_<date>.txt
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

from .growth import OUT_DIR, build_panel, fe_ols

MAX_GAP = 1          # 시차는 인접 수집일(간격 1일)만 사용


def make_lags(p: pd.DataFrame) -> pd.DataFrame:
    """상품×일 패널에 1기 시차와 차분을 붙인다 (카테고리별로 독립 계산)."""
    d = p.dropna(subset=["순위", "velocity_log", "log_review_cnt"]).copy()
    d["ln_rank"] = np.log(d["순위"])
    days = pd.Index(sorted(d["수집일자"].unique()))
    di = {v: i for i, v in enumerate(days)}
    d["di"] = d["수집일자"].map(di)
    d = d.sort_values(["카테고리", "상품번호", "di"])
    g = d.groupby(["카테고리", "상품번호"], sort=False)
    for c in ["ln_rank", "velocity_log", "log_review_cnt", "할인율", "log_price"]:
        d[f"L_{c}"] = g[c].shift()
    d["L_di"] = g["di"].shift()
    d["gap"] = d["di"] - d["L_di"]
    d = d[d["gap"] == MAX_GAP].copy()
    d["d_rank"] = d["ln_rank"] - d["L_ln_rank"]
    d["d_vel"] = d["velocity_log"] - d["L_velocity_log"]
    return d


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-05")
    args = ap.parse_args()

    p = build_panel(args.start, None)
    d = make_lags(p)
    last = p["수집일자"].max().date()

    R: list[str] = []
    def w(s: str = "") -> None:
        R.append(s)

    days = sorted(d["수집일자"].dt.date.unique())
    n_days = p["수집일자"].nunique()
    w("T4. 동적 패널 — 선후관계 접근 (잠정)")
    w(f"패널: {p['수집일자'].min().date()} ~ {last} · 카테고리 수집일 {n_days}일 "
      f"· 시차 가능 관측 {len(d):,}행 · 상품 {d['상품번호'].nunique():,}개")
    w("종속변수는 사양마다 다르다. 계수는 1 within-SD 당 변화, 상품 클러스터 SE")
    w("=" * 78)
    w()

    w("■ 0. 선행 조건 점검")
    w(f"    TASKS.md 권장: 카테고리 패널 3주치(8/26 이후). 현재 {n_days}일 "
      f"({'미충족' if n_days < 15 else '충족'})")
    w("    → 이하 결과는 잠정치다. 검정력 부족으로 '유의하지 않음'이 '효과 없음'을")
    w("      뜻하지 않는다는 점을 결론에 반드시 명시할 것.")
    w()

    # --- 1. 방향 A: 전기 유입 → 당기 순위 변화 ---------------------------
    w("■ 1. 방향 A — 전기 유입이 당기 순위 변화를 예측하는가")
    w("    Δln(순위)_t ~ 유입_{t−1} + ln(순위)_{t−1} + 통제")
    a1 = fe_ols(d, ["L_velocity_log", "L_ln_rank", "L_log_review_cnt",
                    "L_할인율", "L_log_price"], y_col="d_rank")
    w(f"    N={a1.n:,}  within R²={a1.r2w:.4f}")
    w(f"    {'변수':<18}{'beta':>9}{'t(클러스터)':>13}{'p':>10}{'VIF':>7}")
    for nm, b, tc, v in zip(a1.names, a1.beta, a1.tc, a1.vifs):
        w(f"    {nm:<18}{b:>+9.4f}{tc:>+13.2f}"
          f"{2 * stats.norm.sf(abs(tc)):>10.4f}{v:>7.2f}")
    w("    ※ ln(순위)_{t−1} 계수는 평균회귀를 흡수한다. 시차 종속변수를 고정효과와")
    w("      함께 넣었으므로 Nickell bias 로 이 계수는 음(−)으로 과대 추정된다.")
    w()

    # --- 2. 방향 B: 전기 순위 → 당기 유입 --------------------------------
    w("■ 2. 방향 B — 전기 순위가 당기 유입을 예측하는가")
    w("    유입_t ~ ln(순위)_{t−1} + 유입_{t−1} + 통제")
    b1 = fe_ols(d, ["L_ln_rank", "L_velocity_log", "L_log_review_cnt",
                    "L_할인율", "L_log_price"], y_col="velocity_log")
    w(f"    N={b1.n:,}  within R²={b1.r2w:.4f}")
    w(f"    {'변수':<18}{'beta':>9}{'t(클러스터)':>13}{'p':>10}{'VIF':>7}")
    for nm, b, tc, v in zip(b1.names, b1.beta, b1.tc, b1.vifs):
        w(f"    {nm:<18}{b:>+9.4f}{tc:>+13.2f}"
          f"{2 * stats.norm.sf(abs(tc)):>10.4f}{v:>7.2f}")
    w()

    # --- 3. 시차 종속변수 제외 사양 ---------------------------------------
    w("■ 3. Nickell bias 회피 — 시차 종속변수를 뺀 사양")
    a2 = fe_ols(d, ["L_velocity_log", "L_log_review_cnt", "L_할인율", "L_log_price"],
                y_col="d_rank")
    b2 = fe_ols(d, ["L_ln_rank", "L_log_review_cnt", "L_할인율", "L_log_price"],
                y_col="velocity_log")
    ia = a2.names.index("L_velocity_log")
    ib = b2.names.index("L_ln_rank")
    w(f"    방향 A: 전기 유입 → Δ순위    beta={a2.beta[ia]:+.4f}  "
      f"t={a2.tc[ia]:+.2f}")
    w(f"    방향 B: 전기 순위 → 당기 유입  beta={b2.beta[ib]:+.4f}  "
      f"t={b2.tc[ib]:+.2f}")
    w()

    # --- 4. 양방향 비교 ---------------------------------------------------
    w("■ 4. 양방향 강도 비교")
    w(f"    {'사양':<26}{'A: 유입→순위':>16}{'B: 순위→유입':>16}")
    w(f"    {'시차 종속변수 포함':<26}"
      f"{a1.tc[a1.names.index('L_velocity_log')]:>+16.2f}"
      f"{b1.tc[b1.names.index('L_ln_rank')]:>+16.2f}")
    w(f"    {'시차 종속변수 제외':<26}{a2.tc[ia]:>+16.2f}{b2.tc[ib]:>+16.2f}")
    w("    (t 는 상품 클러스터 기준. 부호 해석: 방향 A 는 음수면 '전기 유입이 많을수록")
    w("     당기 순위가 상승', 방향 B 는 음수면 '전기 순위가 좋을수록 당기 유입 증가')")
    w()

    ta, tb = abs(a2.tc[ia]), abs(b2.tc[ib])
    w("■ 5. 판정")
    sig_a, sig_b = ta > 2, tb > 2
    if sig_a and sig_b:
        w(f"    양방향 모두 유의하다 (|t| A={ta:.1f}, B={tb:.1f}).")
        w(f"    상대 강도는 {'A(유입→순위)' if ta > tb else 'B(순위→유입)'} 쪽이 크다.")
        w("    피드백 루프의 존재와 비대칭을 함께 서술할 수 있다.")
    elif sig_a:
        w(f"    방향 A 만 유의하다 (|t|={ta:.1f}). 전기 유입이 당기 순위 변화를 예측한다.")
    elif sig_b:
        w(f"    방향 B 만 유의하다 (|t|={tb:.1f}). 순위가 유입을 부르는 경로가 관측된다.")
        w("    반대로 유입이 순위를 예측하는 신호는 확인되지 않는다.")
    else:
        w(f"    양방향 모두 유의하지 않다 (|t| A={ta:.1f}, B={tb:.1f}).")
    w()
    w("    ⚠ 해석 제약")
    w("      · 패널이 2주 수준이라 검정력이 낮다. 유의하지 않음 ≠ 효과 없음.")
    w("      · T가 짧아 Nickell bias 가 크다. 시차 종속변수 포함 사양의 계수는")
    w("        그대로 인용하지 말 것.")
    w("      · 유입은 구매보다 며칠~몇 주 늦게 발생하므로, 1일 시차는 실제 선후관계를")
    w("        포착하기에 너무 짧을 수 있다. 이것이 방향 A 가 약하게 나오는 이유일 수 있다.")
    w("      · 랭킹이 판매액순(4.4.5)이므로 '순위→유입'은 '판매→리뷰'로 읽어야 한다.")
    w("      · Granger 스타일 예측 관계이며 인과가 아니다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"dynamic_panel_{last}.txt")
    text = "\n".join(R)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
