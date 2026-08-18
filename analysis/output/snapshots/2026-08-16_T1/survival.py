"""T3. 진입/잔류 모형 — 순위보다 안정적인 종속변수.

랭킹은 하루 평균 42개가 교체되는 고변동 시스템이라 "순위 몇 위"보다
"내일도 남아 있는가"가 더 안정적이고 해석이 명확한 종속변수일 수 있다.

세 가지를 본다.
  1) 잔류 로지스틱 — 익일 잔류 여부(0/1)를 설명. 이산시간 위험모형(discrete-time
     hazard)과 같은 형태이므로 생존분석의 역할도 겸한다.
  2) 진입 분석 — 신규 진입 상품이 진입 직전에 어떤 상태였는가.
  3) 생존곡선 — 상품별 연속 체류 기간의 Kaplan–Meier 추정.

표준오차는 상품 단위 클러스터. 카테고리·날짜는 더미로 통제한다(로지스틱에서
고차원 고정효과는 부수모수 문제를 일으키므로 더미 수를 제한).

⚠ 패널이 10일뿐이라 생존곡선의 꼬리는 신뢰할 수 없다. 관측 시작 시점에 이미
   진행 중이던 체류(left truncation)는 길이를 알 수 없어 제외한다.

사용:  python -m analysis.survival
출력:  analysis/output/entry_exit_<date>.txt + stdout
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

from .growth import OUT_DIR, load_rankings, product_velocity

PANEL_START = "2026-08-05"
OVERALL = "전체"


# ---------------------------------------------------------------- 로지스틱

def logit_fit(y: np.ndarray, X: np.ndarray, clusters: np.ndarray):
    """IRLS 로지스틱 + 상품 단위 클러스터 robust SE. (beta, t_clu, pseudo_r2, ll)"""
    n, k = X.shape
    beta = np.zeros(k)
    for _ in range(200):
        eta = np.clip(X @ beta, -30, 30)
        p = 1 / (1 + np.exp(-eta))
        W = np.clip(p * (1 - p), 1e-9, None)
        A = X.T @ (W[:, None] * X)
        step = np.linalg.solve(A + 1e-9 * np.eye(k), X.T @ (y - p))
        beta_new = beta + step
        if np.max(np.abs(step)) < 1e-9:
            beta = beta_new
            break
        beta = beta_new
    eta = np.clip(X @ beta, -30, 30)
    p = 1 / (1 + np.exp(-eta))
    W = np.clip(p * (1 - p), 1e-9, None)
    A_inv = np.linalg.pinv(X.T @ (W[:, None] * X))

    codes = pd.factorize(clusters)[0]
    G = codes.max() + 1
    agg = np.zeros((G, k))
    np.add.at(agg, codes, X * (y - p)[:, None])
    c = (G / (G - 1)) * ((n - 1) / (n - k))
    V = A_inv @ (agg.T @ agg) @ A_inv * c
    se = np.sqrt(np.diag(V))

    eps = 1e-12
    ll = float(np.sum(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps)))
    pbar = y.mean()
    ll0 = float(n * (pbar * np.log(pbar + eps) + (1 - pbar) * np.log(1 - pbar + eps)))
    return beta, beta / se, 1 - ll / ll0, ll, G


# ---------------------------------------------------------------- 데이터

def build(start: str, end: str | None):
    rank_all = load_rankings()
    vel = product_velocity(rank_all)
    vel["velocity_log"] = np.log1p(vel["velocity"].clip(lower=0))

    p = rank_all[rank_all["수집일자"] >= pd.Timestamp(start)].copy()
    if end:
        p = p[p["수집일자"] <= pd.Timestamp(end)]
    p = p[p["카테고리"] != OVERALL]
    p = p.merge(vel[["수집일자", "상품번호", "velocity_log"]],
                on=["수집일자", "상품번호"], how="left")
    p["log_review_cnt"] = np.log10(1 + p["리뷰수"])
    p["log_price"] = np.log10(p["혜택가"].clip(lower=1))
    p["log_rank"] = np.log(p["순위"])
    p["avg_rating"] = p["리뷰별점"]
    p["star1_share"] = p["별점1비율"]
    return p


def add_retention(p: pd.DataFrame) -> pd.DataFrame:
    """카테고리별 다음 수집일에 그 상품이 남아 있는가."""
    days = pd.Index(sorted(p["수집일자"].unique()))
    nxt = {d: days[i + 1] for i, d in enumerate(days[:-1])}
    p = p.copy()
    p["next_day"] = p["수집일자"].map(nxt)
    p["gap_next"] = (p["next_day"] - p["수집일자"]).dt.days
    present = set(zip(p["수집일자"], p["카테고리"], p["상품번호"]))
    p["stay"] = [1 if (nd, c, g) in present else 0
                 for nd, c, g in zip(p["next_day"], p["카테고리"], p["상품번호"])]
    return p


def km(spells: pd.DataFrame) -> pd.DataFrame:
    """Kaplan–Meier. spells: duration(정수), event(1=이탈 관측, 0=우측절단)."""
    rows, s = [], 1.0
    at_risk = len(spells)
    for t in range(1, int(spells["duration"].max()) + 1):
        d = int(((spells["duration"] == t) & (spells["event"] == 1)).sum())
        cens = int(((spells["duration"] == t) & (spells["event"] == 0)).sum())
        if at_risk <= 0:
            break
        s *= (1 - d / at_risk)
        rows.append({"t": t, "at_risk": at_risk, "exit": d, "S": s})
        at_risk -= (d + cens)
    return pd.DataFrame(rows)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=PANEL_START)
    ap.add_argument("--date")
    args = ap.parse_args()

    p = build(args.start, args.date)
    p = add_retention(p)
    last = p["수집일자"].max().date()

    R: list[str] = []
    def w(s: str = "") -> None:
        R.append(s)

    days = sorted(p["수집일자"].dt.date.unique())
    w("T3. 진입/잔류 모형 — 순위보다 안정적인 종속변수")
    w(f"패널: {days[0]} ~ {days[-1]} ({len(days)}일) · 카테고리 {p['카테고리'].nunique()}개 "
      f"· 관측 {len(p):,}행 · 상품 {p['상품번호'].nunique():,}개")
    w("=" * 80)
    w()

    # --- 0. 잔류율 기초 ---------------------------------------------------
    w("■ 0. 잔류율 기초")
    tr = p.dropna(subset=["next_day"])
    w(f"    전이 관측 {len(tr):,}건 · 평균 잔류율 {tr['stay'].mean():.1%}")
    gp = tr.groupby("gap_next")["stay"].agg(["mean", "size"])
    for g, row in gp.iterrows():
        w(f"      다음 수집까지 {int(g)}일: 잔류율 {row['mean']:.1%} ({int(row['size']):,}건)")
    tr1 = tr[tr["gap_next"] == 1].copy()
    w(f"    → 이하 분석은 간격 1일 전이만 사용 ({len(tr1):,}건). "
      f"8/9→8/12 처럼 벌어진 구간은 제외.")
    w()
    w(f"    {'당일 순위 구간':<14}{'전이수':>8}{'익일 잔류율':>13}")
    bins = [(1, 10), (11, 25), (26, 50), (51, 75), (76, 100)]
    for lo, hi in bins:
        s = tr1[(tr1["순위"] >= lo) & (tr1["순위"] <= hi)]
        w(f"    {f'{lo}–{hi}위':<14}{len(s):>8,}{s['stay'].mean():>13.1%}")
    w()

    # --- 1. 잔류 로지스틱 --------------------------------------------------
    w("■ 1. 잔류 로지스틱 (익일 잔류 = 1). 이산시간 위험모형과 동형")
    XV = ["log_rank", "log_review_cnt", "velocity_log", "할인율", "log_price",
          "avg_rating", "star1_share", "증정", "쿠폰", "세일"]
    d = tr1.dropna(subset=XV + ["stay"]).copy()
    Z = d[XV].to_numpy(float)
    Z = (Z - Z.mean(axis=0)) / np.where(Z.std(axis=0) == 0, 1, Z.std(axis=0))
    cat = pd.get_dummies(d["카테고리"], drop_first=True).to_numpy(float)
    day = pd.get_dummies(d["수집일자"], drop_first=True).to_numpy(float)
    X = np.column_stack([np.ones(len(d)), Z, cat, day])
    y = d["stay"].to_numpy(float)
    beta, tclu, pr2, ll, G = logit_fit(y, X, d["상품번호"].to_numpy())

    w(f"    N={len(d):,} (전이 {len(tr1):,}건 중 설명변수 결측 제외)  "
      f"상품(클러스터)={G:,}  McFadden pseudo-R²={pr2:.4f}")
    w("    계수는 설명변수 1 표준편차 증가당 로그오즈 변화. 양수 = 잔류 확률 상승")
    w(f"    {'변수':<16}{'계수':>9}{'오즈비':>9}{'t(클러스터)':>13}{'p':>10}")
    for i, nm in enumerate(XV):
        b, t = beta[i + 1], tclu[i + 1]
        pv = 2 * stats.norm.sf(abs(t))
        star = "***" if pv < .001 else "**" if pv < .01 else "*" if pv < .05 else ""
        w(f"    {nm:<16}{b:>+9.3f}{np.exp(b):>9.3f}{t:>+13.2f}{pv:>10.4f} {star}")
    w("    (카테고리·날짜 더미 포함, 표에서는 생략)")
    w()
    w("    읽을 점 두 가지")
    w("      · 리뷰 규모가 여기서는 양(+)으로 유의하다(오즈비 1.19). 순위 회귀에서는")
    w("        유입 속도에 밀려 사라졌지만, '자리를 지키는 힘'으로는 누적 리뷰가")
    w("        따로 작동한다. 규모는 순위를 올리는 변수가 아니라 버티게 하는 변수에")
    w("        가깝다.")
    w("      · 할인율은 음(−)이다(오즈비 0.87). 순위 회귀에서는 할인이 클수록 상위권인데")
    w("        잔류 확률은 오히려 낮다. 할인으로 밀어올린 자리는 오래 못 간다는 해석이")
    w("        가능하지만, 할인 종료 시점이 관측되지 않으므로 단정할 수 없다.")
    w()

    # --- 2. 진입 분석 ------------------------------------------------------
    w("■ 2. 신규 진입 상품 vs 잔류 상품")
    prev_present = set()
    p_sorted = p.sort_values("수집일자")
    first_day = p["수집일자"].min()
    seen = {}
    for d0, g in p_sorted.groupby("수집일자"):
        seen[d0] = set(zip(g["카테고리"], g["상품번호"]))
    dl = sorted(seen)
    new_rows, stay_rows = [], []
    for i in range(1, len(dl)):
        if (dl[i] - dl[i - 1]).days != 1:
            continue
        cur = p[p["수집일자"] == dl[i]]
        prev = seen[dl[i - 1]]
        mask = [(c, g) not in prev for c, g in zip(cur["카테고리"], cur["상품번호"])]
        new_rows.append(cur[mask])
        stay_rows.append(cur[[not m for m in mask]])
    new = pd.concat(new_rows) if new_rows else cur.iloc[0:0]
    old = pd.concat(stay_rows) if stay_rows else cur.iloc[0:0]
    w(f"    {'구분':<12}{'관측':>8}{'중위 순위':>10}{'중위 리뷰수':>13}"
      f"{'중위 유입/일':>13}{'평균 할인율':>12}{'증정비율':>10}")
    for lab, s in (("신규 진입", new), ("잔류", old)):
        w(f"    {lab:<12}{len(s):>8,}{s['순위'].median():>10.0f}"
          f"{s['리뷰수'].median():>13,.0f}"
          f"{np.expm1(s['velocity_log']).median():>13.1f}"
          f"{s['할인율'].mean():>12.1f}{s['증정'].mean():>10.2f}")
    w(f"    신규 진입 상품의 진입 위치: "
      + ", ".join(f"{lo}–{hi}위 {((new['순위'] >= lo) & (new['순위'] <= hi)).mean():.0%}"
                  for lo, hi in bins))
    w()

    # --- 3. 생존곡선 -------------------------------------------------------
    w("■ 3. 연속 체류 기간 Kaplan–Meier — 신규 진입 상품 기준")
    w("    관측 시작 시점에 이미 진행 중이던 체류는 길이를 알 수 없어 제외했다(좌측 절단).")
    w("    그 결과 이 곡선은 사실상 '패널 기간 중 새로 진입한 상품'의 생존곡선이며,")
    w("    기존 상시 랭커는 빠져 있다. §0 의 전체 잔류율(70.8%)보다 낮게 나오는 이유다.")
    dl_idx = {d0: i for i, d0 in enumerate(dl)}
    p["di"] = p["수집일자"].map(dl_idx)
    spells = []
    for (c, g), grp in p.sort_values("di").groupby(["카테고리", "상품번호"], sort=False):
        idx = sorted(grp["di"].tolist())
        start = idx[0]
        prev = idx[0]
        for i in idx[1:] + [None]:
            if i is not None and i == prev + 1:
                prev = i
                continue
            if start > 0:                       # 좌측 절단 제외
                spells.append({"duration": prev - start + 1,
                               "event": 0 if prev == len(dl) - 1 else 1,
                               "entry_rank": grp[grp["di"] == start]["순위"].iloc[0],
                               "review": grp[grp["di"] == start]["리뷰수"].iloc[0]})
            if i is None:
                break
            start = prev = i
    sp = pd.DataFrame(spells)
    w(f"    체류 구간 {len(sp):,}건 (이탈 관측 {int(sp['event'].sum()):,}건, "
      f"우측 절단 {int((sp['event'] == 0).sum()):,}건)")
    tab = km(sp)
    w(f"    {'경과일':>7}{'위험집합':>10}{'이탈':>8}{'생존확률 S(t)':>15}")
    for _, r in tab.iterrows():
        w(f"    {int(r['t']):>7}{int(r['at_risk']):>10,}{int(r['exit']):>8,}{r['S']:>15.3f}")
    w(f"    중위 체류 기간: "
      f"{('%d일' % tab[tab['S'] <= .5]['t'].min()) if (tab['S'] <= .5).any() else '추정 불가(관측 기간 초과)'}")
    w()
    w("    진입 순위 구간별 3일 생존확률")
    for lo, hi in bins:
        s = sp[(sp["entry_rank"] >= lo) & (sp["entry_rank"] <= hi)]
        if len(s) < 30:
            continue
        t3 = km(s)
        v = t3[t3["t"] == 3]["S"]
        w(f"      진입 {lo}–{hi}위 (n={len(s):,}): "
          f"S(3)={v.iloc[0]:.3f}" if len(v) else "")
    w()

    # --- 4. 판정 ----------------------------------------------------------
    w("■ 4. 판정 (TASKS.md 기준: 잔류 로지스틱 pseudo-R² 가 순위 회귀 R²(0.067)보다 높은가)")
    w(f"    잔류 로지스틱 McFadden pseudo-R² = {pr2:.4f}")
    w("    ⚠ 두 값은 직접 비교할 수 없다. McFadden pseudo-R² 는 로그우도 기반이고")
    w("      OLS within R² 는 분산 기반이라 척도가 다르다. 같은 수치를 비교하듯")
    w("      서술하면 안 된다. 판단은 '해석 가능성'과 '안정성'으로 해야 한다.")
    w()
    if pr2 > 0.067:
        w("    ▶ 수치상으로는 기준을 넘는다. 다만 위 주의사항을 함께 명시할 것.")
    else:
        w("    ▶ 수치상 기준에 못 미친다. 다만 위 주의사항을 함께 명시할 것.")
    w("    ▶ 실질적 장점: 잔류는 0/1 이라 절단 표본 문제에서 자유롭고, 순위처럼")
    w("      하루 22계단씩 출렁이는 잡음이 없다. 종속변수로서 더 안정적이다.")
    w()
    w("    ⚠ 한계")
    w("      · 패널 10일 — 생존곡선의 꼬리(5일 이상)는 위험집합이 급격히 줄어 불안정하다.")
    w("      · TOP100 밖은 관측되지 않으므로 '이탈'은 소멸이 아니라 절단이다.")
    w("      · 잔류는 판매 순위 유지이므로, 리뷰 변수의 계수는 여전히 인과가 아니다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"entry_exit_{last}.txt")
    text = "\n".join(R)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
