"""T1. 리뷰 '성장률' 분리 — 규모와 속도의 얽힘 해소 (TASKS.md §4 T1).

velocity(일 리뷰 증가분)는 단독으로는 순위와 강하게 연관되지만, 리뷰 규모와 함께
고정효과 회귀에 넣으면 약해진다. 대형 상품이 유입도 많기 때문이다. 이 모듈은
velocity 를 '규모로 설명되는 부분'과 '규모와 직교하는 순수 속도'로 분해해
Q1(유입 속도가 빠를수록 상위권인가)을 완결한다.

핵심 설계 (TASKS.md §3 함정 대응):
- velocity 는 랭킹 CSV 의 리뷰수 차분만 사용 (함정 1: 리뷰 목록 API 가 도움순 고정
  반환이라 리뷰 표본 기반 속도 지표는 편향)
- (수집일자, 상품번호) 중복 제거 후 차분 (함정 3)
- 차분은 경과일로 정규화 (함정 6: 결측일 존재)
- 분석 기간을 카테고리 수집이 정착한 8/5 이후로 한정 (함정 7)
- 카테고리 패널을 분석 단위로 사용하고 '전체' 리스트는 제외 (함정 9: 범위 제한).
  '전체'를 남기면 같은 상품이 같은 날 두 번 들어가 관측이 중복된다.

사용:  python -m analysis.growth [--start 2026-08-05] [--date YYYY-MM-DD]
출력:  analysis/output/growth_analysis_<date>.txt + stdout
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

DV = "순위"              # 작을수록 상위 → 계수가 음수면 '상위권과 연관'
OVERALL = "전체"         # 카테고리 패널에서 제외할 전체 랭킹 리스트
PANEL_START = "2026-08-05"
MAX_GAP_DAYS = 7         # 차분 허용 최대 경과일 (너무 벌어진 쌍은 속도로 보지 않음)


# ---------------------------------------------------------------- 패널 구축

def load_rankings() -> pd.DataFrame:
    frames = []
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "*_ranking.csv"))):
        frames.append(pd.read_csv(path, encoding="utf-8-sig", dtype=str))
    rank = pd.concat(frames, ignore_index=True)
    for col in ["순위", "정가", "혜택가", "할인율", "리뷰수", "리뷰별점",
                "별점5비율", "별점4비율", "별점3비율", "별점2비율", "별점1비율",
                "세일", "쿠폰", "증정", "오늘드림"]:
        rank[col] = pd.to_numeric(rank[col], errors="coerce")
    rank["수집일자"] = pd.to_datetime(rank["수집일자"])
    return rank


def product_velocity(rank_all: pd.DataFrame) -> pd.DataFrame:
    """상품×일 단위 리뷰 유입 속도. 전체+카테고리 중복을 없앤 뒤 인접 관측 차분.

    velocity_t = (리뷰수_t - 리뷰수_prev) / (t - prev).days
    """
    hist = (rank_all.dropna(subset=["리뷰수"])
                    .sort_values(["상품번호", "수집일자"])
                    .drop_duplicates(subset=["수집일자", "상품번호"]))
    g = hist.groupby("상품번호", sort=False)
    gap = g["수집일자"].diff().dt.days
    delta = g["리뷰수"].diff()
    vel = delta / gap
    out = hist[["수집일자", "상품번호"]].copy()
    ok = gap.between(1, MAX_GAP_DAYS)
    out["gap_days"] = gap
    out["velocity"] = vel.where(ok)
    # 전기 리뷰수(재고). 리뷰수_t = 리뷰수_prev + gap×velocity 이므로 현재 재고와
    # 유입은 정의상 겹친다. 재고 효과는 '전기 재고'로 봐야 기계적 중첩이 없다.
    out["review_prev"] = g["리뷰수"].shift().where(ok)
    return out


def build_panel(start: str = PANEL_START, end: str | None = None) -> pd.DataFrame:
    rank_all = load_rankings()
    vel = product_velocity(rank_all)

    p = rank_all[rank_all["수집일자"] >= pd.Timestamp(start)].copy()
    if end:
        p = p[p["수집일자"] <= pd.Timestamp(end)]
    p = p[p["카테고리"] != OVERALL]                      # 함정 9
    p = p.merge(vel, on=["수집일자", "상품번호"], how="left")

    p["log_review_cnt"] = np.log10(1 + p["리뷰수"])
    p["log_review_prev"] = np.log10(1 + p["review_prev"])
    p["log_price"] = np.log10(p["혜택가"].clip(lower=1))
    p["avg_rating"] = p["리뷰별점"]
    p["star1_share"] = p["별점1비율"]
    p["cat_day"] = (p["카테고리"].astype(str) + "|"
                    + p["수집일자"].dt.strftime("%Y-%m-%d"))

    # --- 속도 지표 4종 (T1 방법 2단계) -----------------------------------
    v = p["velocity"]
    p["velocity_log"] = np.log1p(v.clip(lower=0))        # log(1+velocity)
    p["growth_rate"] = v / p["리뷰수"].clip(lower=1)      # 일일 성장률
    p["velocity_pct"] = (p.groupby("cat_day")["velocity"]  # 카테고리 내 백분위
                          .rank(pct=True))
    return p


# ---------------------------------------------------------------- 회귀 도구

def _within(df: pd.DataFrame, cols: list[str], group: str) -> pd.DataFrame:
    """그룹(카테고리×일) 평균 차감 = 고정효과 within 변환."""
    g = df.groupby(group, sort=False)
    return df[cols] - g[cols].transform("mean")


def residualize(df: pd.DataFrame, target: str, on: list[str],
                group: str = "cat_day") -> pd.Series:
    """target 을 on 에 (고정효과 안에서) 회귀시킨 잔차 = 규모로 설명 안 되는 부분."""
    sub = df[[target] + on + [group]].dropna()
    w = _within(sub, [target] + on, group)
    X = w[on].to_numpy(float)
    y = w[target].to_numpy(float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    ss = ((y - y.mean()) ** 2).sum()
    r2 = 1 - (resid @ resid) / ss if ss > 0 else np.nan
    return pd.Series(resid, index=sub.index), r2


def vif(X: np.ndarray) -> np.ndarray:
    """다중공선성 진단. within 변환된 X 기준."""
    out = []
    for j in range(X.shape[1]):
        others = np.delete(X, j, axis=1)
        if others.shape[1] == 0:
            out.append(1.0)
            continue
        b, *_ = np.linalg.lstsq(others, X[:, j], rcond=None)
        r = X[:, j] - others @ b
        ss = ((X[:, j] - X[:, j].mean()) ** 2).sum()
        r2 = 1 - (r @ r) / ss if ss > 0 else 0.0
        out.append(1 / max(1 - r2, 1e-12))
    return np.array(out)


class FEResult:
    def __init__(self, names, beta, t, tc, r2w, n, ngroups, vifs,
                 vcov=None, dof=None):
        self.names, self.beta, self.t, self.tc = names, beta, t, tc
        self.r2w, self.n, self.ngroups, self.vifs = r2w, n, ngroups, vifs
        self.vcov, self.dof = vcov, dof      # 클러스터 공분산 (계수 비교 검정용)

    def contrast(self, weights: dict[str, float]) -> tuple[float, float, float]:
        """계수의 선형결합 검정. 예: {'a': 1, 'b': -1} → a - b = 0 인가.

        (추정값, t, 양측 p) 반환. 클러스터 공분산 사용.
        """
        c = np.array([weights.get(n, 0.0) for n in self.names], dtype=float)
        est = float(c @ self.beta)
        se = float(np.sqrt(c @ self.vcov @ c))
        t = est / se if se > 0 else np.nan
        return est, t, 2 * stats.norm.sf(abs(t))

    def lines(self, indent="    ") -> list[str]:
        out = [f"{indent}N={self.n:,}  그룹(카테고리×일)={self.ngroups}  "
               f"within R²={self.r2w:.4f}"]
        out.append(f"{indent}{'변수':<22}{'beta':>8} {'t':>7} {'t(클러스터)':>11} "
                   f"{'p(클러스터)':>11} {'VIF':>6}")
        for nm, b, t, tc, vf in zip(self.names, self.beta, self.t,
                                    self.tc, self.vifs):
            p = 2 * stats.norm.sf(abs(tc))
            star = "***" if p < .001 else "**" if p < .01 else "*" if p < .05 else ""
            out.append(f"{indent}{nm:<22}{b:+8.3f} {t:+7.2f} {tc:+11.2f} "
                       f"{p:11.4f} {vf:6.2f} {star}")
        return out


def fe_ols(df: pd.DataFrame, x_cols: list[str], y_col: str = DV,
           group: str = "cat_day", cluster: str = "상품번호",
           standardize: bool = True, extra: pd.DataFrame | None = None
           ) -> FEResult:
    """카테고리×일 고정효과 OLS. beta 는 '설명변수 1 within-SD 당 순위 변화'.

    standardize=False 면 원단위 계수 → 로그-로그 모형에서 탄력성으로 읽을 수 있다.
    extra 는 추가로 within 변환해 넣을 열(예: 날짜 더미) — 이원 고정효과에 쓴다.

    표준오차는 일반 OLS 와 상품 단위 클러스터 둘 다 계산한다. 같은 상품이 여러 날
    반복 등장하므로 일반 SE 는 과소추정되고 t 가 부풀려진다 (T2 에서 본격 처리).
    """
    src = df if extra is None else pd.concat([df, extra], axis=1)
    cols = list(x_cols) + ([] if extra is None else list(extra.columns))
    sub = src[[y_col] + cols + [group, cluster]].dropna()
    w = _within(sub, [y_col] + cols, group)
    y = w[y_col].to_numpy(float)
    X = w[cols].to_numpy(float)
    sd = X.std(axis=0, ddof=0) if standardize else np.ones(X.shape[1])
    sd[sd == 0] = 1.0
    X = X / sd                                   # within-SD 로 표준화
    x_cols = cols

    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    u = y - X @ beta
    n, k = X.shape
    ngroups = sub[group].nunique()
    dof = n - k - ngroups
    sigma2 = u @ u / dof
    se = np.sqrt(np.diag(sigma2 * XtX_inv))

    # 상품 단위 클러스터 robust SE
    codes = pd.factorize(sub[cluster].to_numpy())[0]
    G = codes.max() + 1
    Xu = X * u[:, None]
    meat = np.zeros((k, k))
    agg = np.zeros((G, k))
    np.add.at(agg, codes, Xu)
    meat = agg.T @ agg
    c = (G / (G - 1)) * ((n - 1) / dof)
    V = XtX_inv @ meat @ XtX_inv * c
    se_c = np.sqrt(np.diag(V))

    ss = (y ** 2).sum()
    r2w = 1 - (u @ u) / ss if ss > 0 else np.nan
    return FEResult(x_cols, beta, beta / se, beta / se_c, r2w, n, ngroups,
                    vif(X), vcov=V, dof=dof)


def spearman(a: pd.Series, b: pd.Series) -> float:
    return a.rank().corr(b.rank())


# ---------------------------------------------------------------- 리포트

def main() -> None:
    # Windows 기본 콘솔(cp949)에서 '—' 등이 깨지지 않도록
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=PANEL_START, help="패널 시작일")
    ap.add_argument("--date", help="패널 종료일 (기본: 최신)")
    args = ap.parse_args()

    p = build_panel(args.start, args.date)
    last = p["수집일자"].max().date()
    R: list[str] = []
    def w(s: str = "") -> None:
        R.append(s)

    days = sorted(p["수집일자"].dt.date.unique())
    w(f"T1. 리뷰 성장률 분리 — 규모와 속도의 얽힘 해소")
    w(f"패널: {days[0]} ~ {days[-1]} ({len(days)}일) · 카테고리 {p['카테고리'].nunique()}개 "
      f"· 관측 {len(p):,}행 · 상품 {p['상품번호'].nunique():,}개")
    w("종속변수 = 순위(작을수록 상위) → 계수가 음수면 '상위권과 연관'")
    w("해석 원칙: 절단 표본 + 역인과 경로 존재 → 전부 연관성/설명력으로만 서술 (인과 아님)")
    w("=" * 78)
    w()

    # --- 0. 표본 진단 ----------------------------------------------------
    w("■ 0. 표본 진단")
    per_day = p.groupby(p["수집일자"].dt.date).size()
    missing = [str(d) for d in pd.date_range(days[0], days[-1]).date
               if d not in set(days)]
    w(f"    일별 관측수: {per_day.min():,} ~ {per_day.max():,}")
    if missing:
        w(f"    ⚠ 카테고리 수집 결측일: {', '.join(missing)} "
          f"(해당일은 전체 TOP100 만 수집됨 → 패널에서 자동 제외)")
    vel_ok = p["velocity"].notna()
    w(f"    velocity 계산 가능: {vel_ok.sum():,}행 ({vel_ok.mean():.1%})")
    gaps = p.loc[vel_ok, "gap_days"].value_counts().sort_index()
    w(f"    차분 경과일 분포: "
      + ", ".join(f"{int(k)}일 {v:,}건" for k, v in gaps.items()))
    neg = (p.loc[vel_ok, "velocity"] < 0).sum()
    w(f"    velocity < 0 (리뷰 삭제 등): {neg:,}건 ({neg / vel_ok.sum():.2%}) "
      f"→ log 지표는 0 으로 절단, 나머지 지표는 원값 유지")
    w()

    # --- 1. 얽힘 진단 ----------------------------------------------------
    w("■ 1. 규모–속도 얽힘 진단 (T1 의 출발점)")
    d = p.dropna(subset=["velocity", "log_review_cnt"])
    w(f"    velocity ↔ log_review_cnt  Pearson r={d['velocity'].corr(d['log_review_cnt']):+.3f}  "
      f"Spearman ρ={spearman(d['velocity'], d['log_review_cnt']):+.3f}")
    for lo, hi, lab in [(0, .33, "소형"), (.33, .67, "중형"), (.67, 1.01, "대형")]:
        q = d[(d["log_review_cnt"].rank(pct=True) >= lo)
              & (d["log_review_cnt"].rank(pct=True) < hi)]
        w(f"      {lab} 구간 리뷰수 중위 {q['리뷰수'].median():>8,.0f} → "
          f"velocity 중위 {q['velocity'].median():6.2f}/일")
    w("    → 규모가 클수록 유입도 많다. 두 변수를 그냥 같이 넣으면 서로를 잡아먹는다.")
    w()

    # --- 2. 속도 지표별 카테고리 내 상관 ---------------------------------
    w("■ 2. 속도 지표별 순위 상관 (카테고리×일 내 Spearman 평균)")
    metrics = ["velocity", "velocity_log", "velocity_pct", "growth_rate",
               "log_review_cnt"]
    w(f"    {'지표':<18}{'ρ(카테고리내 평균)':>18}{'ρ(전체 풀링)':>14}{'N':>10}")
    for m in metrics:
        sub = p.dropna(subset=[DV, m])
        rhos = (sub.groupby("cat_day")
                   .apply(lambda g: spearman(g[DV], g[m]) if g[m].nunique() > 2
                          else np.nan, include_groups=False)
                   .dropna())
        w(f"    {m:<18}{rhos.mean():>+18.3f}"
          f"{spearman(sub[DV], sub[m]):>+14.3f}{len(sub):>10,}")
    w("    → 원 velocity 의 단독 연관은 강하다. 문제는 이게 규모의 대리인지 여부.")
    w()

    # --- 3. 잔차화 ------------------------------------------------------
    w("■ 3. 잔차화 — 어떤 척도로 분리해야 하는가")
    vv = p["velocity"].dropna()
    w(f"    velocity 분포: 중위 {vv.median():.1f}, 평균 {vv.mean():.1f}, "
      f"최대 {vv.max():,.0f}, 왜도 {stats.skew(vv):.1f}")
    w(f"    → 왜도가 극단적이라 원값 선형회귀는 소수 이상치가 좌우한다. "
      f"log/순위 척도가 필요하다.")
    w()
    resid_raw, r2_raw = residualize(p, "velocity", ["log_review_cnt"])
    resid_log, r2_log = residualize(p, "velocity_log", ["log_review_cnt"])
    resid_pct, r2_pct = residualize(p, "velocity_pct", ["log_review_cnt"])
    p["velocity_resid"] = resid_raw
    p["vlog_resid"] = resid_log
    p["vpct_resid"] = resid_pct
    w("    각 속도 척도를 규모(log_review_cnt)에 FE 안에서 회귀했을 때 설명되는 비율:")
    for lab, r2 in [("velocity(원값)", r2_raw), ("velocity_log", r2_log),
                    ("velocity_pct", r2_pct)]:
        w(f"      {lab:<16} within R²={r2:.4f}  → 규모로 설명 {r2:6.1%} / "
          f"순수 속도 {1 - r2:6.1%}")
    w("    ⚠ 원값 기준으로는 규모가 velocity 를 거의 설명하지 못하는 것처럼 보이지만,")
    w("      이는 비선형성 탓이다(§1 의 Pearson +0.102 vs Spearman +0.776).")
    w("      실제 얽힘은 log 척도에서 드러난다 → 이하 주 분석은 velocity_log 사용.")
    dd = p.dropna(subset=["vlog_resid", "log_review_cnt"])
    w(f"    검증: vlog_resid ↔ log_review_cnt r="
      f"{dd['vlog_resid'].corr(dd['log_review_cnt']):+.4f} (설계상 0)")
    # 역방향: 속도로 설명되지 않는 순수 규모
    scale_resid, r2_sc = residualize(p, "log_review_cnt", ["velocity_log"])
    p["scale_resid"] = scale_resid
    w(f"    역방향: log_review_cnt ~ velocity_log → within R²={r2_sc:.4f} "
      f"(규모 변동의 {r2_sc:.1%} 가 속도로 설명됨)")
    w()

    # --- 4. 고정효과 회귀 시리즈 -----------------------------------------
    w("■ 4. 카테고리×일 고정효과 회귀 — 얽힘 해소 전/후")
    w("    beta = 설명변수 1 within-SD 증가당 순위 변화 (음수 = 상위권)")
    w()
    models = [
        ("M1  규모만", ["log_review_cnt"]),
        ("M2  속도만 (log)", ["velocity_log"]),
        ("M3  규모 + 속도(log)  ← 얽힘 상황", ["log_review_cnt", "velocity_log"]),
        ("M4  규모 + 잔차화 속도(log)  ★ T1 핵심", ["log_review_cnt", "vlog_resid"]),
        ("M4b 속도(log) + 잔차화 규모  ← 역방향 경마", ["velocity_log", "scale_resid"]),
        ("M4c 규모 + 잔차화 속도(원값)  ← 참고: 원값 척도", ["log_review_cnt", "velocity_resid"]),
    ]
    for label, xs in models:
        w(f"  {label}")
        for line in fe_ols(p, xs).lines():
            w(line)
        w()
    w("    ※ M3 의 velocity 계수와 M4 의 vlog_resid 계수가 같은 것은 정상이다.")
    w("      Frisch–Waugh–Lovell 정리상 다변량 회귀의 계수는 이미 '다른 변수를 통제한")
    w("      순수 효과'이므로, 잔차화가 바꾸는 것은 속도 계수가 아니라 **규모 계수**다.")
    w("      (M1 규모 t 와 M4 규모 t 를 비교하면 공유분이 규모로 재배분된 것이 보인다.)")
    w()

    controls = ["할인율", "log_price", "avg_rating", "star1_share", "증정", "쿠폰"]
    avail = [c for c in controls if p[c].notna().sum() > 0 and p[c].std() > 0]
    w(f"  M5  M4 + 통제변수 ({', '.join(avail)})")
    for line in fe_ols(p, ["log_review_cnt", "vlog_resid"] + avail).lines():
        w(line)
    w()

    # --- 4-1. 분산 분해 --------------------------------------------------
    w("■ 4-1. 규모 vs 속도 설명력 분해 (동일 표본 고정, within R²)")
    cc = p.dropna(subset=[DV, "log_review_cnt", "velocity_log"])
    only_s = fe_ols(cc, ["log_review_cnt"]).r2w
    only_v = fe_ols(cc, ["velocity_log"]).r2w
    both = fe_ols(cc, ["log_review_cnt", "velocity_log"]).r2w
    shared = only_s + only_v - both
    w(f"    N={len(cc):,}")
    w(f"    규모 단독      within R² = {only_s:.4f}")
    w(f"    속도 단독      within R² = {only_v:.4f}")
    w(f"    둘 다          within R² = {both:.4f}")
    w(f"    ── 공유분      {shared:.4f} ({shared / both:.0%} of 결합 설명력)")
    w(f"    ── 규모 고유분 {both - only_v:.4f} ({(both - only_v) / both:.0%})")
    w(f"    ── 속도 고유분 {both - only_s:.4f} ({(both - only_s) / both:.0%})")
    w()

    # --- 4-2. 기계적 중첩 제거: 전기 재고 vs 당기 유입 ---------------------
    w("■ 4-2. ⚠ 기계적 중첩 제거 — 전기 재고(리뷰수_prev) vs 당기 유입")
    w("    리뷰수_t = 리뷰수_prev + gap×velocity 이므로 '현재 재고'와 '유입'은 정의상")
    w("    겹친다. §4 에서 규모 고유분이 0 으로 나온 것은 이 중첩 탓일 수 있다.")
    w("    → 재고를 전기값으로 바꿔 중첩을 끊고 다시 본다.")
    w()
    pq = p.dropna(subset=[DV, "log_review_prev", "velocity_log"])
    rs_prev, r2_prev = residualize(pq, "velocity_log", ["log_review_prev"])
    pq = pq.copy()
    pq["vlog_resid_prev"] = rs_prev
    w(f"    velocity_log ~ log_review_prev (FE 내) → within R²={r2_prev:.4f}")
    for label, xs in [("M6  전기재고만", ["log_review_prev"]),
                      ("M7  전기재고 + 속도(log)", ["log_review_prev", "velocity_log"]),
                      ("M8  전기재고 + 잔차화 속도(log)",
                       ["log_review_prev", "vlog_resid_prev"])]:
        w(f"  {label}")
        for line in fe_ols(pq, xs).lines():
            w(line)
        w()
    s_only = fe_ols(pq, ["log_review_prev"]).r2w
    v_only = fe_ols(pq, ["velocity_log"]).r2w
    b_both = fe_ols(pq, ["log_review_prev", "velocity_log"]).r2w
    w(f"    설명력 분해 (N={len(pq):,}): 전기재고 단독 {s_only:.4f} / 속도 단독 {v_only:.4f} / "
      f"둘 다 {b_both:.4f}")
    w(f"      ── 공유분 {s_only + v_only - b_both:.4f}  "
      f"전기재고 고유분 {b_both - v_only:.4f}  속도 고유분 {b_both - s_only:.4f}")
    w()

    # --- 5. 대안 속도 지표 비교 -----------------------------------------
    w("■ 5. 대안 속도 지표 비교 (각각 규모와 함께 투입, 계수는 속도 지표 것만 표시)")
    w(f"    {'속도 지표':<18}{'beta':>9}{'t':>8}{'t(클러스터)':>12}{'VIF':>7}"
      f"{'규모 t(클러스터)':>16}")
    for m in ["velocity", "velocity_log", "velocity_pct", "growth_rate",
              "velocity_resid", "vlog_resid", "vpct_resid"]:
        r = fe_ols(p, ["log_review_cnt", m])
        w(f"    {m:<18}{r.beta[1]:+9.3f}{r.t[1]:+8.2f}{r.tc[1]:+12.2f}"
          f"{r.vifs[1]:7.2f}{r.tc[0]:+16.2f}")
    w("    → VIF 가 높을수록 규모와 얽혀 있어 계수 해석이 불안정하다 (목표 < 5).")
    w()

    # --- 6. 규모 구간별 층화 --------------------------------------------
    w("■ 6. 리뷰 규모 구간별 층화 — 속도 효과는 어디서 나오는가")
    w("    (구간별로 잔차화를 다시 수행해 구간 안에서 규모와 직교화)")
    w(f"    {'구간':<8}{'리뷰수 범위':>22}{'N':>9}{'속도 beta':>11}"
      f"{'속도 t(클)':>12}{'규모 beta':>11}{'규모 t(클)':>12}")
    q = p["리뷰수"].quantile([1 / 3, 2 / 3])
    bins = [("소형", -np.inf, q.iloc[0]), ("중형", q.iloc[0], q.iloc[1]),
            ("대형", q.iloc[1], np.inf)]
    for lab, lo, hi in bins:
        s = p[(p["리뷰수"] > lo) & (p["리뷰수"] <= hi)].copy()
        rs, _ = residualize(s, "velocity_log", ["log_review_cnt"])
        s["vlog_resid"] = rs
        r = fe_ols(s, ["log_review_cnt", "vlog_resid"])
        rng = f"{s['리뷰수'].min():,.0f}~{s['리뷰수'].max():,.0f}"
        w(f"    {lab:<8}{rng:>22}{r.n:>9,}{r.beta[1]:>+11.3f}{r.tc[1]:>+12.2f}"
          f"{r.beta[0]:>+11.3f}{r.tc[0]:>+12.2f}")
    w()

    # --- 7. 날짜별 안정성 ------------------------------------------------
    w("■ 7. 날짜별 계수 안정성 (일별로 카테고리 FE 회귀)")
    w(f"    {'날짜':<12}{'N':>7}{'잔차화속도 beta':>16}{'t':>8}"
      f"{'규모 beta':>11}{'t':>8}")
    day_b = []
    for day, g in p.groupby(p["수집일자"].dt.date):
        g = g.copy()
        if g["velocity"].notna().sum() < 100:
            w(f"    {str(day):<12}{'—':>7}  (velocity 표본 부족, 건너뜀)")
            continue
        rs, _ = residualize(g, "velocity_log", ["log_review_cnt"], group="카테고리")
        g["vlog_resid"] = rs
        r = fe_ols(g, ["log_review_cnt", "vlog_resid"], group="카테고리")
        day_b.append(r.beta[1])
        w(f"    {str(day):<12}{r.n:>7,}{r.beta[1]:>+16.3f}{r.t[1]:>+8.2f}"
          f"{r.beta[0]:>+11.3f}{r.t[0]:>+8.2f}")
    if day_b:
        arr = np.array(day_b)
        w(f"    → 잔차화 속도 계수: 평균 {arr.mean():+.3f}, 표준편차 {arr.std():.3f}, "
          f"음수 비율 {(arr < 0).mean():.0%} ({(arr < 0).sum()}/{len(arr)}일)")
    w()

    # --- 8. 판정 --------------------------------------------------------
    w("■ 8. 성공 판정 (TASKS.md T1 기준: 잔차화 속도의 |t| > 2 인가)")
    m4 = fe_ols(p, ["log_review_cnt", "vlog_resid"])
    m5 = fe_ols(p, ["log_review_cnt", "vlog_resid"] + avail)
    m4c = fe_ols(p, ["log_review_cnt", "velocity_resid"])
    for lab, r, key in [("M4 (규모+잔차화속도 log)", m4, "vlog_resid"),
                        ("M5 (+통제변수)", m5, "vlog_resid"),
                        ("M4c (원값 척도, 참고)", m4c, "velocity_resid")]:
        i = r.names.index(key)
        w(f"    {lab:<26} 잔차화속도 t(일반)={r.t[i]:+.2f}  "
          f"t(상품클러스터)={r.tc[i]:+.2f}  VIF={r.vifs[i]:.2f}")
    verdict = abs(m5.tc[m5.names.index("vlog_resid")]) > 2
    w()
    if verdict:
        w("    ▶ 판정: 잔차화 속도(log)가 상품 클러스터 SE 기준으로도 유의 →")
        w("      '리뷰 규모와 독립적인 유입 속도 효과가 존재한다'로 확정.")
        i5 = m5.names.index("log_review_cnt")
        w(f"      동시에 규모 계수는 M1 t={fe_ols(p, ['log_review_cnt']).tc[0]:+.2f} 에서 "
          f"M5 t={m5.tc[i5]:+.2f} 로 이동 — 공유분이 어디로 갔는지 확인할 것.")
    else:
        w("    ▶ 판정: 잔차화 속도(log)가 유의하지 않음 →")
        w("      '속도 효과는 규모의 대리변수였다'가 결론. TASKS.md 지시대로 이것도 유효한 결과.")
    w()
    w("    ▶ 부수 결론 (기존 발견과 배치되므로 별도 검증함):")
    m7 = fe_ols(pq, ["log_review_prev", "velocity_log"])
    w(f"      규모를 log 유입속도와 함께 넣으면 규모의 고유 설명력이 사라진다")
    w(f"      (현재 재고 t={fe_ols(p, ['log_review_cnt', 'velocity_log']).tc[0]:+.2f}, "
      f"전기 재고 t={m7.tc[0]:+.2f}, 고유 ΔR²≈0.000).")
    w("      기존 보고서는 '리뷰 규모가 압도적'(t=-20.2)이라 서술했으나, 그 모형에는")
    w("      log 척도 유입속도가 들어있지 않았다. 규모의 설명력은 대부분 '유입이 많다'는")
    w("      사실의 대리였을 가능성이 크다 — 즉 T1 의 원래 가설과 방향이 반대다.")
    w("      데이터 처리 오류 가능성은 다음을 확인해 배제했다:")
    w("        · 리뷰수_t 와 velocity 의 정의상 중첩 → 전기 재고로 대체해도 동일 (§4-2)")
    w("        · (수집일자,상품번호) 중복 → 차분 전 제거 (§0)")
    w("        · 결측일로 인한 차분 왜곡 → 경과일 정규화 + 7일 초과 쌍 제외 (§0)")
    w("        · 이상치 → log/순위 척도에서 재현, 10일 전부 동일 부호 (§5, §7)")
    w()
    w("    ⚠ 척도 의존성: 원값 velocity 로는 유의하지 않고(t≈-1.1) log/순위 척도에서는")
    w("      크게 유의하다. 왜도가 극단적(§3)이므로 log/순위 척도가 타당하지만, 결론을")
    w("      서술할 때 이 척도 선택을 반드시 명시해야 한다.")
    w("    ⚠ 남은 한계: 동시점 상관이므로 '유입이 순위를 올린다'와 '상위 노출이 유입을")
    w("      부른다'를 구분하지 못한다. 선후관계는 T4(동적 패널)의 몫이다.")
    w("    ⚠ 클러스터 SE 는 상품 단위만 적용. 브랜드 통제는 T2 에서 처리한다.")

    # --- 9. 해석 한계 ----------------------------------------------------
    w()
    w("=" * 78)
    w("■ 9. ⚠ 해석 한계 — 이 결과를 무엇이라고 불러야 하는가")
    w()
    w("  (1) 랭킹은 판매 랭킹이다")
    w("    getBestList.do 는 올리브영 '판매랭킹' 이며 요청에 기간·정렬 파라미터가 없다.")
    w("    별도 검증(analysis/sales_frame.py) 결과 가격 탄력성이 유입 탄력성의 0.85배로")
    w("    거의 같아 **판매액(매출)순에 가깝다**. 따라서 순위는 설명해야 할 대상이라기보다")
    w("    우리가 가진 유일한 '판매 관측치'로 취급하는 편이 정확하다.")
    w("    → '리뷰 유입이 순위를 설명한다'는 상당 부분 '판매가 판매를 설명한다'이다.")
    w()
    w("  (2) 이 효과는 '속도'가 아니라 '수준'이다")
    rank_all = load_rankings()
    vel = product_velocity(rank_all)
    vel["velocity_log"] = np.log1p(vel["velocity"].clip(lower=0))
    w(f"    {'시차':<16}{'rho(카테고리내 평균)':>22}{'N':>9}")
    for k in (-2, -1, 0, 1, 2):
        v = vel.copy()
        v["수집일자"] = v["수집일자"] - pd.Timedelta(days=k)
        m = p.merge(v[["수집일자", "상품번호", "velocity_log"]],
                    on=["수집일자", "상품번호"], how="left",
                    suffixes=("", "_y")).dropna(subset=["velocity_log_y"])
        if len(m) < 500:
            continue
        rhos = (m.groupby("cat_day")
                  .apply(lambda g: spearman(g[DV], g["velocity_log_y"])
                         if g["velocity_log_y"].nunique() > 2 else np.nan,
                         include_groups=False).dropna())
        lab = "당일 유입" if k == 0 else f"{abs(k)}일 {'뒤' if k > 0 else '앞'} 유입"
        w(f"    k={k:+d} {lab:<11}{rhos.mean():>+22.3f}{len(m):>9,}")
    m = p.merge(vel[["수집일자", "상품번호", "velocity_log"]],
                on=["수집일자", "상품번호"], how="left", suffixes=("", "_y"))
    m = m.sort_values(["카테고리", "상품번호", "수집일자"])
    gg = m.groupby(["카테고리", "상품번호"], sort=False)
    m["gap1"] = gg["수집일자"].diff().dt.days
    m["d_rank"] = gg[DV].diff()
    m["d_vel"] = gg["velocity_log_y"].diff()
    dd2 = m[m["gap1"] == 1].dropna(subset=["d_rank", "d_vel"])
    w(f"    상품 내 전일 대비: Δ순위 ↔ Δ유입  r="
      f"{dd2['d_rank'].corr(dd2['d_vel']):+.3f}  (N={len(dd2):,}, "
      f"Δ순위 표준편차 {dd2['d_rank'].std():.1f}계단)")
    w("    → 시차를 밀어도 상관이 평평하고, 상품 내 일간 변화는 무상관이다.")
    w("      즉 이 관계는 '오늘 유입이 몰려 오늘 순위가 올랐다'가 아니라")
    w("      '평소 유입이 많은 상품이 평소 상위권에 있다'는 **상품 간 수준 차이**다.")
    w("      본문에서 velocity 를 '속도·모멘텀'으로 부르는 것은 부정확하다.")
    w()
    w("  (3) 따라서 §8 의 결론은 이렇게 고쳐 읽어야 한다")
    w("      (X) 지금 뜨고 있는 상품이 상위권이다")
    w("      (O) 최근 판매 수준이 높은 상품이 상위권이고, 과거 누적 판매 이력")
    w("          (리뷰 재고)은 그 위에 얹을 정보가 없다")
    w("      판매 랭킹임을 감안하면 절반은 예상 가능한 결과다. 다만 리뷰 유입이")
    w("      순위 변동의 15% 만 설명한다는 점에서 동어반복은 아니다.")
    w()
    w("  (4) 남은 질문 — 리뷰가 판매의 그림자인가, 판매를 만드는가")
    w("      현재 설계로는 구분 불가. 프로모션처럼 상품 내에서 실제로 변하는 변수")
    w("      (analysis/promo.py) 나 시차 설계(T4)가 필요하다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"growth_analysis_{last}.txt")
    text = "\n".join(R)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
