"""대형 세일(올영세일) 이벤트 분석.

올리브영은 약 3개월 주기로 전사 대형 세일을 진행한다. 수집 기간 중 2026-08-30 에
프로모션 지표가 급변했고(할인율 17.0%→27.2%, 쿠폰 배지 0.24→0.91), 이 구간이
랭킹 구조를 어떻게 바꿨는지 검증한다.

세일은 '카테고리×일 안에서만 비교' 라는 본 분석의 식별 전략을 흔드는 사건이다.
같은 날 모든 상품이 동시에 할인에 들어가면 그날의 카테고리 평균이 통째로 이동하므로,
세일 효과는 고정효과에 흡수되어 사라진다. 따라서 여기서는 (a) 세일 전/중 구간을 나눠
같은 회귀를 각각 돌려 계수가 어떻게 달라지는지 비교하고, (b) 상품 단위 전후 변화를
직접 추적한다.

⚠ 한계: 수집 데이터가 세일 3일차(9/1)에서 끝나 세일 종료 후 반등을 관측하지 못했다.
   모든 결과는 잠정이다.

사용:  python -m analysis.sale_event
출력:  analysis/output/sale_event_<date>.txt + stdout
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from .build_dataset import load_rankings
from .growth import build_panel, OUT_DIR, DV
from .panel import fe

OVERALL = "전체"
BADGES = ["세일", "쿠폰", "증정", "오늘드림"]


# ------------------------------------------------------------ 세일 구간 탐지

def detect_sale(rank_all: pd.DataFrame, jump_pp: float = 5.0) -> tuple[pd.Timestamp, pd.DataFrame]:
    """일별 평균 할인율이 전일 대비 jump_pp 이상 뛴 날을 세일 시작일로 본다."""
    daily = (rank_all[rank_all["카테고리"] != OVERALL]
             .groupby("수집일자")
             .agg(할인율=("할인율", "mean"), **{b: (b, "mean") for b in BADGES})
             .reset_index())
    daily["할인율_증분"] = daily["할인율"].diff()
    jumps = daily[daily["할인율_증분"] >= jump_pp]
    start = jumps["수집일자"].iloc[0] if len(jumps) else None
    return start, daily


# ------------------------------------------------------------ 지표 비교 도구

def compare(pre: pd.Series, sale: pd.Series, fmt="{:.2f}") -> str:
    a, b = pre.mean(), sale.mean()
    d = b - a
    return f"{fmt.format(a):>8} → {fmt.format(b):>8}  ({d:+.2f})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jump", type=float, default=5.0, help="세일 판정 할인율 증분(%p)")
    args = ap.parse_args()

    rank_all = load_rankings()
    start, daily = detect_sale(rank_all, args.jump)
    if start is None:
        raise SystemExit("세일 구간을 탐지하지 못했습니다.")
    last = rank_all["수집일자"].max()
    L = []
    def out(s=""):
        print(s); L.append(s)

    out(f"대형 세일 이벤트 분석 — 세일 시작 {start.date()} · 데이터 종료 {last.date()}")
    out(f"(세일 구간 {(last - start).days + 1}일 관측 · 종료 후 미관측 → 잠정)")
    out()

    # ---------------------------------------------------- 1. 프로모션 구조 전환
    out("■ 1. 프로모션 구조의 전환 (카테고리 랭킹 전체 평균)")
    d = daily.copy()
    d["구간"] = np.where(d["수집일자"] >= start, "세일", "세일 전")
    win = d[d["수집일자"] >= start - pd.Timedelta(days=7)]
    out(f"    {'날짜':<12}{'할인율':>8}{'세일':>7}{'쿠폰':>7}{'증정':>7}")
    for _, r in win.iterrows():
        mark = " ◀ 세일 시작" if r["수집일자"] == start else ""
        out(f"    {r['수집일자'].strftime('%m-%d'):<12}{r['할인율']:>7.1f}%"
            f"{r['세일']:>7.2f}{r['쿠폰']:>7.2f}{r['증정']:>7.2f}{mark}")
    pre, sal = d[d["구간"] == "세일 전"], d[d["구간"] == "세일"]
    out()
    for c, f in [("할인율", "{:.1f}"), ("세일", "{:.2f}"), ("쿠폰", "{:.2f}"), ("증정", "{:.2f}")]:
        out(f"    {c:<8} {compare(pre[c], sal[c], f)}")

    # ---------------------------------------------------- 2. 랭킹 지형 변화
    out()
    out("■ 2. 랭킹 지형의 변화 (전체 TOP100 기준)")
    ov = rank_all[rank_all["카테고리"] == OVERALL].copy()
    days = sorted(ov["수집일자"].unique())
    rmap = {t: ov[ov["수집일자"] == t].set_index("상품번호")["순위"] for t in days}
    rows = []
    for i in range(1, len(days)):
        p, c = days[i - 1], days[i]
        gap = (c - p).days
        prev, cur = set(rmap[p].index), set(rmap[c].index)
        common = list(prev & cur)
        rho = rmap[p][common].rank().corr(rmap[c][common].rank()) if len(common) > 5 else np.nan
        rows.append({"날짜": c, "신규진입": len(cur - prev), "간격": gap, "rho": rho,
                     "구간": "세일" if c >= start else "세일 전"})
    tv = pd.DataFrame(rows)
    g = tv[tv["간격"] == 1].groupby("구간")
    out(f"    {'구간':<8}{'일평균 신규진입':>14}{'순위상관 ρ':>12}{'관측일':>8}")
    for k in ["세일 전", "세일"]:
        if k in g.groups:
            s = g.get_group(k)
            out(f"    {k:<8}{s['신규진입'].mean():>13.1f}개{s['rho'].mean():>12.3f}{len(s):>8}일")
    out()
    out("    세일 시작 전후 일별 상세:")
    for _, r in tv[tv["날짜"] >= start - pd.Timedelta(days=4)].iterrows():
        mark = " ◀" if r["날짜"] == start else ""
        rho = f"{r['rho']:.3f}" if pd.notna(r["rho"]) else "  –  "
        out(f"      {r['날짜'].strftime('%m-%d')}  신규 {int(r['신규진입']):>3}개  ρ={rho}{mark}")

    # ---------------------------------------------------- 3. 카테고리 판도
    out()
    out("■ 3. 세일 중 카테고리 구성 변화 (전체 TOP100 슬롯 점유율)")
    cat = rank_all[rank_all["카테고리"] != OVERALL]
    gmap = (cat.sort_values("수집일자").drop_duplicates("상품번호", keep="last")
               .set_index("상품번호")["카테고리"])
    ov2 = ov.copy()
    ov2["mc"] = ov2["상품번호"].map(gmap).fillna("(미매핑)")
    ov2["구간"] = np.where(ov2["수집일자"] >= start, "세일", "세일 전")
    share = (ov2.groupby(["구간", "mc"]).size()
               / ov2.groupby("구간").size() * 100).unstack(0).fillna(0)
    share["변화"] = share.get("세일", 0) - share.get("세일 전", 0)
    share = share.sort_values("변화", ascending=False)
    out(f"    {'카테고리':<14}{'세일 전':>9}{'세일':>9}{'변화':>9}")
    for name, r in pd.concat([share.head(5), share.tail(4)]).iterrows():
        out(f"    {name:<14}{r.get('세일 전', 0):>8.1f}%{r.get('세일', 0):>8.1f}%{r['변화']:>+8.1f}%p")

    # ---------------------------------------------------- 4. 리뷰 유입 반응
    out()
    out("■ 4. 리뷰 유입 속도의 반응 (카테고리 패널)")
    p = build_panel(end=None)
    p["구간"] = np.where(p["수집일자"] >= start, "세일", "세일 전")
    vv = p.dropna(subset=["velocity"])
    gv = vv.groupby("구간")["velocity"]
    out(f"    {'구간':<8}{'중위 유입/일':>13}{'평균':>10}{'관측':>9}")
    for k in ["세일 전", "세일"]:
        if k in gv.groups:
            s = gv.get_group(k)
            out(f"    {k:<8}{s.median():>12.1f}{s.mean():>10.1f}{len(s):>9,}")
    med_pre = gv.get_group("세일 전").median() if "세일 전" in gv.groups else np.nan
    med_sal = gv.get_group("세일").median() if "세일" in gv.groups else np.nan
    if pd.notna(med_pre) and med_pre > 0:
        out(f"    → 중위 유입 {med_sal / med_pre:.2f}배")

    # ---------------------------------------------------- 5. 계수 구조 변화
    out()
    out("■ 5. 순위 결정 구조는 바뀌었나 — 구간별 동일 회귀 비교")
    out("    (카테고리×일 고정효과, 상품 단위 클러스터 SE, 표준화 계수)")
    xs = ["velocity_pct", "log_review_cnt", "할인율", "log_price", "쿠폰"]
    for k, sub in [("세일 전", p[p["구간"] == "세일 전"]), ("세일", p[p["구간"] == "세일"])]:
        s = sub.dropna(subset=[DV] + xs + ["cat_day", "상품번호"])
        if len(s) < 200:
            out(f"    [{k}] 관측 부족 (N={len(s)})"); continue
        r = fe(s, xs, ["cat_day"], cluster="상품번호")
        out(f"    [{k}] N={r.n:,}  within R²={r.r2w:.3f}")
        for nm, b, t in zip(r.names, r.beta, r.t_clu):
            out(f"        {nm:<16} beta={b:+7.2f}  t={t:+6.2f}")

    # ---------------------------------------------------- 6. 세일 수혜 상품
    out()
    out("■ 6. 세일 구간 순위 급상승 상품 (전체 TOP100, 세일 직전 대비)")
    before = start - pd.Timedelta(days=1)
    if before in rmap and last in rmap:
        b0, a0 = rmap[before], rmap[last]
        common = list(set(b0.index) & set(a0.index))
        mv = pd.DataFrame({"before": b0[common], "after": a0[common]})
        mv["상승"] = mv["before"] - mv["after"]
        info = ov[ov["수집일자"] == last].set_index("상품번호")
        top = mv.nlargest(8, "상승")
        out(f"    {'상품':<44}{'세일 전':>7}{'현재':>6}{'상승':>7}{'할인율':>8}")
        for gno, r in top.iterrows():
            nm = (info.loc[gno, "브랜드"] + " " + info.loc[gno, "상품명"])[:42].replace("\xa0", " ")
            dc = info.loc[gno, "할인율"]
            out(f"    {nm:<44}{int(r['before']):>7}{int(r['after']):>6}{int(r['상승']):>+7}{dc:>7.0f}%")
        newly = set(a0.index) - set(b0.index)
        out(f"    세일 개시 후 신규 진입 누적: {len(newly)}개 / TOP100")

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"sale_event_{last.date()}.txt")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"\n저장: {path}")


if __name__ == "__main__":
    main()
