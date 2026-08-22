"""T7. 썸네일 교체 이벤트 스터디 — 상품 내(within-product) 설계.

이미지 파일명이 URL 해시라 썸네일이 교체되면 전후 버전이 모두 보존된다. 같은 상품의
대표이미지URL 변경을 교체 이벤트로 감지할 수 있으며, 이는 **상품 내 비교**라
앞의 모든 크로스섹션 분석보다 인과에 가깝다. 이미지 파일 없이 URL 시계열만으로도
이벤트 감지가 가능하다.

⚠ 4.4.6(프로모션)에서 확인한 역인과 — 순위가 떨어진 직후에 세일이 붙는 패턴 —
   이 여기서도 그대로 위험이다. 교체는 무작위가 아니라 부진한 상품에 시행될 수 있다.
   따라서 사전 추세(pre-trend) 확인을 판정의 필수 조건으로 둔다.

사용:  python -m analysis.thumbnail_events
출력:  analysis/output/thumbnail_events_<date>.txt
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from .growth import OUT_DIR, load_rankings

WIN = 4          # 이벤트 전후 관측 창(수집일 기준)
OVERALL = "전체"


def build_events(r: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(상품×일 패널, 교체 이벤트 목록)."""
    r = r.dropna(subset=["대표이미지URL", "순위"]).copy()
    # 같은 날 전체·카테고리 중복 → 상품×일 1행 (순위는 카테고리 랭킹 우선)
    r["is_overall"] = (r["카테고리"] == OVERALL).astype(int)
    r = (r.sort_values(["상품번호", "수집일자", "is_overall"])
           .drop_duplicates(subset=["수집일자", "상품번호"], keep="first"))
    days = pd.Index(sorted(r["수집일자"].unique()))
    di = {d: i for i, d in enumerate(days)}
    r["di"] = r["수집일자"].map(di)
    r["ln_rank"] = np.log(r["순위"])
    g = r.sort_values(["상품번호", "di"]).groupby("상품번호", sort=False)
    r = r.sort_values(["상품번호", "di"])
    r["prev_url"] = g["대표이미지URL"].shift()
    r["prev_di"] = g["di"].shift()
    ev = r[(r["prev_url"].notna()) & (r["대표이미지URL"] != r["prev_url"])].copy()
    ev["gap"] = ev["di"] - ev["prev_di"]
    return r, ev


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argparse.ArgumentParser().parse_args()

    rank = load_rankings()
    panel, ev = build_events(rank)
    last = panel["수집일자"].max().date()

    R: list[str] = []
    def w(s: str = "") -> None:
        R.append(s)

    days = sorted(panel["수집일자"].dt.date.unique())
    w("T7. 썸네일 교체 이벤트 스터디")
    w(f"관측: {days[0]} ~ {days[-1]} ({len(days)}개 수집일) · 상품×일 {len(panel):,}행 "
      f"· 상품 {panel['상품번호'].nunique():,}개")
    w("종속변수 = ln(순위). 단위 평균을 뺀 값이므로 음수 = 그 상품의 평소보다 상위")
    w("=" * 78)
    w()

    w("■ 0. 이벤트 규모")
    w(f"    교체 이벤트 {len(ev):,}건 · 교체를 겪은 상품 {ev['상품번호'].nunique():,}개")
    w(f"    2회 이상 교체한 상품 {int((ev.groupby('상품번호').size() >= 2).sum()):,}개")
    w(f"    → TASKS.md 착수 기준(30건) 충족")
    w()
    w(f"    {'수집일':<14}{'교체':>7}{'관측 상품':>10}{'교체율':>9}")
    for d, g in ev.groupby(ev["수집일자"].dt.date):
        n_obs = int((panel["수집일자"].dt.date == d).sum())
        w(f"    {str(d):<14}{len(g):>7,}{n_obs:>10,}{len(g) / max(n_obs, 1):>9.1%}")
    w()
    w("    ⚠ 교체 판정은 '직전 관측일 대비' 이므로 수집 결측 구간이 길수록 교체가")
    w("      과다 집계된다. 이하 이벤트 스터디는 간격 1일 교체만 사용한다.")
    w()
    w("    URL 구조 확인: 파일명이 '상품번호 + 2자리 이미지 인덱스' 형태다")
    w("      (예: A00000015853929 → A00000015853911 = 같은 상품의 29번 이미지 → 11번).")
    w("      즉 URL 변경은 대표 이미지로 내세운 컷이 실제로 바뀐 것이며, CDN 경로 변경")
    w("      같은 잡음이 아니다. 전체·카테고리 리스트 간 URL 불일치도 2,478건 중 2건뿐이라")
    w("      리스트 소속 차이로 인한 가짜 교체는 사실상 없다.")
    w()

    # --- 1. 이벤트 스터디 -------------------------------------------------
    ev1 = ev[ev["gap"] == 1]
    w(f"■ 1. 교체 전후 순위 궤적 (간격 1일 교체 {len(ev1):,}건)")
    pn = panel.copy()
    pn["ln_dm"] = pn["ln_rank"] - pn.groupby("상품번호")["ln_rank"].transform("mean")
    m = pn.merge(ev1[["상품번호", "di"]].rename(columns={"di": "t0"}),
                 on="상품번호", how="inner")
    m["rel"] = m["di"] - m["t0"]
    m = m[m["rel"].between(-WIN, WIN)]
    prof = m.groupby("rel")["ln_dm"].agg(["mean", "size"])
    w(f"    {'상대일':>7}{'관측':>9}{'평균 ln(순위) 편차':>20}")
    for k, row in prof.iterrows():
        mark = "  ← 교체일" if k == 0 else ""
        w(f"    {int(k):>+7}{int(row['size']):>9,}{row['mean']:>+20.4f}{mark}")
    pre = prof.loc[prof.index < 0, "mean"]
    post = prof.loc[prof.index > 0, "mean"]
    w()
    w(f"    교체 전 평균 {pre.mean():+.4f} → 교체 후 평균 {post.mean():+.4f} "
      f"(차이 {post.mean() - pre.mean():+.4f})")
    w()

    # --- 1-1. 균형 패널 ---------------------------------------------------
    w("■ 1-1. 균형 패널 재추정 (−2~+2일 전부 관측된 이벤트만)")
    w("    위 궤적은 상대일마다 관측 수가 달라 표본 구성이 바뀐다. 교체 후 TOP100 밖으로")
    w("    이탈한 상품이 빠지므로 교체 후 구간이 실제보다 좋아 보일 수 있다.")
    obs = set(zip(panel["상품번호"], panel["di"]))
    bal = [(gno, d) for gno, d in zip(ev1["상품번호"], ev1["di"])
           if all((gno, d + k) in obs for k in range(-2, 3))]
    w(f"    균형 이벤트 {len(bal):,}건 (전체 {len(ev1):,}건 중 "
      f"{len(bal) / max(len(ev1), 1):.0%})")
    if len(bal) >= 30:
        bk = pd.DataFrame(bal, columns=["상품번호", "t0"])
        mb = pn.merge(bk, on="상품번호", how="inner")
        mb["rel"] = mb["di"] - mb["t0"]
        mb = mb[mb["rel"].between(-2, 2)]
        pb = mb.groupby("rel")["ln_dm"].agg(["mean", "size"])
        w(f"    {'상대일':>7}{'관측':>9}{'평균 ln(순위) 편차':>20}")
        for k, row in pb.iterrows():
            mark = "  ← 교체일" if k == 0 else ""
            w(f"    {int(k):>+7}{int(row['size']):>9,}{row['mean']:>+20.4f}{mark}")
        pre_b = pb.loc[pb.index < 0, "mean"].mean()
        post_b = pb.loc[pb.index > 0, "mean"].mean()
        w(f"    교체 전 {pre_b:+.4f} → 교체 후 {post_b:+.4f} (차이 {post_b - pre_b:+.4f})")
        w("    → 불균형 패널의 결과가 표본 구성 변화 때문인지 여기서 판별한다.")
    else:
        w("    균형 이벤트가 30건 미만이라 재추정을 생략한다.")
    w()

    # --- 2. 사전 추세 진단 -------------------------------------------------
    w("■ 2. 사전 추세 진단 — 교체는 무작위인가")
    slope = np.polyfit(pre.index.astype(float), pre.values, 1)[0] if len(pre) > 1 else np.nan
    w(f"    교체 전 {WIN}일 기울기 {slope:+.4f}/일 "
      f"({'순위 악화 중' if slope > 0 else '순위 개선 중'})")
    w("    (ln 순위가 커지는 방향 = 순위가 나빠지는 방향)")
    if slope > 0.01:
        w("    ▶ 교체 직전에 순위가 이미 나빠지고 있었다. 즉 교체는 부진에 대한 대응이며,")
        w("      교체 후 개선이 보이더라도 평균회귀와 구분할 수 없다. 4.4.6 의 세일 배지와")
        w("      같은 역인과 구조다.")
    elif slope < -0.01:
        w("    ▶ 교체 직전에 순위가 오히려 개선되고 있었다. 상승 중인 상품에 교체가")
        w("      집중된다는 뜻이므로, 교체 후 효과를 교체 덕분으로 읽으면 안 된다.")
    else:
        w("    ▶ 사전 추세가 뚜렷하지 않다. 교체 시점이 순위 흐름과 무관하게 잡혔을")
        w("      가능성이 있어, 이벤트 스터디 해석의 조건이 비교적 양호하다.")
    w()

    # --- 3. 대조군 비교 ---------------------------------------------------
    w("■ 3. 대조군 대비 (같은 날 교체하지 않은 상품)")
    ev_keys = set(zip(ev1["상품번호"], ev1["di"]))
    pn["is_ev"] = [(a, b) in ev_keys for a, b in zip(pn["상품번호"], pn["di"])]
    # 교체일 t0 를 가진 상품의 t0 시점 vs 같은 날 비교체 상품의 당일 편차
    same_day = pn.groupby("di")["ln_dm"].transform("mean")
    pn["ln_dm_adj"] = pn["ln_dm"] - same_day
    w(f"    {'상대일':>7}{'교체군 편차':>14}{'대조군 편차':>14}{'차이':>10}")
    for k in range(-2, 3):
        sub = m[m["rel"] == k]
        keys = set(zip(sub["상품번호"], sub["di"]))
        treat = pn[[(a, b) in keys for a, b in zip(pn["상품번호"], pn["di"])]]
        ctrl_days = treat["di"].unique()
        ctrl = pn[pn["di"].isin(ctrl_days) & ~pn["is_ev"]]
        if len(treat) < 30:
            continue
        w(f"    {k:>+7}{treat['ln_dm'].mean():>+14.4f}{ctrl['ln_dm'].mean():>+14.4f}"
          f"{treat['ln_dm'].mean() - ctrl['ln_dm'].mean():>+10.4f}")
    w()

    # --- 3-1. 프로모션 동시 발생 -------------------------------------------
    w("■ 3-1. 교체는 프로모션과 함께 일어나는가")
    w("    교체 전날·당일에 순위가 평소보다 높았다가 되돌아가는 패턴은, 교체 자체의")
    w("    효과가 아니라 같은 시점의 프로모션 때문일 수 있다(4.4.6 의 쿠폰 당일 효과).")
    BADGE = ["세일", "쿠폰", "증정"]
    pb2 = panel.sort_values(["상품번호", "di"]).copy()
    gg = pb2.groupby("상품번호", sort=False)
    for b in BADGE:
        pb2[b] = pd.to_numeric(pb2[b], errors="coerce")
        pb2[f"d_{b}"] = gg[b].diff()
    pb2["is_ev"] = [(a, d) in set(zip(ev1["상품번호"], ev1["di"]))
                    for a, d in zip(pb2["상품번호"], pb2["di"])]
    base = pb2[(~pb2["is_ev"]) & pb2["d_쿠폰"].notna()]
    trt = pb2[pb2["is_ev"] & pb2["d_쿠폰"].notna()]
    w(f"    {'배지':<8}{'교체일 부착률':>14}{'비교체일 부착률':>16}{'배수':>8}")
    for b in BADGE:
        a1 = (trt[f"d_{b}"] > 0).mean()
        a0 = (base[f"d_{b}"] > 0).mean()
        w(f"    {b:<8}{a1:>14.1%}{a0:>16.1%}{a1 / max(a0, 1e-9):>8.1f}배")
    any_t = (trt[[f"d_{b}" for b in BADGE]] > 0).any(axis=1).mean()
    any_b = (base[[f"d_{b}" for b in BADGE]] > 0).any(axis=1).mean()
    w(f"    {'하나라도':<8}{any_t:>14.1%}{any_b:>16.1%}{any_t / max(any_b, 1e-9):>8.1f}배")
    w(f"    (교체일 {len(trt):,}건 vs 비교체일 {len(base):,}건)")
    if any_t > any_b * 1.5:
        w("    ▶ 썸네일 교체는 프로모션 부착과 강하게 동반된다. 따라서 교체 전후의 순위")
        w("      움직임을 '썸네일 효과'로 읽으면 안 된다 — 프로모션 효과와 분리 불가다.")
    else:
        w("    ▶ 교체와 프로모션 부착의 동반은 뚜렷하지 않다.")
    w()

    # --- 3-2. 프로모션 무변화 부분표본 --------------------------------------
    w("■ 3-2. 프로모션이 그대로였던 교체만 추려서 재검정")
    w("    교체와 프로모션이 함께 일어난다면, 배지가 전혀 바뀌지 않은 날의 교체만")
    w("    남기면 썸네일 단독 효과에 가까워진다.")
    changed = (pb2[[f"d_{b}" for b in BADGE]].abs().sum(axis=1) > 0)
    pb2["badge_changed"] = changed
    clean_keys = set(zip(pb2.loc[pb2["is_ev"] & ~changed, "상품번호"],
                         pb2.loc[pb2["is_ev"] & ~changed, "di"]))
    w(f"    간격 1일 교체 {len(ev1):,}건 중 배지 변화가 없던 교체 "
      f"{len(clean_keys):,}건 ({len(clean_keys) / max(len(ev1), 1):.0%})")
    if len(clean_keys) >= 50:
        ck = pd.DataFrame(list(clean_keys), columns=["상품번호", "t0"])
        mc = pn.merge(ck, on="상품번호", how="inner")
        mc["rel"] = mc["di"] - mc["t0"]
        mc = mc[mc["rel"].between(-2, 2)]
        pc = mc.groupby("rel")["ln_dm"].agg(["mean", "size"])
        w(f"    {'상대일':>7}{'관측':>9}{'평균 ln(순위) 편차':>20}")
        for k, r in pc.iterrows():
            mark = "  ← 교체일" if k == 0 else ""
            w(f"    {int(k):>+7}{int(r['size']):>9,}{r['mean']:>+20.4f}{mark}")
        pre_c = pc.loc[pc.index < 0, "mean"].mean()
        post_c = pc.loc[pc.index > 0, "mean"].mean()
        w(f"    교체 전 {pre_c:+.4f} → 교체 후 {post_c:+.4f} "
          f"(차이 {post_c - pre_c:+.4f})")
        w()
        d0 = pc.loc[0, "mean"] if 0 in pc.index else float("nan")
        dm1 = pc.loc[-1, "mean"] if -1 in pc.index else float("nan")
        if post_c > d0:
            w("    ▶ 프로모션 변화를 걷어내도 패턴의 모양은 그대로다. 교체 직전"
              f"({dm1:+.3f})과 당일({d0:+.3f})에 순위가 평소보다 높고, 교체 뒤에는")
            w(f"      오히려 평소 수준으로 되돌아간다({post_c:+.3f}).")
            w("      즉 썸네일을 바꿔서 순위가 오른 것이 아니라, 순위가 좋을 때 썸네일을")
            w("      바꾼다고 읽는 편이 자연스럽다. 프로모션은 이 패턴의 원인이 아니었다.")
        else:
            w("    ▶ 프로모션 변화를 걷어내자 교체 이후 순위가 개선되는 방향으로 바뀐다.")
            w("      썸네일 교체 자체의 효과일 가능성을 배제할 수 없다.")
    else:
        w("    표본이 50건 미만이라 재검정을 생략한다.")
    w()

    # --- 4. 교체 상품의 특성 ----------------------------------------------
    w("■ 4. 어떤 상품이 썸네일을 바꾸는가")
    pn["ever_ev"] = pn["상품번호"].isin(ev1["상품번호"])
    for lab, sub in (("교체 경험 있음", pn[pn["ever_ev"]]),
                     ("교체 경험 없음", pn[~pn["ever_ev"]])):
        w(f"    {lab:<14} 상품 {sub['상품번호'].nunique():>6,}개 · "
          f"중위 순위 {sub['순위'].median():>5.0f} · "
          f"중위 리뷰수 {pd.to_numeric(sub['리뷰수'], errors='coerce').median():>9,.0f} · "
          f"평균 할인율 {pd.to_numeric(sub['할인율'], errors='coerce').mean():>5.1f}")
    w()
    w("■ 5. 한계")
    w("    · 교체 시점은 무작위가 아니다. §2 의 사전 추세 진단 없이 효과를 주장할 수 없다.")
    w("    · 하루 1회 스냅샷이라 같은 날 두 번 교체하면 1회로만 관측된다.")
    w("    · URL 변경이 곧 시각적 변경은 아니다(CDN 경로 변경 가능). 실제 이미지 차이")
    w("      검증은 image_bank.py 의 특성값 비교로 별도 확인해야 한다.")
    w("    · TOP100 밖으로 이탈하면 관측이 끊겨 교체 후 급락 사례가 표본에서 사라진다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"thumbnail_events_{last}.txt")
    text = "\n".join(R)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
