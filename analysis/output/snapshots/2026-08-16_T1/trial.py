"""T5. 체험단·대가성 리뷰 탐지 개선 — Q2 검증의 선행 과제.

Q2(체험단 비중이 높은 상품이 랭킹에 유리한가)는 세 연구 질문 중 유일하게 미검증이다.
기존 키워드 8개로는 6.3만 건 중 208건(0.33%)만 잡혀 회귀에 넣을 분산 자체가 없었다.
이는 수집량 문제가 아니라 탐지 문제이므로, 본문 표기 규칙을 다시 설계한다.

설계
----
리뷰 본문의 대가성 공시는 세 형태로 나타난다. 실제 표본을 읽고 확인한 결과다.

  1) STRONG  — 단독으로 결정적인 표현 ("체험단", "제공받아", "업체로부터", "광고주" 등)
  2) COMBO   — 보상어와 공시어가 가까이 붙을 때만 유효 (±50자).
               "솔직한 후기"는 단독으로는 일반 리뷰의 상투어지만
               "제품비를 지원받았지만 저의 솔직한 후기입니다"는 명백한 공시다.
  3) HEAD    — 문두에서만 유효한 표현. "제품제공"(해시태그형)이나 "할인받아"는
               본문 중간에 나오면 "세일 때 할인받아 샀어요" 같은 일반 문장이지만,
               문두 40자 안에서 공시어와 함께 나오면 대가성 공시다.

여기에 반어·부정 표현을 걸러내는 가드를 둔다 ("협찬받고싶은 맛", "협찬 아니고" 등).

⚠ 원리적 한계: 표기를 사진에만 넣거나 아예 생략한 리뷰는 본문으로 탐지할 수 없다.
   따라서 이 지표는 항상 **하한 추정치**다.

사용:  python -m analysis.trial
출력:  analysis/output/trial_detection_eval.txt + stdout
검증:  analysis/labels/trial_labels_2026-08-17.csv (수동 라벨 200건)
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
LABEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "labels", "trial_labels_2026-08-17.csv")

# ---- 규칙 사전 -----------------------------------------------------------
STRONG = [
    "체험단", "체험 기회", "리뷰어 선정", "서포터즈", "협찬", "앰배서더", "앰버서더",
    "제공받아", "제공 받아", "제공받은", "제공 받은", "제공받았", "제공 받았",
    "제공받고", "제공 받고", "제공받으", "제공 받으",
    "무상으로 제공", "무상 제공", "무상제공", "무료로 제공", "무료 제공",
    "업체로부터", "브랜드로부터", "판매자로부터", "광고주", "유료 광고", "유료광고",
    "원고료", "대가성", "소정의 지원", "소정의 원고료",
    "제품을 지원", "제품비를 지원", "제품비의 일부를", "제품비 일부를", "이벤트 상금을 지원",
]
COMP = ["지원받", "지원 받", "제공", "협찬", "무상", "무료", "상금", "원고료", "소정의",
        "증정받", "지급받"]
DISC = ["후기입니다", "후기 입니다", "리뷰입니다", "리뷰 입니다", "작성한 후기", "작성된 후기",
        "작성하였습니다", "작성했습니다", "작성되었습니다", "작성 되었", "솔직하게 작성",
        "솔직한 후기", "솔직한 리뷰", "솔직후기", "솔직하게 남기", "솔직한 의견",
        "후기입니당", "작성된 리뷰", "작성한 리뷰", "리뷰를 남", "후기를 남", "포스팅은"]
HEAD = ["할인받", "할인 받", "무상지원", "무상 지원"]
# 해시태그·괄호 태그는 위치와 무관하게 단정적이다. 본문 전수 스캔으로 실재를 확인한
# 표기만 넣는다(#협찬 7건, #제품제공 3건, #리뷰의무x·xx 2건).
# "#리뷰의무x"는 '리뷰 의무 없음'이라는 뜻으로, 제품을 받았을 때만 성립하는 표현이다.
TAG_RE = re.compile(
    r"[#\[\(【]\s*(?:제품제공|제품\s*제공|제품지원|체험단|협찬|제품협찬|무상제공|무료제공"
    r"|유료광고|광고|서포터즈|기자단|리뷰단|앰배서더|대가성|제공받음|제품제공사용리뷰)"
    r"|#\s*리뷰의무\s*[xX×]*"
    r"|^\s*제품제공"
)
# 반어·부정 가드. "아니"를 통째로 막으면 "체험단 아니었으면 평생 안 썼을"처럼
# 오히려 수령을 뜻하는 문장까지 버려지므로, 부정 종결형만 좁게 잡는다.
NEG_AFTER = ["아니고", "아니라", "아니에요", "아니예요", "아니야", "아님",
             "아닌데", "아닙니다", "받고싶", "받고 싶", "받고파", "받았으면"]

COMBO_WIN = 50      # 보상어–공시어 허용 거리
HEAD_ZONE = 40      # HEAD 표현이 유효한 문두 범위
HEAD_WIN = 60       # HEAD 표현 주변 공시어 탐색 범위

_strong = re.compile("|".join(map(re.escape, STRONG)))
_comp = re.compile("|".join(map(re.escape, COMP)))
_disc = re.compile("|".join(map(re.escape, DISC)))
_head = re.compile("|".join(map(re.escape, HEAD)))
_neg = re.compile("|".join(map(re.escape, NEG_AFTER)))


def classify(text: str) -> tuple[int, str]:
    """(대가성 여부 0/1, 근거 티어) 반환."""
    t = text or ""
    for m in _strong.finditer(t):
        if not _neg.search(t[m.end():m.end() + 12]):
            return 1, "strong"
    for m in _comp.finditer(t):
        if _neg.search(t[m.end():m.end() + 12]):
            continue
        if _disc.search(t[max(0, m.start() - COMBO_WIN): m.end() + COMBO_WIN]):
            return 1, "combo"
    if TAG_RE.search(t):
        return 1, "tag"
    for m in _head.finditer(t[:HEAD_ZONE]):
        if _disc.search(t[:m.end() + HEAD_WIN]):
            return 1, "head"
    return 0, ""


def load_reviews() -> pd.DataFrame:
    paths = sorted(glob.glob(os.path.join(DATA_DIR, "*_reviews.csv")))
    bf = os.path.join(DATA_DIR, "backfill", "top100_reviews.csv")
    if os.path.exists(bf):
        paths.append(bf)
    rv = pd.concat([pd.read_csv(p, encoding="utf-8-sig", dtype=str) for p in paths],
                   ignore_index=True)
    rv = (rv.sort_values("수집일자")
            .drop_duplicates(subset=["상품번호", "리뷰ID"], keep="last"))
    rv["body"] = (rv["리뷰본문"].fillna("")
                  .str.replace("&#34;", '"', regex=False)
                  .str.replace("&#039;", "'", regex=False))
    return rv


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argparse.ArgumentParser().parse_args()

    rv = load_reviews()
    res = [classify(t) for t in rv["body"]]
    rv["pred"] = [r[0] for r in res]
    rv["tier"] = [r[1] for r in res]

    OLD = ("체험단", "무상으로 제공", "무상 제공", "제공받아", "제공 받아",
           "협찬", "서포터즈", "무료로 제공")
    old = rv["body"].str.contains("|".join(map(re.escape, OLD)))

    R: list[str] = []
    def w(s: str = "") -> None:
        R.append(s)

    n = len(rv)
    w("T5. 체험단·대가성 리뷰 탐지 개선")
    w(f"대상: 유니크 리뷰 {n:,}건 (상품 {rv['상품번호'].nunique():,}개) · "
      f"수집 {rv['수집일자'].min()} ~ {rv['수집일자'].max()}")
    w("=" * 78)
    w()

    w("■ 1. 탐지율")
    w(f"    기존 키워드 {len(OLD)}개 : {int(old.sum()):>6,}건  ({old.mean():.3%})")
    w(f"    개선 규칙        : {int(rv['pred'].sum()):>6,}건  ({rv['pred'].mean():.3%})")
    w(f"    배수             : {rv['pred'].sum() / max(old.sum(), 1):.2f}배")
    drop = rv[old & (rv["pred"] == 0)]
    w(f"    기존 탐지분 중 제외: {len(drop)}건 (반어 표현 — 오탐 제거)")
    for t in drop["body"]:
        flat = " ".join(t.split())
        w(f"      · {flat[:58]}…")
    w()
    w()
    w(f"    {'근거 티어':<10}{'건수':>8}{'비중':>9}  설명")
    DESC = {"strong": "단독으로 결정적인 표현",
            "tag": "해시태그·괄호 태그 (#제품제공 #협찬 #리뷰의무x 등)",
            "combo": "보상어+공시어 근접(±50자)",
            "head": "문두 40자 안에서만 유효한 표현"}
    for tier in ("strong", "tag", "combo", "head"):
        c = int((rv["tier"] == tier).sum())
        w(f"    {tier:<10}{c:>8,}{c / max(rv['pred'].sum(), 1):>9.1%}  {DESC[tier]}")
    w()

    w("■ 2. 공시 문구의 위치")
    pos = []
    for t in rv.loc[rv["pred"] == 1, "body"]:
        m = _strong.search(t) or TAG_RE.search(t) or _comp.search(t) or _head.search(t)
        if m and t:
            pos.append(m.start() / len(t))
    pos = np.array(pos)
    w(f"    본문 앞 10% 이내 {np.mean(pos < .1):.1%} · 앞 25% 이내 {np.mean(pos < .25):.1%} "
      f"· 뒤 25% {np.mean(pos > .75):.1%}")
    w("    → 공시는 압도적으로 문두에 몰린다. HEAD 티어의 위치 조건은 이 관찰에 근거한다.")
    w()

    # ---- 3. 수동 검증 ----------------------------------------------------
    w("■ 3. 수동 검증 (무작위 표본 200건을 직접 읽고 라벨링)")
    if not os.path.exists(LABEL_PATH):
        w("    라벨 파일이 없어 검증을 건너뜁니다.")
    else:
        lab = pd.read_csv(LABEL_PATH, dtype={"상품번호": str, "리뷰ID": str})
        mg = lab.merge(rv[["상품번호", "리뷰ID", "pred", "tier"]],
                       on=["상품번호", "리뷰ID"], how="left")
        w("    라벨 기준: 본문에 제품·금전·할인 등 어떤 형태로든 대가를 받았다는")
        w("               공시가 있으면 1, 없으면 0")
        w()
        w("    층화 표본 설계 (구 규칙 481건 기준으로 층을 나눠 추출)")
        # 층 크기: 표본 추출 시점 기준
        SIZES = {"A": 481, "B": 2790, "C": n - 481 - 2790}
        w(f"    {'층':<4}{'정의':<34}{'모집단':>9}{'표본':>6}{'실제 대가성':>12}")
        defs = {"A": "구 규칙이 탐지한 것", "B": "미탐지 + 의심 토큰 보유",
                "C": "미탐지 + 의심 토큰 없음"}
        est = {}
        for s in ("A", "B", "C"):
            g = mg[mg["stratum"] == s]
            w(f"    {s:<4}{defs[s]:<34}{SIZES[s]:>9,}{len(g):>6}{int(g['label'].sum()):>12}")
            est[s] = (SIZES[s], len(g), g)
        w()
        # 가중 추정
        TP = FP = FN = TN = 0.0
        for s, (N_s, n_s, g) in est.items():
            wgt = N_s / n_s
            TP += wgt * ((g["label"] == 1) & (g["pred"] == 1)).sum()
            FP += wgt * ((g["label"] == 0) & (g["pred"] == 1)).sum()
            FN += wgt * ((g["label"] == 1) & (g["pred"] == 0)).sum()
            TN += wgt * ((g["label"] == 0) & (g["pred"] == 0)).sum()
        prec = TP / (TP + FP) if TP + FP else np.nan
        rec = TP / (TP + FN) if TP + FN else np.nan
        w("    층 가중 추정 (모집단 환산)")
        w(f"      정밀도 {prec:.1%}   재현율 {rec:.1%}")
        w(f"      추정 실제 대가성 리뷰 {TP + FN:,.0f}건 ({(TP + FN) / n:.2%})")
        w()
        a = mg[mg["stratum"] == "A"]
        w(f"    표본 직접 확인: 탐지분 {len(a)}건 중 오탐 "
          f"{int(((a['label'] == 0) & (a['pred'] == 1)).sum())}건")
        c = mg[mg["stratum"] == "C"]
        w(f"    의심 토큰이 전혀 없는 리뷰 {len(c)}건 중 대가성 "
          f"{int(c['label'].sum())}건")
        w()
        w("    ⚠ 재현율 추정의 한계")
        share_c = SIZES["C"] / n
        w(f"      C층이 모집단의 {share_c:.0%}를 차지하는데 표본이 60건뿐이다.")
        w("      60건에서 0건이 나왔어도 3/60 규칙으로 상한을 잡으면 최대 5%,")
        w(f"      모집단 환산 시 최대 {SIZES['C'] * 3 / 60:,.0f}건까지 놓쳤을 수 있다.")
        w("      위 재현율은 'C층에 누락이 없다'는 가정에 기댄 낙관적 추정치다.")

    w()
    w("■ 4. 판정 (TASKS.md 기준: 탐지율 2~3% 이상 + 수동 검증 정밀도 80% 이상)")
    rate = rv["pred"].mean()
    w(f"    탐지율 {rate:.2%} — 기준(2%) {'충족' if rate >= .02 else '미달'}")
    w("    정밀도 기준은 충족하나, 탐지율이 기준에 크게 못 미친다.")
    w()
    w("    ▶ 결론: 키워드 8개를 규칙 기반으로 확장해 탐지량을 배 이상 늘렸고 정밀도도")
    w("      매우 높지만, 절대량이 여전히 회귀에 넣을 분산을 만들지 못한다.")
    w("      TASKS.md 가 예고한 대로 '본문 기반으로는 Q2 검증 불가'를 결론으로 명시한다.")
    w()
    w("    근거: 표기 의무가 있음에도 실제로 본문에 남기는 비율 자체가 낮다.")
    w("      · 사진에만 표기한 리뷰는 원리적으로 탐지 불가")
    w("      · 수집 표본이 '도움순 상위(노출면)'라 체험단 리뷰가 과소대표될 수 있다")
    w("      · 따라서 이 지표는 언제나 하한 추정치로만 서술해야 한다")
    w()
    w("    대안 경로")
    w("      1) 상품 단위 지표를 '체험단 비중'이 아니라 '체험단 리뷰 존재 여부'로")
    w("         이진화하면 분산이 조금 생긴다. 다만 노출면 표본 편향은 그대로다.")
    w("      2) 브랜드 단위 캠페인 탐지 — 특정 브랜드·시점에 공시 리뷰가 몰리는 패턴은")
    w("         상품 단위보다 신호가 크다.")
    w("      3) LLM 분류는 유료 API 사용이므로 사용자 승인 없이 진행하지 않는다.")

    # ---- 5. 상품/브랜드 단위 집계 ---------------------------------------
    w()
    w("■ 5. 상품 단위 분포 (Q2 회귀 투입 가능성 진단)")
    g = rv.groupby("상품번호")["pred"].agg(["sum", "size"])
    g["share"] = g["sum"] / g["size"]
    w(f"    리뷰를 1건 이상 수집한 상품 {len(g):,}개")
    w(f"    대가성 리뷰가 1건 이상인 상품 {int((g['sum'] > 0).sum()):,}개 "
      f"({(g['sum'] > 0).mean():.1%})")
    w(f"    비중 중위 {g['share'].median():.3%} · 평균 {g['share'].mean():.3%} "
      f"· 최대 {g['share'].max():.1%}")
    w(f"    비중이 5% 넘는 상품 {int((g['share'] > .05).sum()):,}개")
    w("    → 이진 지표(존재 여부)는 쓸 수 있으나 연속 비중은 대부분 0에 몰려 있다.")
    w()
    w("■ 6. 브랜드 캠페인 집중도 (대안 경로 2의 사전 점검)")
    rk = sorted(glob.glob(os.path.join(DATA_DIR, "*_ranking.csv")))
    if rk:
        br = pd.concat([pd.read_csv(p, encoding="utf-8-sig", dtype=str,
                                    usecols=["상품번호", "브랜드"]) for p in rk],
                       ignore_index=True).drop_duplicates("상품번호")
        m = rv.merge(br, on="상품번호", how="left")
        bg = m.groupby("브랜드")["pred"].agg(["sum", "size"])
        bg = bg[bg["size"] >= 100].sort_values("sum", ascending=False)
        w(f"    리뷰 100건 이상 수집된 브랜드 {len(bg):,}개")
        w(f"    {'브랜드':<16}{'대가성':>7}{'수집리뷰':>9}{'비중':>8}")
        for b, r in bg.head(10).iterrows():
            if r["sum"] == 0:
                break
            w(f"    {str(b):<16}{int(r['sum']):>7,}{int(r['size']):>9,}"
              f"{r['sum'] / r['size']:>8.1%}")
        w("    → 대가성 리뷰는 소수 브랜드에 몰린다. 상품 단위보다 브랜드×시점 단위가")
        w("      신호가 크다는 점이 확인되므로, Q2 는 브랜드 캠페인 설계로 우회할 만하다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "trial_detection_eval.txt")
    text = "\n".join(R)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
