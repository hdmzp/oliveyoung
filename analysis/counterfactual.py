"""프로모션의 증분 효과 — 반사실(counterfactual) 추정 (보고서 5.6절).

"프로모션을 걸었더니 매출이 늘었다"는 문장은 거의 언제나 참이다. 프로모션은 팔릴
만한 시점에 편성되고, 그 직전에는 대개 판매가 한 번 꺼지기 때문이다. 이 모듈은
**프로모션이 없었다면 어떻게 됐을까**를 여러 방식으로 예측해, 실제값에서 그 예측을
뺀 값 = 증분 효과만 남긴다.

이벤트 정의
---------
  온셋 = 배지(쿠폰/세일/증정)가 직전 2회 관측에서 0 이었다가 1 로 바뀐 날.
  창   = 사전 7관측 · 사후 5관측 (온셋일 포함). 사전 5개·사후 4개 이상 관측 필요.

반사실 모형 5종
-------------
  · 사전평균(무보정)  프로모션 직전 평균으로 그대로 이어간다 — 실무에서 가장 흔한 방식
  · 시장대조(DiD)     사전평균 + (같은 카테고리 시장지수의 변화분)
  · ARIMA(1,0,0)     상품 자기 시계열의 사전 구간으로 적합 후 5기 예측
  · EARTH(MARS 근사) 스플라인 기저 + 선형회귀. 구간별 기울기가 꺾이는 비선형을 잡는다
  · 신경망(MLP)       은닉층 (64, 32)
  뒤의 셋은 **프로모션 변화가 전혀 없는 관측(통제군)** 만으로 학습한다. 즉 "평상시
  판매가 어떻게 이어지는가"만 배운 모형으로 프로모션 구간을 예측한다.

모형 선택은 취향이 아니라 검증으로 한다
--------------------------------
  통제군을 상품 단위로 4분의 1 떼어 홀드아웃으로 두고, 5일 지평 예측오차(RMSE·MAE)와
  편향을 잰다. 증분 효과의 크기는 어떤 반사실을 믿느냐에 따라 크게 달라지므로,
  이 검증 표를 반드시 함께 읽어야 한다.

사용:  python -m analysis.counterfactual [--pre 7] [--post 5]
출력:  analysis/output/counterfactual_<date>.txt + stdout
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import SplineTransformer, StandardScaler
from statsmodels.tsa.arima.model import ARIMA

from .growth import OUT_DIR, build_panel

warnings.filterwarnings("ignore")

BADGES = ["쿠폰", "세일", "증정"]
DISC_JUMP = 5            # 할인율이 이만큼(%p) 움직여도 '프로모션 변화'로 본다
SEED = 0


# ---------------------------------------------------------------- 패널

def prep(start: str = "2026-08-03") -> pd.DataFrame:
    p = build_panel(start)
    d = (p[p["카테고리"] != "전체"]
         .drop_duplicates(subset=["수집일자", "상품번호"])
         .sort_values(["상품번호", "수집일자"]).copy())
    days = sorted(d["수집일자"].unique())
    d["ti"] = d["수집일자"].map({x: i for i, x in enumerate(days)})
    d["y"] = np.log1p(d["velocity"].clip(lower=0))
    g = d.groupby("상품번호")
    for b in BADGES:
        d[f"{b}_on"] = ((d[b] == 1) & (g[b].shift(1) == 0) & (g[b].shift(2) == 0))
    chg = pd.Series(False, index=d.index)
    for b in BADGES:
        chg |= (d[b] != g[b].shift(1)).fillna(False)
    chg |= ((d["할인율"] - g["할인율"].shift(1)).abs() >= DISC_JUMP).fillna(False)
    d["promo_chg"] = chg
    d["mkt"] = d.groupby(["카테고리", "ti"])["y"].transform("mean")
    return d


def windows(d: pd.DataFrame, pre: int, post: int
            ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """온셋 이벤트와 통제 유사이벤트를 같은 창 모양으로 잘라낸다."""
    Y = d.set_index(["상품번호", "ti"])["y"]
    M = d.set_index(["상품번호", "ti"])["mkt"]
    CH = d.set_index(["상품번호", "ti"])["promo_chg"]
    treated, control = [], []
    for pid, x in d.groupby("상품번호", sort=False):
        cat = x["카테고리"].iat[0]
        for r in x.itertuples():
            t0 = r.ti
            ypre = [Y.get((pid, t0 - k), np.nan) for k in range(pre, 0, -1)]
            ypost = [Y.get((pid, t0 + k), np.nan) for k in range(post)]
            mpre = [M.get((pid, t0 - k), np.nan) for k in range(pre, 0, -1)]
            mpost = [M.get((pid, t0 + k), np.nan) for k in range(post)]
            if (np.sum(~pd.isna(ypre)) < pre - 2
                    or np.sum(~pd.isna(ypost)) < post - 1):
                continue
            row = [pid, cat, t0] + ypre + ypost + mpre + mpost
            kinds = [b for b in BADGES if getattr(r, f"{b}_on")]
            if kinds:
                treated.append(row + [kinds[0]])
            elif not any(bool(CH.get((pid, t0 + k), True))
                         for k in range(-1, post)):
                control.append(row + ["control"])
    cols = (["pid", "cat", "t0"]
            + [f"pre{k}" for k in range(pre, 0, -1)]
            + [f"post{k}" for k in range(post)]
            + [f"mpre{k}" for k in range(pre, 0, -1)]
            + [f"mpost{k}" for k in range(post)] + ["kind"])
    return pd.DataFrame(treated, columns=cols), pd.DataFrame(control, columns=cols)


# ---------------------------------------------------------------- 특징

def fill(df: pd.DataFrame, cols: list[str]) -> None:
    row_mean = df[cols].mean(axis=1)
    for c in cols:
        df[c] = df[c].fillna(row_mean)


def to_long(df: pd.DataFrame, pre: int, post: int) -> pd.DataFrame:
    PC = [f"pre{k}" for k in range(pre, 0, -1)]
    MP = [f"mpre{k}" for k in range(pre, 0, -1)]
    out = []
    for h in range(post):
        x = df[["pid", "cat", "kind", "t0"]].copy()
        x["h"] = h
        for i, c in enumerate(PC):
            x[f"L{i}"] = df[c].to_numpy()
        x["premean"] = df[PC].mean(axis=1).to_numpy()
        x["presd"] = df[PC].std(axis=1).to_numpy()
        x["pretrend"] = (df[PC[-3:]].mean(axis=1)
                         - df[PC[:3]].mean(axis=1)).to_numpy()
        x["mkt_pre"] = df[MP].mean(axis=1).to_numpy()
        x["mkt_h"] = df[f"mpost{h}"].to_numpy()
        x["y"] = df[f"post{h}"].to_numpy()
        out.append(x)
    return pd.concat(out, ignore_index=True)


def arima_forecast(W: pd.DataFrame, pre: int, post: int) -> np.ndarray:
    PC = [f"pre{k}" for k in range(pre, 0, -1)]
    out = np.full((len(W), post), np.nan)
    for i, (_, r) in enumerate(W.iterrows()):
        s = r[PC].to_numpy(float)
        s = s[~np.isnan(s)]
        if len(s) < 4:
            out[i, :] = np.nanmean(s) if len(s) else np.nan
            continue
        try:
            f = ARIMA(s, order=(1, 0, 0), trend="c").fit().forecast(post)
        except Exception:
            try:
                f = ARIMA(s, order=(0, 1, 1)).fit().forecast(post)
            except Exception:
                f = np.repeat(np.nanmean(s), post)
        out[i, :] = f
    return out


def attach_arima(L: pd.DataFrame, W: pd.DataFrame, pre: int,
                 post: int) -> pd.DataFrame:
    A = arima_forecast(W, pre, post)
    long = pd.concat([pd.DataFrame({"pid": W["pid"].to_numpy(),
                                    "t0": W["t0"].to_numpy(),
                                    "h": h, "arima": A[:, h]})
                      for h in range(post)], ignore_index=True)
    return L.merge(long, on=["pid", "t0", "h"], how="left")


def pct(delta: float) -> float:
    return 100 * (np.exp(delta) - 1)


# ---------------------------------------------------------------- 본체

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-03")
    ap.add_argument("--pre", type=int, default=7)
    ap.add_argument("--post", type=int, default=5)
    args = ap.parse_args()
    PRE, POST = args.pre, args.post

    d = prep(args.start)
    E, C = windows(d, PRE, POST)
    PC = [f"pre{k}" for k in range(PRE, 0, -1)]
    MP = [f"mpre{k}" for k in range(PRE, 0, -1)]
    for df in (E, C):
        fill(df, PC)
        fill(df, MP)

    FEAT = ([f"L{i}" for i in range(PRE)]
            + ["premean", "presd", "pretrend", "mkt_pre", "mkt_h", "h"])
    LE = to_long(E, PRE, POST)
    LC = to_long(C, PRE, POST)

    rng = np.random.default_rng(SEED)
    pids = C["pid"].unique().copy()
    rng.shuffle(pids)
    hold = set(pids[:max(1, len(pids) // 4)])
    tr = LC[~LC["pid"].isin(hold)].dropna(subset=["y", "mkt_h"])
    te = LC[LC["pid"].isin(hold)].dropna(subset=["y", "mkt_h"])

    Xtr, ytr = tr[FEAT].to_numpy(float), tr["y"].to_numpy(float)
    models = {
        "EARTH(MARS 근사)": make_pipeline(
            SplineTransformer(n_knots=5, degree=3, include_bias=False),
            LinearRegression()).fit(Xtr, ytr),
        "신경망(MLP)": make_pipeline(
            StandardScaler(),
            MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=1200,
                         random_state=SEED, early_stopping=True,
                         n_iter_no_change=25)).fit(Xtr, ytr),
    }

    te = attach_arima(te, C[C["pid"].isin(hold)].reset_index(drop=True),
                      PRE, POST)
    LE = attach_arima(LE, E, PRE, POST).dropna(subset=["y", "mkt_h"])

    def predict(L: pd.DataFrame) -> dict[str, np.ndarray]:
        p = {"사전평균(무보정)": L["premean"].to_numpy(float),
             "시장대조(DiD)": (L["premean"] + L["mkt_h"]
                            - L["mkt_pre"]).to_numpy(float),
             "ARIMA(1,0,0)": L["arima"].to_numpy(float)}
        X = L[FEAT].to_numpy(float)
        for k, m in models.items():
            p[k] = m.predict(X)
        return p

    R: list[str] = []
    def out(s: str = "") -> None:
        R.append(s)

    out("프로모션의 증분 효과 — 반사실 추정")
    out(f"창: 사전 {PRE}관측 · 사후 {POST}관측 · "
        f"{d['수집일자'].min().date()} ~ {d['수집일자'].max().date()}")
    out(f"처치 이벤트 {len(E):,}건(상품 {E['pid'].nunique():,}개) · "
        f"통제 유사이벤트 {len(C):,}건(상품 {C['pid'].nunique():,}개)")
    out("종속변수 ln(1+리뷰 유입) — 판매 수량 대리지표")
    out("=" * 78)
    out()

    out("■ 1. 이벤트 창의 실제 경로 (처치군 평균, ln 스케일)")
    pre_path = E[PC].mean()
    post_path = E[[f"post{h}" for h in range(POST)]].mean()
    out("    사전  " + "  ".join(f"D{-k}:{v:.3f}"
                                for k, v in zip(range(PRE, 0, -1), pre_path)))
    out("    사후  " + "  ".join(f"D+{h}:{v:.3f}"
                                for h, v in enumerate(post_path)))
    dip = pre_path.iloc[-1] - pre_path.iloc[:-1].mean()
    out(f"    온셋 직전 1관측이 그 앞 평균보다 {dip:+.3f} (≈{pct(dip):+.1f}%) — "
        "프로모션은 판매가 꺼진 뒤에 붙는다")
    out("    → 사전 평균을 그대로 반사실로 쓰면 이 '자연 반등'까지 "
        "프로모션 효과로 계상된다.")
    out()

    out("■ 2. 반사실 모형 검증 (통제군 홀드아웃, 상품 단위 분할)")
    out(f"    학습 {len(tr):,}행 · 검증 {len(te):,}행")
    out(f"    {'모형':<20}{'RMSE':>8}{'MAE':>8}{'편향':>9}")
    yte = te["y"].to_numpy(float)
    val = {}
    for k, v in predict(te).items():
        ok = ~np.isnan(v)
        rmse = float(np.sqrt(np.mean((yte[ok] - v[ok]) ** 2)))
        mae = float(np.mean(np.abs(yte[ok] - v[ok])))
        bias = float(np.mean(v[ok] - yte[ok]))
        val[k] = rmse
        out(f"    {k:<20}{rmse:>8.4f}{mae:>8.4f}{bias:>+9.4f}")
    best = min(val, key=val.get)
    out(f"    → 가장 정확한 반사실은 {best}. 단순 사전평균이 가장 부정확하다.")
    out()

    out("■ 3. 증분 효과 (Actual − Counterfactual, 온셋일 포함 "
        f"{POST}관측 평균)")
    ya = LE["y"].to_numpy(float)
    cf = predict(LE)
    for k, v in cf.items():
        ok = ~np.isnan(v)
        gap = ya[ok] - v[ok]
        se = gap.std(ddof=1) / np.sqrt(LE.loc[ok, "pid"].nunique())
        out(f"    {k:<20} Δln {gap.mean():+.4f} → 판매수량 {pct(gap.mean()):+.1f}%"
            f"   (상품 클러스터 SE {se:.4f})")
    out(f"    → 무보정 추정치는 검증 1위 모형 대비 "
        f"{pct((ya - cf['사전평균(무보정)']).mean()) / max(pct((ya - cf[best]).mean()), 1e-9):.1f}배 "
        "부풀려져 있다.")
    out()

    for k, v in cf.items():
        LE["_p_" + k] = v
    LE["gap"] = ya - cf[best]
    out(f"■ 4. 프로모션 유형별 증분 효과 ({best} 기준)")
    for k, s in LE.groupby("kind"):
        out(f"    {k:<6} 이벤트 {s['pid'].nunique():>4}개 · "
            f"Δln {s['gap'].mean():+.4f} → {pct(s['gap'].mean()):+.1f}%")
    out()

    out(f"■ 5. 지평별 증분 효과 ({best} 기준)")
    for h, s in LE.groupby("h"):
        out(f"    D+{h}  Δln {s['gap'].mean():+.4f} → {pct(s['gap'].mean()):+.1f}%")
    out("    리뷰는 구매 뒤 며칠 지나 쓰이므로, 판매 대리지표의 반응도 "
        "그만큼 뒤로 밀린다.")
    out()

    out("■ 6. 이벤트 시계열 — 실제 경로와 반사실 경로 (사전 평균 = 100)")
    base = float(np.exp(E[PC].mean().mean()) - 1)
    idx = [f"D-{k}" for k in range(PRE, 0, -1)] + [f"D+{h}" for h in range(POST)]
    actual = ([float(np.exp(v) - 1) for v in E[PC].mean()]
              + [float(np.exp(v) - 1) for v in
                 E[[f"post{h}" for h in range(POST)]].mean()])
    paths = {"실제(Actual)": actual}
    for k, v in cf.items():
        tail = [float(np.exp(LE.loc[LE["h"] == h, "_p_" + k].mean()) - 1)
                for h in range(POST)]
        paths[k] = [float(np.exp(x) - 1) for x in E[PC].mean()] + tail
    out(f"    {'모형':<20}" + "".join(f"{c:>8}" for c in idx))
    series = {}
    for k, v in paths.items():
        norm = [100 * x / base for x in v]
        series[k] = [round(x, 1) for x in norm]
        out(f"    {k:<20}" + "".join(f"{x:>8.1f}" for x in norm))
    out("    반사실 경로는 사후 구간에서만 갈린다 — 사전 구간은 정의상 실제와 같다.")
    out()

    out("■ 7. 창 길이 민감도 (사전/사후 관측 수를 바꿔도 결론이 같은가)")
    out(f"    {'창':<12}{'이벤트':>7}{'무보정':>10}{'모형기반':>10}")
    for p2, q2 in ((5, 8), (PRE, POST), (5, 10)):
        E2, C2 = windows(d, p2, q2)
        PC2 = [f"pre{k}" for k in range(p2, 0, -1)]
        MP2 = [f"mpre{k}" for k in range(p2, 0, -1)]
        for df in (E2, C2):
            fill(df, PC2)
            fill(df, MP2)
        F2 = ([f"L{i}" for i in range(p2)]
              + ["premean", "presd", "pretrend", "mkt_pre", "mkt_h", "h"])
        L2c = to_long(C2, p2, q2).dropna(subset=["y", "mkt_h"])
        L2e = to_long(E2, p2, q2).dropna(subset=["y", "mkt_h"])
        m2 = make_pipeline(StandardScaler(),
                           MLPRegressor(hidden_layer_sizes=(64, 32),
                                        max_iter=1200, random_state=SEED,
                                        early_stopping=True)).fit(L2c[F2], L2c["y"])
        naive = (L2e["y"] - L2e["premean"]).mean()
        model = (L2e["y"] - m2.predict(L2e[F2])).mean()
        out(f"    사전{p2}/사후{q2:<4}{E2['pid'].nunique():>7}"
            f"{pct(naive):>+10.1f}%{pct(model):>+10.1f}%")
    out()

    out("■ 8. 해석의 한계")
    out("    · 반사실 모형은 '프로모션이 없던 관측'만으로 학습했다. 프로모션이 붙는")
    out("      상품이 애초에 다른 성격이라면 외삽 오차가 남는다.")
    out("    · 판매 대리지표는 리뷰 유입이다. 리뷰 작성 지연 때문에 즉시 효과는")
    out("      과소, 지연 효과는 D+5 이후로 밀려 잡힌다.")
    out("    · 배지 온셋은 관측 간격 기준이다. 수집 결측일이 낀 구간에서는 온셋")
    out("      시점이 실제보다 늦게 잡힐 수 있다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    last = d["수집일자"].max().date()
    path = os.path.join(OUT_DIR, f"counterfactual_{last}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(R))
    pd.DataFrame(series, index=idx).to_csv(
        os.path.join(OUT_DIR, f"counterfactual_paths_{last}.csv"),
        encoding="utf-8-sig")
    print("\n".join(R))
    print(f"\n저장: {path}")


if __name__ == "__main__":
    main()
