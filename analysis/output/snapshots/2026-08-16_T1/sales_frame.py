"""랭킹의 정체 검증 — 판매액순인가 판매량순인가.

랭킹 페이지(getBestList.do)는 '판매랭킹'이지만 집계 기준이 공개돼 있지 않다.
판매액(매출)순이냐 판매량(개수)순이냐에 따라 이후 모든 분석의 해석이 달라지므로
먼저 이것부터 가른다.

식별 아이디어
-------------
리뷰는 '산 사람'이 쓰므로 리뷰 유입은 대체로 **판매량**에 비례한다(전환율 배).
판매액 = 판매량 × 가격 이고, 순위는 판매 지표의 멱함수라고 보면

    ln(순위) = a - b1·ln(판매량) - b2·ln(가격)

  · 판매량순  → b2 ≈ 0        (가격은 순위와 무관해야 함)
  · 판매액순  → b1 ≈ b2       (판매량과 가격이 같은 탄력성으로 들어와야 함)

따라서 (1) b2 = 0 검정, (2) b1 = b2 검정 두 개로 판별한다. 추가로 제약 모형
ln(순위) ~ ln(판매량 × 가격) 이 무제약 모형과 설명력이 같은지도 본다.

⚠ 전제: 리뷰 전환율(판매 1건당 리뷰 확률)이 가격대에 따라 체계적으로 다르면
   b2 가 편향된다. 이 한계는 리포트에 함께 출력한다.

사용:  python -m analysis.sales_frame
출력:  analysis/output/sales_frame_<date>.txt + stdout
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from .growth import OUT_DIR, build_panel, fe_ols


def prep(p: pd.DataFrame) -> pd.DataFrame:
    d = p.dropna(subset=["velocity", "혜택가", "순위"]).copy()
    d = d[(d["velocity"] >= 1) & (d["혜택가"] > 0)]     # 순수 로그를 쓰기 위해
    d["ln_rank"] = np.log(d["순위"])
    d["ln_vol"] = np.log(d["velocity"])                 # 판매량 대리
    d["ln_price"] = np.log(d["혜택가"])
    d["ln_revenue"] = d["ln_vol"] + d["ln_price"]       # 판매액 대리(제약 모형)
    return d


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

    w("랭킹의 정체 검증 — 판매액순인가 판매량순인가")
    w(f"표본: {d['수집일자'].min().date()} ~ {d['수집일자'].max().date()} · "
      f"{len(d):,}행 · 상품 {d['상품번호'].nunique():,}개 "
      f"(리뷰 유입 1건/일 이상인 관측만)")
    w("모형: ln(순위) ~ ln(리뷰유입) + ln(혜택가), 카테고리×일 고정효과, "
      "상품 클러스터 SE")
    w("계수는 탄력성 — 값이 음수면 '클수록 상위권'")
    w("=" * 78)
    w()

    w("■ 0. 판별 기준")
    w("    리뷰 유입 ∝ 판매량 이라고 보면")
    w("      판매량순  → 가격 탄력성 ≈ 0")
    w("      판매액순  → 가격 탄력성 ≈ 유입 탄력성 (둘이 같아야 함)")
    w()

    w("■ 1. 개별 모형")
    for lab, xs in [("V  유입만 (판매량 가설)", ["ln_vol"]),
                    ("P  가격만", ["ln_price"]),
                    ("U  유입 + 가격 (무제약)", ["ln_vol", "ln_price"]),
                    ("R  ln(유입×가격) (판매액 제약)", ["ln_revenue"])]:
        r = fe_ols(d, xs, y_col="ln_rank", standardize=False)
        w(f"  {lab}")
        w(f"    N={r.n:,}  within R²={r.r2w:.4f}")
        for nm, b, tc in zip(r.names, r.beta, r.tc):
            w(f"      {nm:<12} 탄력성={b:+7.4f}  t(클러스터)={tc:+7.2f}")
        w()

    u = fe_ols(d, ["ln_vol", "ln_price"], y_col="ln_rank", standardize=False)
    rr = fe_ols(d, ["ln_revenue"], y_col="ln_rank", standardize=False)

    w("■ 2. 판별 검정")
    b_vol, b_pri = u.beta[0], u.beta[1]
    _, t0, p0 = u.contrast({"ln_price": 1.0})
    est, t1, p1 = u.contrast({"ln_vol": 1.0, "ln_price": -1.0})
    w(f"    (1) 가격 탄력성 = 0 인가?   추정 {b_pri:+.4f}  t={t0:+.2f}  p={p0:.4f}")
    w(f"        → {'기각: 가격이 순위에 들어간다 (판매량순 아님)' if p0 < .05 else '기각 못함: 판매량순과 정합'}")
    w(f"    (2) 유입 탄력성 = 가격 탄력성 인가?  차이 {est:+.4f}  t={t1:+.2f}  p={p1:.4f}")
    w(f"        → {'기각: 두 탄력성이 다르다 (단순 판매액순 아님)' if p1 < .05 else '기각 못함: 판매액순과 정합'}")
    w(f"    (3) 제약 모형 설명력 손실: 무제약 R²={u.r2w:.4f} vs 제약 R²={rr.r2w:.4f} "
      f"(차이 {u.r2w - rr.r2w:+.4f})")
    w(f"    참고: 탄력성 비 (가격/유입) = {b_pri / b_vol:.2f}  "
      f"(1.0 이면 완전한 판매액순)")
    w()

    w("■ 3. 카테고리별 재현성 (가격 탄력성)")
    w(f"    {'카테고리':<14}{'N':>7}{'유입 탄력성':>13}{'가격 탄력성':>13}{'가격 t':>9}")
    rows = []
    for cat, g in d.groupby("카테고리"):
        if len(g) < 300 or g["ln_price"].std() == 0:
            continue
        r = fe_ols(g, ["ln_vol", "ln_price"], y_col="ln_rank",
                   group="수집일자", standardize=False)
        rows.append((cat, r.n, r.beta[0], r.beta[1], r.tc[1]))
    for cat, n, bv, bp, tp in sorted(rows, key=lambda x: x[3]):
        w(f"    {cat:<14}{n:>7,}{bv:>+13.4f}{bp:>+13.4f}{tp:>+9.2f}")
    neg = sum(1 for r_ in rows if r_[3] < 0)
    w(f"    → 가격 탄력성이 음수(비쌀수록 상위)인 카테고리: {neg}/{len(rows)}개")
    w()

    w("■ 4. 해석 주의 — 이 검정이 틀릴 수 있는 경로")
    w("    · 리뷰 전환율이 가격대에 따라 다르면(고가품일수록 리뷰를 더/덜 쓴다면)")
    w("      가격 탄력성이 판매액 효과가 아니라 전환율 차이를 잡는다. 이게 가장 큰 위험.")
    w("    · 가격은 브랜드·품질·카테고리 내 포지션과 얽혀 있다. 고가 라인이 잘 팔리는")
    w("      브랜드의 것이면 가격 계수는 브랜드 효과의 대리가 된다 (T2 의 브랜드 통제 필요).")
    w("    · 리뷰 유입은 구매 시점보다 며칠~몇 주 늦게 발생하므로 당일 판매량의")
    w("      정확한 대리가 아니다. 유입 탄력성이 감쇠(attenuation)되면 비율이 부풀려진다.")
    w("    · TOP100 절단 표본이라 순위 하위의 판매 분포를 못 본다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"sales_frame_{last}.txt")
    text = "\n".join(R)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
