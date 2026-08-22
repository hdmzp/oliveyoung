"""결과보고서용 그림 생성 — 현재 수집 데이터로 매번 다시 그린다.

보고서의 모든 그림은 이 모듈 하나로 재생성된다. 데이터가 더 쌓이면
python -m analysis.figures 를 다시 실행하고 보고서를 재빌드하면 된다.

사용:  python -m analysis.figures
출력:  analysis/output/figures/fig*.png
"""
from __future__ import annotations

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .growth import (OUT_DIR, DV, build_panel, load_rankings, product_velocity,
                     fe_ols, residualize, spearman)

FIG_DIR = os.path.join(OUT_DIR, "figures")

plt.rcParams.update({
    "font.family": "Malgun Gothic",
    "axes.unicode_minus": False,
    "figure.dpi": 150,
    "savefig.dpi": 150,
    "savefig.bbox": "tight",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.6,
    "font.size": 10,
})

INK = "#2b2b2b"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
GRAY = "#9a9a94"
TEAL = "#1baf7a"
RED = "#d03b3b"


def save(fig, name):
    os.makedirs(FIG_DIR, exist_ok=True)
    path = os.path.join(FIG_DIR, name)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    print(f"  {name}")
    return path


# ---------------------------------------------------------------- 그림들

def fig_churn(rank):
    """일별 신규 진입 수. 로컬 수집 구간에 월초(8/1)가 없어 최다일을 강조한다."""
    ov = (rank[rank["카테고리"] == "전체"]
          .drop_duplicates(subset=["수집일자", "상품번호"]))
    days = sorted(ov["수집일자"].unique())
    sets = {d: set(ov[ov["수집일자"] == d]["상품번호"]) for d in days}
    rows = []
    for a, b in zip(days[:-1], days[1:]):
        if (b - a) / np.timedelta64(1, "D") != 1:
            continue
        rows.append((pd.Timestamp(b), len(sets[b] - sets[a])))
    df = pd.DataFrame(rows, columns=["day", "new"])
    top = df["new"].idxmax()
    fig, ax = plt.subplots(figsize=(8.8, 3.2))
    colors = [ORANGE if i == top else BLUE for i in df.index]
    ax.bar(df["day"], df["new"], color=colors, width=0.7)
    ax.annotate(f"최다 {df.loc[top, 'new']}개",
                (df.loc[top, "day"], df.loc[top, "new"]),
                textcoords="offset points", xytext=(0, 7), ha="center",
                fontsize=9.5, color=ORANGE, fontweight="bold")
    mean = df["new"].mean()
    ax.axhline(mean, color=GRAY, ls="--", lw=1)
    ax.set_ylim(0, df["new"].max() * 1.3)
    ax.annotate(f"하루 평균 {mean:.0f}개 교체", (df["day"].iloc[-1], mean),
                textcoords="offset points", xytext=(-4, 7), ha="right",
                fontsize=9.5, color=GRAY)
    ax.set_ylabel("신규 진입 수", labelpad=8)
    ax.set_title("전체 100위 안에서 하루에만 30여 개가 새 얼굴로 바뀐다",
                 loc="left", fontsize=11, color=INK, pad=10)
    fig.autofmt_xdate(rotation=45, ha="right")
    return save(fig, "fig1_churn.png")


def fig_retention(p):
    """당일 순위 구간별 익일 잔류율."""
    days = pd.Index(sorted(p["수집일자"].unique()))
    di = {d: i for i, d in enumerate(days)}
    q = p.copy()
    q["di"] = q["수집일자"].map(di)
    # 수집이 하루 건너뛴 구간은 제외해 본문 수치와 기준을 맞춘다
    gap1 = {i for i, (a, b) in enumerate(zip(days[:-1], days[1:]))
            if (b - a) / pd.Timedelta(days=1) == 1}
    present = set(zip(q["di"], q["카테고리"], q["상품번호"]))
    q["stay"] = [(i + 1, c, g) in present
                 for i, c, g in zip(q["di"], q["카테고리"], q["상품번호"])]
    q = q[q["di"].isin(gap1)]
    bins = [(1, 10), (11, 25), (26, 50), (51, 75), (76, 100)]
    labs, vals = [], []
    for lo, hi in bins:
        s = q[(q["순위"] >= lo) & (q["순위"] <= hi)]
        labs.append(f"{lo}–{hi}위")
        vals.append(s["stay"].mean() * 100)
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    cols = [BLUE if v >= 70 else (GRAY if v >= 55 else ORANGE) for v in vals]
    b = ax.bar(labs, vals, color=cols, width=0.6)
    ax.bar_label(b, fmt="%.0f%%", padding=3, fontsize=10)
    ax.set_ylim(0, 105)
    ax.set_ylabel("다음 날에도 100위 안에 남는 비율")
    ax.set_title("상위권일수록 자리를 지킨다", loc="left", fontsize=11,
                 color=INK, pad=10)
    return save(fig, "fig2_retention.png")


def fig_variance(p):
    """리뷰 총량 vs 리뷰 증가속도 — 설명력 분해."""
    cc = p.dropna(subset=[DV, "log_review_cnt", "velocity_log"])
    only_s = fe_ols(cc, ["log_review_cnt"]).r2w * 100
    only_v = fe_ols(cc, ["velocity_log"]).r2w * 100
    both = fe_ols(cc, ["log_review_cnt", "velocity_log"]).r2w * 100
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    labs = ["리뷰 총량만", "리뷰 증가속도만", "둘 다"]
    vals = [only_s, only_v, both]
    cols = [GRAY, BLUE, BLUE]
    b = ax.barh(labs, vals, color=cols, height=0.55)
    ax.bar_label(b, fmt="%.1f%%", padding=4, fontsize=10)
    ax.set_xlim(0, max(vals) * 1.35)
    ax.invert_yaxis()
    ax.set_xlabel("같은 카테고리·같은 날 안에서 순위 차이를 설명하는 정도")
    ax.set_title("증가속도를 알면 총량은 더 보탤 것이 없다", loc="left",
                 fontsize=11, color=INK, pad=10)
    ax.annotate("총량을 추가해도\n설명력이 늘지 않는다",
                xy=(both, 2), xytext=(both * 0.55, 2.42),
                fontsize=9, color=ORANGE,
                arrowprops=dict(arrowstyle="->", color=ORANGE, lw=1.2))
    return save(fig, "fig3_variance.png")


def fig_rating(p):
    """평점 분포 — 천장효과."""
    r = p["리뷰별점"].dropna()
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.hist(r, bins=40, color=BLUE, alpha=0.85)
    ax.axvline(r.median(), color=ORANGE, lw=1.6)
    ax.annotate(f"중위 {r.median():.2f}점", (r.median(), ax.get_ylim()[1] * 0.85),
                textcoords="offset points", xytext=(8, 0), color=ORANGE,
                fontsize=10, fontweight="bold")
    ax.set_xlabel("상품 평균 별점")
    ax.set_ylabel("상품 수")
    ax.set_title("별점은 거의 모든 상품이 만점 근처에 몰려 있다", loc="left",
                 fontsize=11, color=INK, pad=10)
    return save(fig, "fig4_rating.png")


def fig_elasticity(p):
    """판매액순 판별 — 유입 탄력성 vs 가격 탄력성."""
    d = p.dropna(subset=["velocity", "혜택가", "순위"]).copy()
    d = d[(d["velocity"] >= 1) & (d["혜택가"] > 0)]
    d["ln_rank"] = np.log(d["순위"])
    d["ln_vol"] = np.log(d["velocity"])
    d["ln_price"] = np.log(d["혜택가"])
    r = fe_ols(d, ["ln_vol", "ln_price"], y_col="ln_rank", standardize=False)
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    labs = ["리뷰 증가속도\n(판매량을 대신하는 값)", "판매가격"]
    vals = [abs(r.beta[0]), abs(r.beta[1])]
    b = ax.barh(labs, vals, color=[BLUE, TEAL], height=0.5)
    ax.bar_label(b, fmt="%.2f", padding=4, fontsize=10)
    ax.set_xlim(0, max(vals) * 1.3)
    ax.invert_yaxis()
    ax.set_xlabel("순위에 미치는 영향력의 크기 (탄력성 절댓값)")
    ax.set_title("가격도 판매량만큼 순위에 반영된다 → 매출액 기준 랭킹",
                 loc="left", fontsize=11, color=INK, pad=10)
    return save(fig, "fig5_elasticity.png")


def fig_promo_event(p):
    """세일·쿠폰 부착 전후 순위 궤적 — 역인과."""
    d = p.dropna(subset=["순위"]).copy()
    d["ln_rank"] = np.log(d["순위"])
    d["unit"] = d["카테고리"].astype(str) + "|" + d["상품번호"].astype(str)
    days = pd.Index(sorted(d["수집일자"].unique()))
    di = {v: i for i, v in enumerate(days)}
    d["di"] = d["수집일자"].map(di)
    d["dm"] = d["ln_rank"] - d.groupby("unit")["ln_rank"].transform("mean")
    d = d.sort_values(["unit", "di"])
    g = d.groupby("unit", sort=False)
    fig, ax = plt.subplots(figsize=(7.6, 3.3))
    for badge, col in (("세일", ORANGE), ("쿠폰", BLUE)):
        d[badge] = pd.to_numeric(d[badge], errors="coerce")
        onset = (g[badge].shift(1) == 0) & (d[badge] == 1)
        ev = d.loc[onset, ["unit", "di"]].rename(columns={"di": "t0"})
        if len(ev) < 30:
            continue
        m = d.merge(ev, on="unit", how="inner")
        m["rel"] = m["di"] - m["t0"]
        m = m[m["rel"].between(-3, 3)]
        prof = m.groupby("rel")["dm"].mean()
        ax.plot(prof.index, prof.values, "-o", color=col, lw=2, ms=5,
                label=f"{badge} 부착 ({len(ev):,}건)")
    ax.axvline(0, color=GRAY, ls="--", lw=1)
    ax.axhline(0, color=GRAY, lw=0.8)
    lo, hi = ax.get_ylim()
    ax.annotate("배지가 붙은 날", (0, lo), textcoords="offset points",
                xytext=(8, 14), fontsize=9, color=GRAY)
    ax.set_xlabel("배지 부착일 기준 경과일")
    ax.set_ylabel("평소 순위 대비 (아래일수록 상위)")
    ax.invert_yaxis()
    ax.legend(frameon=False, fontsize=9)
    ax.set_title("세일은 순위가 떨어진 뒤에 붙는다", loc="left", fontsize=11,
                 color=INK, pad=10)
    return save(fig, "fig6_promo_event.png")


def fig_thumbnail(p, bank):
    """썸네일 특성별 영향력 — 통제 전후."""
    from .image_features import url_to_filename
    d = p.dropna(subset=["대표이미지URL"]).copy()
    d["file"] = [url_to_filename(u) for u in d["대표이미지URL"]]
    d = d.merge(bank, on="file", how="inner")
    F = ["edge_density", "colorfulness", "white_border_share", "saturation",
         "brightness"]
    KOR = {"edge_density": "구성 복잡도\n(글자·요소 많음)", "colorfulness": "색 다양성",
           "white_border_share": "흰 배경 비율", "saturation": "채도",
           "brightness": "밝기"}
    r1 = fe_ols(d, F)
    ctrl = ["velocity_log", "log_review_cnt", "log_price", "할인율"]
    r2 = fe_ols(d, F + ctrl)
    fig, ax = plt.subplots(figsize=(7.8, 3.4))
    y = np.arange(len(F))
    t1 = [abs(r1.tc[r1.names.index(f)]) for f in F]
    t2 = [abs(r2.tc[r2.names.index(f)]) for f in F]
    ax.barh(y - 0.19, t1, height=0.36, color=GRAY, label="판매 요인 통제 전")
    ax.barh(y + 0.19, t2, height=0.36, color=BLUE, label="통제 후")
    ax.axvline(2, color=RED, ls="--", lw=1.2)
    ax.annotate("이 선을 넘어야\n신뢰할 수 있는 신호", (2, len(F) - 0.4),
                textcoords="offset points", xytext=(8, 0), fontsize=9, color=RED)
    ax.set_yticks(y, [KOR[f] for f in F], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("통계적 신호의 강도")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.set_title("판매 요인을 걷어내면 '구성 복잡도'만 남는다", loc="left",
                 fontsize=11, color=INK, pad=10)
    return save(fig, "fig7_thumbnail.png")


def fig_direction(p):
    """선후관계 — 양방향 비교."""
    from .dynamic_panel import make_lags
    d = make_lags(p)
    a = fe_ols(d, ["L_velocity_log", "L_log_review_cnt", "L_할인율", "L_log_price"],
               y_col="d_rank")
    b = fe_ols(d, ["L_ln_rank", "L_log_review_cnt", "L_할인율", "L_log_price"],
               y_col="velocity_log")
    ta = abs(a.tc[a.names.index("L_velocity_log")])
    tb = abs(b.tc[b.names.index("L_ln_rank")])
    fig, ax = plt.subplots(figsize=(7.6, 2.9))
    labs = ["어제 리뷰가 늘면\n오늘 순위가 오르는가", "어제 순위가 높으면\n오늘 리뷰가 느는가"]
    b2 = ax.barh(labs, [ta, tb], color=[GRAY, BLUE], height=0.5)
    ax.bar_label(b2, fmt="%.1f", padding=4, fontsize=10)
    ax.axvline(2, color=RED, ls="--", lw=1.2)
    ax.annotate("신호 판정선(2)", (2, -0.55), textcoords="offset points",
                xytext=(6, 0), fontsize=9, color=RED)
    ax.set_xlim(0, max(ta, tb) * 1.25)
    ax.invert_yaxis()
    ax.set_xlabel("통계적 신호의 강도")
    ax.set_title("리뷰가 판매를 부르는 것이 아니라 판매가 리뷰를 부른다",
                 loc="left", fontsize=11, color=INK, pad=10)
    return save(fig, "fig8_direction.png")


def fig_category(p):
    """카테고리별 재현성 — 유입속도와 순위의 상관."""
    rows = []
    for cat, g in p.dropna(subset=["velocity_log"]).groupby("카테고리"):
        rhos = [spearman(x[DV], x["velocity_log"])
                for _, x in g.groupby("수집일자") if x["velocity_log"].nunique() > 2]
        if rhos:
            rows.append((cat, np.mean(rhos), np.min(rhos), np.max(rhos)))
    df = pd.DataFrame(rows, columns=["cat", "m", "lo", "hi"]).sort_values("m")
    fig, ax = plt.subplots(figsize=(7.6, 5.2))
    y = np.arange(len(df))
    ax.hlines(y, df["lo"], df["hi"], color=GRAY, lw=2, alpha=0.55)
    ax.plot(df["m"], y, "o", color=BLUE, ms=6)
    ax.axvline(0, color=INK, lw=1)
    ax.set_yticks(y, df["cat"], fontsize=9)
    ax.set_xlabel("리뷰 증가속도와 순위의 상관 (음수 = 빠를수록 상위)")
    ax.set_title("20개 카테고리 전부에서 같은 방향으로 나타난다", loc="left",
                 fontsize=11, color=INK, pad=10)
    return save(fig, "fig9_category.png")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("그림 생성 중...")
    rank = load_rankings()
    p = build_panel("2026-08-05", None)
    bank = pd.read_csv(os.path.join(OUT_DIR, "image_bank.csv"), encoding="utf-8-sig")
    fig_churn(rank)
    fig_retention(p)
    fig_variance(p)
    fig_rating(p)
    fig_elasticity(p)
    fig_promo_event(p)
    fig_thumbnail(p, bank)
    fig_direction(p)
    fig_category(p)
    print(f"저장 위치: {FIG_DIR}")


if __name__ == "__main__":
    main()
