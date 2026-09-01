"""리뷰 본문 텍스트 분석 (보고서 5.9절).

순위와의 연관성을 검증하는 절이 아니라, 수집한 리뷰 본문이 어떤 내용으로
채워져 있는지를 기술적으로 정리하는 부가 분석이다.

- 리뷰 본문에서 소비자가 실제로 사용하는 어휘를 추출한다
- 사전 정의한 소구 속성 10종의 언급률을 전체·카테고리별로 집계한다
- 포토 첨부·재구매 표시·본문 길이 등 리뷰의 구조적 특성을 요약한다

사용:  python -m analysis.review_text
출력:  analysis/output/review_text.json  (웹 리포트가 읽는 집계 결과)
"""
from __future__ import annotations

import csv
import glob
import json
import math
import os
import re
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "analysis", "output", "review_text.json")

# 카테고리 수집이 안정된 이후 구간만 순위 결합에 사용 (2.2절과 동일 기준)
PANEL_FROM = "2026-08-05"
# 보고서 관측 종료일. 이후 수집분은 보고서 기간(2.2절)과 어긋나므로 제외한다
PANEL_TO = "2026-09-01"

HANGUL = re.compile(r"[가-힣]+")
# 조사·어미 꼬리를 벗겨 어간에 가깝게 만든다 (형태소 분석기 없이 근사)
TAIL = re.compile(
    r"(이에요|예요|입니다|습니다|했어요|하네요|같아요|이라서|이라고|에서는|에게는"
    r"|에서|에게|으로|처럼|이라|라고|한테|까지|부터|이고|이나|하고|보다|마다|조차"
    r"|밖에|이랑|는데|은데|해서|하는|이다|의|가|이|을|를|은|는|에|와|과|도|만|로|랑|께|서|요)$"
)

# 내용어가 아닌 고빈도 어휘 (부사·용언 활용형·지시어 등)
STOP = set("""
좋아 좋은 좋고 좋았어 좋다 좋네 너무 진짜 정말 아주 엄청 완전 되게 매우 조금 살짝 약간 많이 자주 계속
있어 있는 있고 있습니다 있었어 없이 없어 없고 없는 않아 않고 않은 않아서 같은 같이 같고 그래 그냥 근데
저는 제가 저도 우리 이거 그거 저거 이건 그건 요건 여기 거기 이번 다음 다른 여러 모든 무슨 어떤 이런 그런
쓰고 쓰기 쓰는 써서 썼어 사용 사용하기 사용할 사용해 바르고 바르기 바르면 발라 발랐 구매 구입 주문 배송
생각 마음 정도 하나 두개 처음 다시 바로 이제 아직 이미 항상 평소 요즘 최근 전에 나중 오래 금방 얼른
하고 해서 하면 하니 하지 되고 되는 되어 됐어 봤어 보고 보니 보면 들어 나와 나서 가서 와서 받아 받고
분들 사람 사용감 님들 여러분 대박 굿굿 강추 추천 후기 리뷰 상품 제품 가지 부분 경우 때문 이유 정말로
같아요 좋습니다 합니다 입니다 했습니다 있습니다 그리고 그래서 하지만 그러나 또한 역시 특히 확실히 거의
구매했 사용했 사용중 써봤 발랐어 느껴져 느껴지 괜찮 나름 딱히 별로 워낙 은근 무난 그만큼 이렇게 저렇게
많은데 작은 시원 오메 일부 솔직한 지원받았 제품비 판매자
있는데 편이라 일단 아니라 후에 사용하면 가장 한번 제일 좋았 손이 기분 그런지 한다는 하는데 되어서
같아 같습니다 훨씬 쓰면 원래 함께 정말이지 그런데 이라서 라서 하나요 였어요
""".split())

# 표기 변형 병합 (워드클라우드 표시용)
MERGE = {"향이": "향", "향도": "향", "향은": "향", "촉촉하게": "촉촉", "느낌이": "느낌"}

# 소비자 소구 속성 사전 — 각 속성은 대표 키워드 묶음으로 정의한다
ATTRS = [
    ("자극·순함", ["자극", "순하", "따갑", "따가움", "예민", "민감", "무자극", "저자극", "트러블없"]),
    ("보습·수분", ["보습", "수분", "촉촉", "건조", "당김", "속건조", "촉촉함", "수분감"]),
    ("발림·제형", ["제형", "발림", "부드럽", "묽", "꾸덕", "흡수", "겉돌", "밀리"]),
    ("끈적임·마무리", ["끈적", "산뜻", "번들", "매트", "백탁", "유분"]),
    ("향", ["향이", "향기", "냄새", "무향", "향은", "향도"]),
    ("가격·가성비", ["가격", "가성비", "저렴", "비싸", "할인", "세일", "가심비"]),
    ("지속력", ["지속", "무너지", "유지", "오래가", "지속력"]),
    ("트러블·진정", ["트러블", "여드름", "진정", "붉은기", "홍조", "뾰루지"]),
    ("커버·발색", ["커버", "발색", "밀착", "잡티", "톤업"]),
    ("재구매 의사", ["재구매", "또사", "또 사", "리필", "쟁여", "여러개", "재구입"]),
]


# 5.8절 대가성 공시 탐지 규칙 중 '명시적 공시 표현'에 해당하는 대표 패턴
PAID = re.compile(
    r"(체험단|제공받아|제공 받아|제공받았|무상\s*제공|업체로부터|업체에서 제공|광고주"
    r"|제품비를? 지원|지원받아|지원받았|협찬|서포터즈|앰배서더|제품제공|소정의 (원고료|고료))"
)


def load_reviews() -> list[dict]:
    files = sorted(glob.glob(os.path.join(DATA, "*_reviews.csv")))
    bf = os.path.join(DATA, "backfill", "top100_reviews.csv")
    if os.path.exists(bf):
        files.append(bf)
    seen, rows = set(), []
    for f in files:
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                rid = r.get("리뷰ID")
                if not rid or rid in seen:
                    continue
                if (r.get("수집일자") or "") > PANEL_TO:
                    continue
                seen.add(rid)
                rows.append(r)
    return rows


def load_mean_rank() -> tuple[dict[str, float], dict[str, str]]:
    """상품별 카테고리 랭킹 평균 순위와 대표 카테고리 (8/5 이후 패널 기준)."""
    acc = defaultdict(list)
    cats = defaultdict(Counter)
    for f in sorted(glob.glob(os.path.join(DATA, "*_ranking.csv"))):
        date = os.path.basename(f)[:10]
        if not (PANEL_FROM <= date <= PANEL_TO):
            continue
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("카테고리") == "전체":
                    continue  # 전체 목록은 카테고리와 중복 관측이라 제외 (3장 분석 단위와 동일)
                try:
                    acc[r["상품번호"]].append(int(r["순위"]))
                    cats[r["상품번호"]][r["카테고리"]] += 1
                except (KeyError, ValueError):
                    continue
    mean = {g: sum(v) / len(v) for g, v in acc.items() if v}
    rep = {g: c.most_common(1)[0][0] for g, c in cats.items() if c}
    return mean, rep


def tokenize(text: str) -> list[str]:
    out = []
    for w in HANGUL.findall(text):
        while True:
            m = TAIL.search(w)
            if not m or len(w) - len(m.group(0)) < 2:
                break
            w = w[: len(w) - len(m.group(0))]
        if len(w) >= 2 and w not in STOP:
            out.append(w)
    return out


def main() -> None:
    reviews = load_reviews()
    _, rep_cat = load_mean_rank()

    doc_freq = Counter()
    attr_all = Counter()
    attr_by_cat = defaultdict(Counter)
    cat_docs = Counter()
    lengths = []
    photo = repurchase = 0
    stars = Counter()
    n_texts = 0

    for r in reviews:
        body = (r.get("리뷰본문") or "").strip()
        if len(body) < 10:
            continue
        n_texts += 1
        doc_freq.update(set(tokenize(body)))
        lengths.append(len(body))
        if r.get("포토여부") == "1":
            photo += 1
        if r.get("재구매") == "1":
            repurchase += 1
        try:
            stars[int(float(r.get("별점") or 0))] += 1
        except ValueError:
            pass

        hit = [name for name, keys in ATTRS if any(k in body for k in keys)]
        attr_all.update(hit)
        cat = rep_cat.get(r.get("상품번호"))
        if cat:
            cat_docs[cat] += 1
            attr_by_cat[cat].update(hit)

    merged = Counter()
    for w, n in doc_freq.items():
        merged[MERGE.get(w, w)] += n
    cloud = [[w, n] for w, n in merged.most_common(48)]

    attrs = sorted(
        ([name, round(attr_all[name] / n_texts * 100, 1)] for name, _ in ATTRS),
        key=lambda x: -x[1],
    )
    order = [a[0] for a in attrs]

    # 카테고리 × 속성 언급률 — 리뷰 표본이 충분한 카테고리만
    MIN_DOCS = 800
    cats = [c for c, n in cat_docs.most_common() if n >= MIN_DOCS]
    profile = [
        {
            "cat": c,
            "n": cat_docs[c],
            "rates": [round(attr_by_cat[c][a] / cat_docs[c] * 100, 1) for a in order],
        }
        for c in cats
    ]

    lengths.sort()
    out = {
        "corpus": {
            "reviews": n_texts,
            "cats_used": len(cats),
            "min_docs": MIN_DOCS,
        },
        "cloud": cloud,
        "attrs": attrs,
        "profile": {"attrs": order, "rows": profile},
        "struct": {
            "photo": round(photo / n_texts * 100, 1),
            "repurchase": round(repurchase / n_texts * 100, 1),
            "len_mean": round(sum(lengths) / len(lengths)),
            "len_median": lengths[len(lengths) // 2],
            "len_p90": lengths[int(len(lengths) * 0.9)],
            "stars": {str(k): stars[k] for k in sorted(stars)},
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out["corpus"], ensure_ascii=False))
    print("속성:", attrs)
    print("구조:", json.dumps(out["struct"], ensure_ascii=False))
    print("카테고리:", [(p["cat"], p["n"]) for p in profile])


if __name__ == "__main__":
    main()
