"""H2. 프로모션이 붙은 날 순위가 오르는가 — 상품 내(within-product) 비교.

리뷰 관련 변수는 상품 내에서 거의 변하지 않아 상품 고정효과 안에서는 식별되지
않는다(상품 내 Δ순위 ↔ Δ유입 상관 ≈ 0). 반면 배지(세일/쿠폰/증정/오늘드림)와
할인율은 **날마다 바뀐다.** 따라서 "같은 상품이 쿠폰 붙은 날과 안 붙은 날"을
비교하는 진짜 within-product 설계가 가능하다.

설계
----
  ln(순위) ~ 배지 + 할인율 + [상품×카테고리 고정효과] + [날짜 고정효과]

상품×카테고리 고정효과가 상품의 고유 인기도·브랜드·가격대를 전부 흡수하고,
날짜 고정효과가 전체 시장 변동(주말·월초 리셋 등)을 흡수한다. 남는 것은
"같은 상품이, 같은 날 시장 조건에서, 프로모션 유무에 따라" 달라진 부분이다.

⚠ 식별의 한계: 프로모션은 무작위 배정이 아니다. 잘 팔릴 것 같은 시점에 맞춰
   기획되면(수요 예측 기반 편성) 계수는 프로모션 효과가 아니라 기대 수요를 잡는다.
   이건 이 데이터로는 배제할 수 없다 — 반드시 함께 서술할 것.

사용:  python -m analysis.promo
출력:  analysis/output/promo_<date>.txt + stdout
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from .growth import OUT_DIR, build_panel, fe_ols

BADGES = ["세일", "쿠폰", "증정", "오늘드림"]


def prep(p: pd.DataFrame) -> pd.DataFrame:
    d = p.dropna(subset=["순위", "혜택가"]).copy()
    d = d[d["혜택가"] > 0]
    d["ln_rank"] = np.log(d["순위"])
    d["ln_price"] = np.log(d["혜택가"])
    d["unit"] = d["카테고리"].astype(str) + "|" + d["상품번호"].astype(str)
    d["day"] = d["수집일자"].dt.strftime("%Y-%m-%d")
    for b in BADGES:
        d[b] = pd.to_numeric(d[b], errors="coerce")
    return d.dropna(subset=BADGES + ["할인율"])


def day_dummies(d: pd.DataFrame) -> pd.DataFrame:
    dd = pd.get_dummies(d["day"], prefix="d", drop_first=True).astype(float)
    dd.index = d.index
    return dd


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
    d = prep(p)
    last = p["수집일자"].max().date()

    R: list[str] = []
    def w(s: str = "") -> None:
        R.append(s)

    w("H2. 프로모션이 붙은 날 순위가 오르는가 — 상품 내 비교")
    w(f"표본: {d['day'].min()} ~ {d['day'].max()} · {len(d):,}행 · "
      f"상품×카테고리 단위 {d['unit'].nunique():,}개")
    w("모형: ln(순위) ~ 프로모션 + 상품×카테고리 FE + 날짜 FE, 상품 클러스터 SE")
    w("계수 음수 = 순위 상승(상위권). 대략 '순위 몇 % 개선'으로 읽는다.")
    w("=" * 78)
    w()

    # --- 0. 식별 가능성 진단 ------------------------------------------
    w("■ 0. 식별 가능성 — 상품 내에서 실제로 변하는가")
    w("    (변하지 않으면 상품 고정효과가 그 변수를 통째로 흡수해 추정 불가)")
    w(f"    {'변수':<10}{'전체 평균':>10}{'변화 있는 단위':>15}{'비율':>8}")
    usable = []
    g = d.groupby("unit")
    n_units = d["unit"].nunique()
    for b in BADGES + ["할인율"]:
        sw = (g[b].nunique() > 1).sum()
        w(f"    {b:<10}{d[b].mean():>10.3f}{sw:>15,}{sw / n_units:>8.1%}")
        if sw >= 50:
            usable.append(b)
    w(f"    → 추정 가능한 변수: {', '.join(usable) if usable else '없음'}")
    w()

    if not usable:
        w("변화하는 프로모션 변수가 없어 within-product 추정이 불가능하다.")
    else:
        dd = day_dummies(d)

        w("■ 1. 상품×카테고리 FE + 날짜 FE")
        r = fe_ols(d, usable, y_col="ln_rank", group="unit",
                   standardize=False, extra=dd)
        w(f"    N={r.n:,}  단위={r.ngroups:,}  within R²={r.r2w:.4f}")
        w(f"    {'변수':<10}{'계수':>10}{'t(클러스터)':>13}{'해석':>22}")
        for nm, b, tc in zip(r.names, r.beta, r.tc):
            if nm.startswith("d_"):
                continue
            eff = (np.exp(b) - 1) * 100
            w(f"    {nm:<10}{b:>+10.4f}{tc:>+13.2f}"
              f"{f'순위 {eff:+.1f}%':>22}")
        w()

        w("■ 2. 가격을 함께 통제 (할인은 가격을 낮추므로 경로가 겹친다)")
        r2 = fe_ols(d, usable + ["ln_price"], y_col="ln_rank", group="unit",
                    standardize=False, extra=dd)
        w(f"    N={r2.n:,}  within R²={r2.r2w:.4f}")
        for nm, b, tc in zip(r2.names, r2.beta, r2.tc):
            if nm.startswith("d_"):
                continue
            w(f"    {nm:<10}{b:>+10.4f}{tc:>+13.2f}")
        w("    ※ 가격을 넣으면 '할인으로 싸져서 잘 팔린 경로'가 가격 쪽으로 빠진다.")
        w("      배지 계수는 '가격 인하와 별개인 노출·프레이밍 효과'로 좁혀 읽어야 한다.")
        w()

        # --- 3. 이벤트: 배지가 새로 붙은 날 전후 -----------------------
        w("■ 3. 배지가 새로 붙은 시점 전후 순위 궤적")
        w("    (단위별 평균을 뺀 ln(순위). 음수 = 그 단위의 평소보다 상위)")
        d2 = d.sort_values(["unit", "수집일자"]).copy()
        d2["ln_rank_dm"] = d2["ln_rank"] - d2.groupby("unit")["ln_rank"].transform("mean")
        for b in [x for x in usable if x in BADGES]:
            gg = d2.groupby("unit", sort=False)[b]
            onset = (gg.shift(1) == 0) & (d2[b] == 1)
            ev = d2.loc[onset, ["unit", "수집일자"]].rename(
                columns={"수집일자": "t0"})
            if len(ev) < 30:
                w(f"    {b}: 신규 부착 사건 {len(ev)}건 — 표본 부족, 생략")
                continue
            m = d2.merge(ev, on="unit", how="inner")
            m["rel"] = (m["수집일자"] - m["t0"]).dt.days
            m = m[m["rel"].between(-3, 3)]
            prof = m.groupby("rel")["ln_rank_dm"].agg(["mean", "size"])
            w(f"    {b} (신규 부착 {len(ev):,}건)")
            w("      " + "  ".join(f"{int(k):+d}일:{v:+.3f}"
                                   for k, v in prof["mean"].items()))
        w()

    w("■ 4. 해석 주의")
    w("    · 프로모션은 무작위가 아니다. 잘 팔릴 시점에 맞춰 편성되면 계수는")
    w("      '프로모션 효과'가 아니라 '기대 수요'를 잡는다. 이 데이터로는 배제 불가.")
    w("    · 배지는 랭킹 페이지에 표시된 것이라 실제 프로모션의 부분집합일 수 있다.")
    w("    · 하루 1회 스냅샷이라 하루 안의 프로모션 시작/종료는 관측되지 않는다.")
    w("    · TOP100 밖으로 떨어진 상품은 관측이 끊긴다(절단) — 프로모션 종료 후")
    w("      급락한 사례가 표본에서 사라져 효과가 과소추정될 수 있다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"promo_{last}.txt")
    text = "\n".join(R)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
