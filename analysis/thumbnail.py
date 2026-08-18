"""T6. 썸네일 저수준 특성과 순위 — 전 기간 패널 재현 검증.

초판 보고서(4.6)는 "상위권일수록 어둡고 채도 높다"는 상관을 8/1·8/5·8/9 세 스냅샷에서
확인했다. 다만 그 검정은 (i) 전체 TOP100 단독 크로스섹션이라 범위 제한에 걸리고,
(ii) 단순 Spearman 이라 카테고리·날짜 차이를 통제하지 않으며, (iii) 같은 상품의 반복
관측에 대한 표준오차 보정이 없다.

이미지가 수집 PC 에 확보되었으므로, image_bank.py 로 뽑아둔 특성을 카테고리 패널
전 기간에 붙여 T1~T2 와 동일한 사양(카테고리×일 고정효과 + 상품 클러스터 SE)으로
다시 검정한다. 아울러 T7 의 교체 이벤트 전후로 이미지가 실제 얼마나 달라졌는지도 잰다.

사용:  python -m analysis.thumbnail
선행:  python -m analysis.image_bank   (analysis/output/image_bank.csv 생성)
출력:  analysis/output/thumbnail_<date>.txt
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from .growth import OUT_DIR, DV, build_panel, fe_ols, spearman, load_rankings
from .image_bank import BANK
from .image_features import url_to_filename
from .thumbnail_events import build_events

FEATS = ["brightness", "saturation", "colorfulness", "white_border_share",
         "edge_density"]
KOR = {"brightness": "밝기", "saturation": "채도", "colorfulness": "컬러풀니스",
       "white_border_share": "흰테두리비율", "edge_density": "엣지밀도"}


def attach(df: pd.DataFrame, bank: pd.DataFrame) -> pd.DataFrame:
    d = df.dropna(subset=["대표이미지URL"]).copy()
    d["file"] = [url_to_filename(u) for u in d["대표이미지URL"]]
    return d.merge(bank, on="file", how="left")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-05")
    args = ap.parse_args()

    if not os.path.exists(BANK):
        raise SystemExit("먼저 python -m analysis.image_bank 를 실행하세요.")
    bank = pd.read_csv(BANK, encoding="utf-8-sig")

    p = attach(build_panel(args.start, None), bank)
    last = p["수집일자"].max().date()

    R: list[str] = []
    def w(s: str = "") -> None:
        R.append(s)

    ok = p["brightness"].notna()
    w("T6. 썸네일 저수준 특성과 순위 — 전 기간 패널 재현 검증")
    w(f"패널: {p['수집일자'].min().date()} ~ {last} · 관측 {len(p):,}행 · "
      f"상품 {p['상품번호'].nunique():,}개")
    w(f"특성 뱅크 {len(bank):,}장 · 패널 조인 성공 {int(ok.sum()):,}행 ({ok.mean():.1%})")
    w("종속변수 = 순위(작을수록 상위). 계수 음수 = 값이 클수록 상위권")
    w("=" * 78)
    w()

    d = p[ok].copy()

    # --- 1. 초판 방식 재현 -------------------------------------------------
    w("■ 1. 초판 방식 재현 — 전체 TOP100 단순 Spearman")
    w("    (초판 4.6 은 이 방식으로 세 스냅샷에서 부호 재현을 확인했다)")
    rank_all = load_rankings()
    ov = attach(rank_all[rank_all["카테고리"] == "전체"], bank)
    ov = ov[ov["brightness"].notna()]
    w(f"    {'특성':<14}" + "".join(f"{str(x)[5:]:>9}" for x in
                                   sorted(ov['수집일자'].dt.date.unique())[-8:]))
    days8 = sorted(ov["수집일자"].dt.date.unique())[-8:]
    for f in FEATS:
        row = ""
        for dd in days8:
            g = ov[ov["수집일자"].dt.date == dd]
            row += f"{spearman(g['순위'], g[f]):>+9.2f}" if len(g) > 20 else f"{'—':>9}"
        w(f"    {KOR[f]:<14}{row}")
    w("    → 초판의 부호(밝기 +, 채도 −)가 최근 날짜에서도 대체로 유지되는지 확인용")
    w()

    # --- 2. 카테고리×일 고정효과 ------------------------------------------
    w("■ 2. 카테고리×일 고정효과 + 상품 클러스터 SE (본 검정)")
    w("    beta = 1 within-SD 당 순위 변화")
    r = fe_ols(d, FEATS)
    w(f"    N={r.n:,}  그룹={r.ngroups}  within R²={r.r2w:.4f}")
    w(f"    {'특성':<14}{'beta':>9}{'t(일반)':>10}{'t(클러스터)':>13}{'VIF':>7}")
    for nm, b, t, tc, v in zip(r.names, r.beta, r.t, r.tc, r.vifs):
        w(f"    {KOR[nm]:<14}{b:>+9.3f}{t:>+10.2f}{tc:>+13.2f}{v:>7.2f}")
    w()

    # --- 3. 리뷰·가격 통제 후 ---------------------------------------------
    w("■ 3. 판매 관련 변수를 통제하면 남는가")
    w("    (썸네일이 순위와 연관돼도, 잘 팔리는 상품이 좋은 썸네일을 쓰는 것일 수 있다)")
    ctrl = ["velocity_log", "log_review_cnt", "log_price", "할인율"]
    r2 = fe_ols(d, FEATS + ctrl)
    w(f"    N={r2.n:,}  within R²={r2.r2w:.4f}")
    w(f"    {'변수':<14}{'beta':>9}{'t(클러스터)':>13}{'VIF':>7}")
    for nm, b, tc, v in zip(r2.names, r2.beta, r2.tc, r2.vifs):
        lab = KOR.get(nm, nm)
        w(f"    {lab:<14}{b:>+9.3f}{tc:>+13.2f}{v:>7.2f}")
    w()
    surv = [KOR[f] for f in FEATS
            if abs(r2.tc[r2.names.index(f)]) > 2]
    w(f"    통제 후에도 |t|>2 인 특성: {', '.join(surv) if surv else '없음'}")
    w()

    # --- 4. 날짜별 안정성 --------------------------------------------------
    w("■ 4. 날짜별 계수 안정성 (일별 카테고리 고정효과)")
    w(f"    {'날짜':<12}{'N':>7}" + "".join(f"{KOR[f]:>12}" for f in FEATS))
    coefs = {f: [] for f in FEATS}
    for day, g in d.groupby(d["수집일자"].dt.date):
        g = g.dropna(subset=FEATS + [DV])
        if len(g) < 300:
            continue
        rr = fe_ols(g, FEATS, group="카테고리")
        for f in FEATS:
            coefs[f].append(rr.beta[rr.names.index(f)])
        w(f"    {str(day):<12}{rr.n:>7,}"
          + "".join(f"{rr.beta[rr.names.index(f)]:>+12.3f}" for f in FEATS))
    w()
    w(f"    {'특성':<14}{'평균':>10}{'표준편차':>10}{'부호 일치':>11}")
    for f in FEATS:
        a = np.array(coefs[f])
        if not len(a):
            continue
        agree = max((a < 0).mean(), (a > 0).mean())
        w(f"    {KOR[f]:<14}{a.mean():>+10.3f}{a.std():>10.3f}{agree:>11.0%}")
    w()

    # --- 5. 교체 이벤트 전후 이미지 변화 ------------------------------------
    w("■ 5. 교체 이벤트 전후로 이미지가 실제 얼마나 달라지는가 (T7 연계)")
    w("    URL 이 바뀌어도 시각적으로 비슷하면 '교체'의 의미가 약하다.")
    panel_all, ev = build_events(rank_all)
    ev1 = ev[ev["gap"] == 1].copy()
    ev1["file_new"] = [url_to_filename(u) for u in ev1["대표이미지URL"]]
    ev1["file_old"] = [url_to_filename(u) for u in ev1["prev_url"]]
    bi = bank.set_index("file")
    both = ev1[ev1["file_new"].isin(bi.index) & ev1["file_old"].isin(bi.index)]
    w(f"    간격 1일 교체 {len(ev1):,}건 중 전후 이미지가 모두 아카이브된 건 "
      f"{len(both):,}건")
    if len(both):
        w(f"    {'특성':<14}{'교체 전 평균':>13}{'교체 후 평균':>13}{'평균 변화':>11}"
          f"{'|변화| 중위':>12}")
        for f in FEATS:
            a = bi.loc[both["file_old"], f].to_numpy(float)
            b = bi.loc[both["file_new"], f].to_numpy(float)
            w(f"    {KOR[f]:<14}{a.mean():>13.3f}{b.mean():>13.3f}"
              f"{(b - a).mean():>+11.3f}{np.median(np.abs(b - a)):>12.3f}")
        same = np.mean([np.allclose(bi.loc[o, FEATS].to_numpy(float),
                                    bi.loc[n, FEATS].to_numpy(float), rtol=1e-3)
                        for o, n in zip(both["file_old"], both["file_new"])])
        w(f"    전후 특성이 사실상 동일한 비율: {same:.1%}")
        w("    → 이 비율이 높으면 URL 변경이 시각적 교체를 뜻하지 않는다는 신호다.")
    w()

    w("■ 6. 한계")
    w("    · 저수준 특성은 '무엇이 그려져 있는가'를 담지 못한다. 밝기·채도가 낮다는 것과")
    w("      기획 이미지라는 것은 다른 층위다. 마케팅 속성은 수동 라벨이 필요하다(T6 2단계).")
    w("    · 썸네일은 상품 정체성과 강하게 얽혀 있어, 고정효과로 흡수되지 않는 부분은")
    w("      대부분 상품 간 차이다. 인과로 읽을 수 없다.")
    w("    · 교체 이벤트는 프로모션과 동반되므로(T7 §3-1) 썸네일 단독 효과 분리가 어렵다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"thumbnail_{last}.txt")
    text = "\n".join(R)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
