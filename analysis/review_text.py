"""리뷰 본문 텍스트 분석 (보고서 5.9절).

- 리뷰 본문에서 소비자가 실제로 언급하는 어휘를 추출한다
- 순위 상위권 / 하위권 상품의 리뷰에서 변별되는 어휘를 비교한다
- 사전 정의한 소구 속성별 언급률을 순위 구간으로 나누어 집계한다

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
                seen.add(rid)
                rows.append(r)
    return rows


def load_mean_rank() -> tuple[dict[str, float], dict[str, str]]:
    """상품별 카테고리 랭킹 평균 순위와 대표 카테고리 (8/5 이후 패널 기준)."""
    acc = defaultdict(list)
    cats = defaultdict(Counter)
    for f in sorted(glob.glob(os.path.join(DATA, "*_ranking.csv"))):
        date = os.path.basename(f)[:10]
        if date < PANEL_FROM:
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


def log_odds(a: Counter, b: Counter, vocab: list[str], alpha: float = 1.0) -> dict[str, float]:
    """두 집단의 변별 어휘 — 사전확률을 둔 로그오즈비 (z 점수)."""
    na, nb = sum(a.values()), sum(b.values())
    res = {}
    for w in vocab:
        ya, yb = a[w] + alpha, b[w] + alpha
        d = math.log(ya / (na + alpha - ya)) - math.log(yb / (nb + alpha - yb))
        var = 1 / ya + 1 / yb
        res[w] = d / math.sqrt(var)
    return res


def product_level(reviews: list[dict], mean_rank: dict[str, float],
                  min_reviews: int = 20) -> dict:
    """상품을 하나의 관측으로 묶어 구간 간 비율 차이를 검정한다."""
    per = defaultdict(lambda: {"n": 0, "paid": 0, "rep": 0, "tier": None})
    for r in reviews:
        body = (r.get("리뷰본문") or "").strip()
        if len(body) < 10:
            continue
        goods = r.get("상품번호")
        mr = mean_rank.get(goods)
        if mr is None:
            continue
        tier = "top" if mr <= 25 else ("bottom" if mr >= 76 else None)
        if tier is None:
            continue
        d = per[goods]
        d["tier"] = tier
        d["n"] += 1
        if PAID.search(body):
            d["paid"] += 1
        if r.get("재구매") == "1":
            d["rep"] += 1

    groups = {"top": defaultdict(list), "bottom": defaultdict(list)}
    for d in per.values():
        if d["n"] < min_reviews:
            continue
        for key in ("paid", "rep"):
            groups[d["tier"]][key].append(d[key] / d["n"] * 100)

    res = {"min_reviews": min_reviews,
           "n_products": {t: len(groups[t]["paid"]) for t in groups}}
    for key, label in (("paid", "대가성 공시 표기율"), ("rep", "재구매 표시율")):
        a, b = groups["top"][key], groups["bottom"][key]
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        va = sum((x - ma) ** 2 for x in a) / len(a)
        vb = sum((x - mb) ** 2 for x in b) / len(b)
        se = math.sqrt(va / len(a) + vb / len(b))
        res[key] = {"label": label, "top": round(ma, 2), "bottom": round(mb, 2),
                    "t": round(abs(ma - mb) / se, 2) if se else 0.0}
    return res


def main() -> None:
    reviews = load_reviews()
    mean_rank, rep_cat = load_mean_rank()

    doc_freq = Counter()
    tier_docs = {"top": 0, "bottom": 0}
    attr_hits = {"top": Counter(), "bottom": Counter()}
    struct = {"top": Counter(), "bottom": Counter()}
    n_len = {"top": [], "bottom": []}
    paid = {"top": 0, "bottom": 0}
    n_texts = 0
    # 카테고리 교란 통제용: 카테고리별 · 구간별 토큰 집계
    by_cat = defaultdict(lambda: {"top": Counter(), "bottom": Counter()})
    cat_docs = defaultdict(lambda: {"top": 0, "bottom": 0})

    for r in reviews:
        body = (r.get("리뷰본문") or "").strip()
        if len(body) < 10:
            continue
        n_texts += 1
        toks = tokenize(body)
        doc_freq.update(set(toks))

        goods = r.get("상품번호")
        mr = mean_rank.get(goods)
        if mr is None:
            continue
        tier = "top" if mr <= 25 else ("bottom" if mr >= 76 else None)
        if tier is None:
            continue

        tier_docs[tier] += 1
        n_len[tier].append(len(body))
        cat = rep_cat.get(goods, "기타")
        by_cat[cat][tier].update(toks)
        cat_docs[cat][tier] += 1

        if PAID.search(body):
            paid[tier] += 1
        for name, keys in ATTRS:
            if any(k in body for k in keys):
                attr_hits[tier][name] += 1
        if r.get("포토여부") == "1":
            struct[tier]["photo"] += 1
        if r.get("재구매") == "1":
            struct[tier]["repurchase"] += 1

    # 워드클라우드 — 문서빈도 기준 (한 리뷰에 여러 번 나와도 1회)
    merged = Counter()
    for w, n in doc_freq.items():
        merged[MERGE.get(w, w)] += n
    cloud = [[w, n] for w, n in merged.most_common(48)]

    # 변별 어휘 — 카테고리 안에서 구간을 비교한 뒤 카테고리 간 평균
    #   같은 카테고리 안에서만 비교하므로 '샴푸·네일' 같은 품목 고유명사가 걸러진다
    per_word = defaultdict(list)
    for cat, cnt in by_cat.items():
        if cat_docs[cat]["top"] < 150 or cat_docs[cat]["bottom"] < 150:
            continue  # 표본이 얇은 카테고리는 제외
        vocab = [w for w in set(cnt["top"]) | set(cnt["bottom"])
                 if cnt["top"][w] + cnt["bottom"][w] >= 20]
        z = log_odds(cnt["top"], cnt["bottom"], vocab)
        for w, s_ in z.items():
            per_word[w].append(s_)

    MIN_CATS = 4
    agg = {w: sum(v) / len(v) for w, v in per_word.items() if len(v) >= MIN_CATS}
    ranked = sorted(agg.items(), key=lambda kv: kv[1])
    distinct = {
        "top": [[w, round(sc, 2), len(per_word[w])] for w, sc in ranked[::-1][:10]],
        "bottom": [[w, round(sc, 2), len(per_word[w])] for w, sc in ranked[:10]],
    }
    n_cats = sum(1 for c in by_cat if cat_docs[c]["top"] >= 150 and cat_docs[c]["bottom"] >= 150)

    attrs = []
    for name, _ in ATTRS:
        t = attr_hits["top"][name] / tier_docs["top"] * 100
        b = attr_hits["bottom"][name] / tier_docs["bottom"] * 100
        attrs.append([name, round(t, 1), round(b, 1)])
    attrs.sort(key=lambda x: -max(x[1], x[2]))

    out = {
        "corpus": {
            "reviews": n_texts,
            "top_docs": tier_docs["top"],
            "bottom_docs": tier_docs["bottom"],
            "cats_used": n_cats,
        },
        "cloud": cloud,
        "distinct": distinct,
        "attrs": attrs,
        "paid": {
            "top": round(paid["top"] / tier_docs["top"] * 100, 2),
            "bottom": round(paid["bottom"] / tier_docs["bottom"] * 100, 2),
            "top_n": paid["top"],
            "bottom_n": paid["bottom"],
        },
        "struct": {
            "top": {
                "photo": round(struct["top"]["photo"] / tier_docs["top"] * 100, 1),
                "repurchase": round(struct["top"]["repurchase"] / tier_docs["top"] * 100, 1),
                "len": round(sum(n_len["top"]) / len(n_len["top"]), 1),
            },
            "bottom": {
                "photo": round(struct["bottom"]["photo"] / tier_docs["bottom"] * 100, 1),
                "repurchase": round(struct["bottom"]["repurchase"] / tier_docs["bottom"] * 100, 1),
                "len": round(sum(n_len["bottom"]) / len(n_len["bottom"]), 1),
            },
        },
    }
    # 상품 단위 비교 — 리뷰 단위로 세면 같은 상품의 반복 관측이 유의성을 부풀린다 (4.1절)
    out["by_product"] = product_level(reviews, mean_rank)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out["corpus"], ensure_ascii=False))
    print("상위권 변별:", [(w, s_) for w, s_, _ in distinct["top"]])
    print("하위권 변별:", [(w, s_) for w, s_, _ in distinct["bottom"]])
    print("대가성:", out["paid"])
    print("속성:", attrs)
    print("구조:", out["struct"])


if __name__ == "__main__":
    main()
