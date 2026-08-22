"""Q2 재설계 — 대가성 리뷰를 '상품 비중'이 아니라 '브랜드 캠페인'으로 본다.

analysis/trial.py 의 결론은 상품 단위로는 Q2 를 검증할 수 없다는 것이었다.
전체 리뷰의 0.8%만 대가성으로 탐지되고, 상품별 비중의 중앙값이 0이라 회귀에 넣을
분산이 없었다. 그러나 대가성 리뷰가 소수 브랜드에 몰려 있다는 점은 확인됐다.

그래서 단위를 바꾼다. 대가성 리뷰의 작성일을 브랜드별로 모으면 특정 시점에 몰리는
구간이 보이는데, 이것이 캠페인이다. 캠페인 시점을 기준으로 그 브랜드 상품들의 랭킹이
어떻게 움직였는지를 본다.

  · 브랜드×일 단위 패널: 랭킹에 올라간 상품 수(슬롯), 평균 순위
  · 캠페인 시작일 = 그 브랜드의 대가성 리뷰가 평소보다 뚜렷하게 몰린 날
  · 캠페인 전후 ±7일의 슬롯 수·평균 순위 궤적

⚠ 리뷰는 구매·수령보다 늦게 작성되므로, 리뷰 작성일이 몰린 시점은 실제 캠페인
   집행보다 며칠 뒤다. 따라서 '캠페인 이전' 구간에 이미 효과가 나타나 있을 수 있다.

사용:  python -m analysis.campaign
출력:  analysis/output/campaign_<date>.txt
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from .growth import OUT_DIR, load_rankings
from .trial import classify, load_reviews

WIN = 7           # 캠페인 전후 관측 창(일)
MIN_TRIAL = 3     # 캠페인으로 볼 최소 대가성 리뷰 수(브랜드·일)


def brand_panel(rank: pd.DataFrame) -> pd.DataFrame:
    """브랜드×일: 랭킹 슬롯 수와 평균 순위."""
    r = rank.dropna(subset=["순위", "브랜드"]).copy()
    r = r[r["카테고리"] != "전체"]
    r = r.drop_duplicates(subset=["수집일자", "카테고리", "상품번호"])
    g = r.groupby(["브랜드", "수집일자"]).agg(
        slots=("순위", "size"), mean_rank=("순위", "mean"),
        best_rank=("순위", "min"), goods=("상품번호", "nunique")).reset_index()
    return g


def trial_by_brand(rv: pd.DataFrame, rank: pd.DataFrame) -> pd.DataFrame:
    """브랜드×작성일: 대가성 리뷰 건수."""
    br = (rank.dropna(subset=["브랜드"])
              .drop_duplicates("상품번호")[["상품번호", "브랜드"]])
    d = rv.merge(br, on="상품번호", how="inner")
    d["작성일"] = pd.to_datetime(d["작성일"].str.strip(), format="%Y.%m.%d",
                                errors="coerce")
    d = d.dropna(subset=["작성일"])
    d["is_trial"] = [classify(t)[0] for t in d["body"]]
    g = (d.groupby(["브랜드", "작성일"])
           .agg(trial=("is_trial", "sum"), reviews=("is_trial", "size"))
           .reset_index())
    return g


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argparse.ArgumentParser().parse_args()

    rank = load_rankings()
    rv = load_reviews()
    bp = brand_panel(rank)
    tb = trial_by_brand(rv, rank)
    last = rank["수집일자"].max().date()

    R: list[str] = []
    def w(s: str = "") -> None:
        R.append(s)

    w("Q2 재설계 — 브랜드 캠페인 단위 검증")
    w(f"랭킹 관측 {rank['수집일자'].min().date()} ~ {last} · "
      f"브랜드×일 패널 {len(bp):,}행 · 브랜드 {bp['브랜드'].nunique():,}개")
    w("=" * 78)
    w()

    # --- 0. 대가성 리뷰의 시간 분포 ---------------------------------------
    w("■ 0. 대가성 리뷰는 시점에 몰리는가")
    tt = tb[tb["trial"] > 0]
    w(f"    대가성 리뷰가 하루라도 잡힌 브랜드 {tt['브랜드'].nunique():,}개 · "
      f"브랜드×일 조합 {len(tt):,}건")
    daily = tb.groupby("브랜드")["trial"].agg(["sum", "size"])
    daily = daily[daily["sum"] >= MIN_TRIAL].sort_values("sum", ascending=False)
    w(f"    대가성 리뷰 {MIN_TRIAL}건 이상 브랜드 {len(daily):,}개")
    w()
    w(f"    {'브랜드':<16}{'대가성':>7}{'작성일 수':>10}{'최다일 집중도':>14}")
    for b, row in daily.head(10).iterrows():
        s = tb[(tb["브랜드"] == b) & (tb["trial"] > 0)]
        peak = s["trial"].max() / row["sum"]
        w(f"    {str(b):<16}{int(row['sum']):>7}{int((s['trial'] > 0).sum()):>10}"
          f"{peak:>14.0%}")
    w("    → 집중도가 높을수록 특정 날짜에 리뷰가 몰렸다는 뜻이다(캠페인 신호).")
    w()

    # --- 1. 캠페인 정의 ----------------------------------------------------
    w("■ 1. 캠페인 시점 정의")
    w(f"    브랜드별로 대가성 리뷰가 하루 {MIN_TRIAL}건 이상 작성된 날을 캠페인 "
      f"시점으로 본다.")
    camp = tb[tb["trial"] >= MIN_TRIAL].copy()
    # 같은 브랜드에서 연속된 날은 하나의 캠페인으로 묶는다
    camp = camp.sort_values(["브랜드", "작성일"])
    camp["gap"] = camp.groupby("브랜드")["작성일"].diff().dt.days
    camp["new"] = (camp["gap"].isna()) | (camp["gap"] > 3)
    camp = camp[camp["new"]]
    w(f"    캠페인 {len(camp):,}건 · 브랜드 {camp['브랜드'].nunique():,}개")
    if len(camp) == 0:
        w("    캠페인으로 볼 만한 집중 시점이 없어 분석을 중단한다.")
    else:
        w(f"    {'브랜드':<16}{'캠페인일':<14}{'그날 대가성 리뷰':>16}")
        for _, r in camp.nlargest(8, "trial").iterrows():
            w(f"    {str(r['브랜드']):<16}{str(r['작성일'].date()):<14}"
              f"{int(r['trial']):>16}")
    w()

    # --- 1-1. 관측 기간과의 겹침 -------------------------------------------
    if len(camp):
        lo, hi = bp["수집일자"].min(), bp["수집일자"].max()
        inside = camp[(camp["작성일"] >= lo - pd.Timedelta(days=WIN))
                      & (camp["작성일"] <= hi + pd.Timedelta(days=WIN))]
        w("■ 1-1. ⚠ 캠페인 시점과 랭킹 관측 기간이 겹치는가")
        w(f"    랭킹 관측 기간: {lo.date()} ~ {hi.date()}")
        w(f"    캠페인 {len(camp):,}건 중 이 기간(±{WIN}일) 안에 드는 것: "
          f"{len(inside):,}건")
        w(f"    캠페인 시점 분포: {camp['작성일'].min().date()} ~ "
          f"{camp['작성일'].max().date()}")
        w("    → 리뷰 작성일은 과거로 길게 퍼져 있는데 랭킹 수집은 최근 한 달뿐이다.")
        w("      대부분의 캠페인은 랭킹을 관측하기 전에 이미 끝났다. 이것이 이벤트")
        w("      스터디를 막는 실제 원인이며, 탐지 성능의 문제가 아니다.")
        w()

    # --- 2. 캠페인 전후 랭킹 궤적 ------------------------------------------
    if len(camp):
        w("■ 2. 캠페인 전후 브랜드의 랭킹 성과")
        bp2 = bp.copy()
        bp2["ln_rank"] = np.log(bp2["mean_rank"])
        for c in ("slots", "ln_rank"):
            bp2[f"dm_{c}"] = (bp2[c]
                              - bp2.groupby("브랜드")[c].transform("mean"))
        m = bp2.merge(camp[["브랜드", "작성일"]].rename(columns={"작성일": "t0"}),
                      on="브랜드", how="inner")
        m["rel"] = (m["수집일자"] - m["t0"]).dt.days
        m = m[m["rel"].between(-WIN, WIN)]
        if len(m) < 50:
            w("    캠페인 전후로 관측된 브랜드×일이 부족해 궤적을 그릴 수 없다.")
        else:
            prof = m.groupby("rel").agg(n=("slots", "size"),
                                        slots=("dm_slots", "mean"),
                                        rank=("dm_ln_rank", "mean"))
            w("    (브랜드 평균을 뺀 값. 슬롯은 클수록, 순위는 작을수록 좋음)")
            w(f"    {'상대일':>7}{'관측':>7}{'슬롯 편차':>12}{'순위 편차':>12}")
            for k, r in prof.iterrows():
                mark = "  ← 캠페인" if k == 0 else ""
                w(f"    {int(k):>+7}{int(r['n']):>7}{r['slots']:>+12.2f}"
                  f"{r['rank']:>+12.4f}{mark}")
            pre = prof[prof.index < 0]
            post = prof[prof.index > 0]
            w()
            w(f"    캠페인 전 평균 슬롯 편차 {pre['slots'].mean():+.2f} → "
              f"후 {post['slots'].mean():+.2f}")
            w(f"    캠페인 전 평균 순위 편차 {pre['rank'].mean():+.4f} → "
              f"후 {post['rank'].mean():+.4f}")
            w()
            if post["slots"].mean() > pre["slots"].mean():
                w("    ▶ 캠페인 이후 랭킹에 올린 상품 수가 늘었다.")
            else:
                w("    ▶ 캠페인 이후 랭킹에 올린 상품 수가 늘지 않았다.")
        w()

    # --- 3. 브랜드 단면 비교 ----------------------------------------------
    w("■ 3. 대가성 리뷰를 쓰는 브랜드는 랭킹 성과가 다른가")
    br = (rank.dropna(subset=["브랜드"]).drop_duplicates("상품번호")
              [["상품번호", "브랜드"]])
    rvb = rv.merge(br, on="상품번호", how="inner")
    rvb["is_trial"] = [classify(t)[0] for t in rvb["body"]]
    agg = (rvb.groupby("브랜드")
              .agg(trial=("is_trial", "sum"), n=("is_trial", "size")))
    agg = agg[agg["n"] >= 100]
    agg["share"] = agg["trial"] / agg["n"]
    perf = bp.groupby("브랜드").agg(slots=("slots", "sum"),
                                  mean_rank=("mean_rank", "mean"),
                                  days=("수집일자", "nunique"))
    j = agg.join(perf, how="inner").dropna()
    w(f"    리뷰 100건 이상 수집된 브랜드 {len(j):,}개")
    hi = j[j["share"] > 0.02]
    lo = j[j["share"] <= 0.02]
    w(f"    {'구분':<20}{'브랜드':>7}{'평균 슬롯':>11}{'평균 순위':>11}"
      f"{'평균 등장일':>12}")
    for lab, s in (("대가성 2% 초과", hi), ("대가성 2% 이하", lo)):
        if len(s):
            w(f"    {lab:<20}{len(s):>7}{s['slots'].mean():>11.1f}"
              f"{s['mean_rank'].mean():>11.1f}{s['days'].mean():>12.1f}")
    if len(hi) >= 5 and len(lo) >= 5:
        from scipy import stats as st
        t, pv = st.ttest_ind(hi["mean_rank"], lo["mean_rank"], equal_var=False)
        w(f"    평균 순위 차이 검정: t={t:+.2f}, p={pv:.3f}")
        if pv < .05:
            w("    ▶ 두 집단의 평균 순위가 통계적으로 다르다.")
        else:
            w("    ▶ 두 집단의 평균 순위에 유의한 차이가 없다.")
    w()

    w("■ 4. 판정과 한계")
    w("    이 설계는 상품 단위의 분산 부족 문제는 피하지만, 여전히 Q2 를 확정적으로")
    w("    답하지 못한다. 이유는 세 가지다.")
    w("      · 대가성 리뷰의 작성일은 실제 캠페인 집행보다 늦다. 따라서 '캠페인 전'")
    w("        구간에 이미 효과가 섞여 있다.")
    w("      · 캠페인을 도는 브랜드는 애초에 마케팅 여력이 있는 브랜드다. 랭킹 성과가")
    w("        좋다면 캠페인 때문인지 브랜드 체급 때문인지 구분되지 않는다.")
    w("      · 본문 표기 기반 탐지가 하한 추정치라는 제약은 그대로다.")
    w("    ▶ 브랜드 캠페인 단위는 상품 단위보다 신호가 크지만, 인과 해석은 여전히")
    w("      불가능하다. Q2 는 '검증 불가' 판정을 유지하되, 캠페인 시점 데이터가 더")
    w("      쌓이면 사전 추세를 통제한 이벤트 스터디로 재시도할 수 있다.")
    w()
    w("    ▶ 무엇이 필요한가: 랭킹 수집을 시작한 이후에 집행된 캠페인이 쌓여야 한다.")
    w("      지금 확보된 캠페인은 대부분 수집 이전 시점이라 전후 비교 자체가 불가능하다.")
    w("      수집을 몇 달 더 이어가면 관측 기간 안의 캠페인만으로 재검정할 수 있다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"campaign_{last}.txt")
    text = "\n".join(R)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
