"""썸네일 마케팅 속성과 순위 — 수동 라벨 기반 분석.

저수준 특성(밝기·채도·구성 복잡도)은 '무엇이 그려져 있는가'를 담지 못한다.
analysis/contact_sheet.py 로 만든 컨택트시트를 사람이 보고 네 가지 속성을 분류했다.

  person  인물(모델·연예인·인플루언서) 등장
  period  기간 한정 소구 ("8/22 단 하루", "7일 특가", "한정특가")
  gift    증정·기획 구성 ("+10정 증정", "1+1", "추가증정")
  claim   순위·수상 클레임 ("1등", "올영PICK", "AWARDS", "OO PICK")

같은 스냅샷 안에서 카테고리 차이를 걷어내고 순위와의 관계를 본다. 표본이 160장이라
카테고리×일 고정효과까지 걸면 자유도가 남지 않으므로 카테고리 고정효과만 적용한다.

사용:  python -m analysis.thumbnail_labels
출력:  analysis/output/thumbnail_labels_<date>.txt
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

from .growth import OUT_DIR, DV, fe_ols, load_rankings
from .image_bank import BANK
from .image_features import url_to_filename

LABEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "labels")
ATTRS = ["person", "period", "gift", "claim"]
KOR = {"person": "인물 등장", "period": "기간 한정 소구", "gift": "증정·기획 구성",
       "claim": "순위·수상 클레임"}


def load_labels() -> pd.DataFrame:
    paths = sorted(glob.glob(os.path.join(LABEL_DIR, "img_labels_*.csv")))
    frames = []
    for p in paths:
        d = pd.read_csv(p, encoding="utf-8-sig")
        if not set(ATTRS).issubset(d.columns):
            continue          # 초기 라벨 파일은 컬럼 구성이 달라 제외
        d["source"] = os.path.basename(p)
        frames.append(d)
    if not frames:
        raise SystemExit("라벨 파일이 없습니다. python -m analysis.contact_sheet 후 라벨링 필요")
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argparse.ArgumentParser().parse_args()

    lab = load_labels()
    rank = load_rankings()
    bank = pd.read_csv(BANK, encoding="utf-8-sig")

    R: list[str] = []
    def w(s: str = "") -> None:
        R.append(s)

    # 라벨 대상 상품의 해당 스냅샷 행을 붙인다
    snap_day = rank["수집일자"].max()
    snap = rank[(rank["수집일자"] == snap_day) & (rank["카테고리"] != "전체")]
    snap = snap.drop_duplicates("상품번호")
    d = lab.merge(snap[["상품번호", "순위", "카테고리", "브랜드", "리뷰수", "혜택가",
                        "할인율", "대표이미지URL"]],
                  on="상품번호", how="inner", suffixes=("_lab", ""))
    d["file"] = [url_to_filename(u) for u in d["대표이미지URL"]]
    d = d.merge(bank[["file", "edge_density", "brightness"]], on="file", how="left")
    d["ln_rank"] = np.log(d["순위"])
    d["log_review_cnt"] = np.log10(1 + pd.to_numeric(d["리뷰수"], errors="coerce"))

    w("썸네일 마케팅 속성과 순위 — 수동 라벨 분석")
    w(f"라벨 {len(lab):,}장 · 스냅샷 {snap_day.date()} 랭킹과 결합 {len(d):,}장 · "
      f"카테고리 {d['카테고리'].nunique()}개")
    w("=" * 78)
    w()

    w("■ 1. 각 속성이 얼마나 흔한가")
    w(f"    {'속성':<18}{'해당 썸네일':>12}{'비율':>9}")
    for a in ATTRS:
        w(f"    {KOR[a]:<18}{int(d[a].sum()):>12}{d[a].mean():>9.1%}")
    w()
    w("    조합도 흔하다. 두 개 이상 동시에 쓰는 썸네일 비율: "
      f"{(d[ATTRS].sum(axis=1) >= 2).mean():.1%}")
    w(f"    아무 것도 없는 '맨 제품컷' 비율: {(d[ATTRS].sum(axis=1) == 0).mean():.1%}")
    w()

    w("■ 2. 속성별 평균 순위 비교 (단순 비교)")
    w(f"    {'속성':<18}{'있음 평균순위':>14}{'없음 평균순위':>14}{'차이':>9}{'p':>9}")
    for a in ATTRS:
        yes = d[d[a] == 1]["순위"]
        no = d[d[a] == 0]["순위"]
        if len(yes) < 5 or len(no) < 5:
            continue
        t, p = stats.ttest_ind(yes, no, equal_var=False)
        w(f"    {KOR[a]:<18}{yes.mean():>14.1f}{no.mean():>14.1f}"
          f"{yes.mean() - no.mean():>+9.1f}{p:>9.3f}")
    w("    (순위는 작을수록 상위. 차이가 음수면 그 속성이 있는 쪽이 상위권)")
    w()

    w("■ 3. 카테고리를 통제한 회귀")
    w("    종속변수 ln(순위). 계수가 음수면 그 속성이 상위권과 연관")
    r1 = fe_ols(d, ATTRS, y_col="ln_rank", group="카테고리", cluster="상품번호",
                standardize=False)
    w(f"    N={r1.n}  카테고리 {r1.ngroups}개")
    w(f"    {'속성':<18}{'계수':>10}{'t':>9}{'p':>9}")
    for nm, b, t in zip(r1.names, r1.beta, r1.t):
        w(f"    {KOR[nm]:<18}{b:>+10.3f}{t:>+9.2f}{2 * stats.norm.sf(abs(t)):>9.3f}")
    w()

    w("■ 4. 저수준 특성과 함께 넣으면 무엇이 남는가")
    w("    구성 복잡도(엣지밀도)는 '정보를 얼마나 얹었는가'의 대리 지표다.")
    w("    마케팅 속성을 직접 넣으면 그 대리 지표가 설명하던 몫을 가져가는지 본다.")
    dd = d.dropna(subset=["edge_density"])
    r2 = fe_ols(dd, ["edge_density"], y_col="ln_rank", group="카테고리",
                cluster="상품번호")
    r3 = fe_ols(dd, ATTRS + ["edge_density"], y_col="ln_rank", group="카테고리",
                cluster="상품번호")
    w(f"    구성 복잡도만        : 계수 {r2.beta[0]:+.3f}  t={r2.t[0]:+.2f}  "
      f"within R²={r2.r2w:.3f}")
    i = r3.names.index("edge_density")
    w(f"    마케팅 속성과 함께    : 계수 {r3.beta[i]:+.3f}  t={r3.t[i]:+.2f}  "
      f"within R²={r3.r2w:.3f}")
    w()
    w(f"    {'변수':<18}{'계수':>10}{'t':>9}")
    for nm, b, t in zip(r3.names, r3.beta, r3.t):
        w(f"    {KOR.get(nm, '구성 복잡도'):<18}{b:>+10.3f}{t:>+9.2f}")
    w()

    w("■ 5. 판정")
    sig = [KOR[a] for a in ATTRS if abs(r1.t[r1.names.index(a)]) > 2]
    if sig:
        w(f"    카테고리 통제 후 유의한 속성: {', '.join(sig)}")
    else:
        w("    카테고리 통제 후 통계적으로 유의한 속성은 없다.")
    w(f"    표본이 {len(d)}장이라 검정력이 낮다. TASKS 기준 권장 표본은 300장 이상이므로,")
    w("    현재 결과는 방향을 가늠하는 수준으로만 읽어야 한다.")
    w()
    w("    ⚠ 한계")
    w("      · 라벨은 한 사람이 한 번 매긴 것이라 판정 기준의 일관성을 교차 검증하지 못했다.")
    w("      · 단일 스냅샷이라 같은 상품의 반복 관측으로 표본을 늘릴 수 없다.")
    w("      · 마케팅 속성은 상품 자체의 체급과 얽혀 있다. 잘 팔리는 상품일수록 기획을")
    w("        많이 붙이므로, 속성이 순위를 만든 것인지 결과인지 구분되지 않는다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"thumbnail_labels_{snap_day.date()}.txt")
    text = "\n".join(R)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
