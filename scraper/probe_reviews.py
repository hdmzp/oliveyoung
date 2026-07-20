"""리뷰 AJAX 엔드포인트의 올바른 파라미터 조합을 자동 탐색한다.

getGdasListAjax.do 가 리뷰 HTML 을 반환하는 것은 확인됐으나, 파라미터가 맞지 않으면
"등록된 상품평이 없습니다"가 온다. 여러 후보 조합(엔드포인트·정렬키·itemNo·메서드)을
시도하고, 각 응답에서 실제 리뷰 항목이 몇 개 파싱되는지 출력해 정답을 찾는다.

사용:
  python -m scraper.probe_reviews --goods-no A000000247086
결과 요약을 그대로 공유하면 reviews.py 를 확정할 수 있다.
원문 응답은 probe_out/ 에 저장된다.
"""
from __future__ import annotations

import argparse
import itertools
import re
from pathlib import Path

from bs4 import BeautifulSoup

from . import config
from .http_client import Client

OUT = Path("probe_out")

# 시도할 엔드포인트 (getGdasListAjax.do 가 리뷰 HTML 반환 확인됨 → 우선)
ENDPOINTS = [
    "getGdasListAjax.do",
    "getGdasListJson.do",
]
# 정렬 파라미터 이름 후보와 값 후보 (gdasSort 유력)
SORT_KEYS = ["gdasSort"]
SORT_VALUES = ["01", "02"]
# itemNo 후보 — 'all_search' 가 빈 결과 주범으로 의심됨. 빈값 우선.
ITEM_NOS = ["", "all"]
# 리뷰 목록 li 를 담는 컨테이너 후보
LIST_SELECTORS = [
    "ul.prd_review_list2 > li", "ul.prd_review_list > li",
    "#gdasList > li", "ul.gdas_list > li", ".review_list > li",
    "ul.inner_list > li",
]


def count_reviews(html: str) -> tuple[int, str]:
    """(리뷰 li 개수, 사용된 셀렉터). no_data 는 0 으로 본다."""
    if "등록된 상품평이 없습니다" in html:
        return 0, "no_data_message"
    soup = BeautifulSoup(html, "lxml")
    best_n, best_sel = 0, ""
    for sel in LIST_SELECTORS:
        lis = [li for li in soup.select(sel)
               if "no_data" not in (li.get("class") or [])]
        if len(lis) > best_n:
            best_n, best_sel = len(lis), sel
    return best_n, best_sel


def find_total_and_score(html: str) -> dict:
    """응답에서 총 리뷰수/평점 후보를 최대한 뽑아본다."""
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    out = {}
    m = re.search(r"총\s*([\d,]+)\s*건", text)
    if m:
        out["총건수(총N건)"] = m.group(1)
    m = re.search(r"([0-9]\.[0-9])\s*점", text)
    if m:
        out["평점(N.N점)"] = m.group(1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goods-no", default="A000000247086")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    client = Client()
    referer = f"{config.GOODS_DETAIL_URL}?goodsNo={args.goods_no}"
    hits = []
    tried = 0

    # 먼저 상세 페이지를 방문해 세션 쿠키를 정상화 (리뷰 조회에 세션 필요할 수 있음)
    try:
        client.get(config.GOODS_DETAIL_URL, params={"goodsNo": args.goods_no})
        print("detail page visited (session warmed)\n")
    except Exception as exc:
        print(f"detail warm failed (계속 진행): {exc}\n")

    print("=== 파라미터 조합 탐색 (리뷰 li 개수 > 0 인 조합을 찾는다) ===\n")
    for ep, sort_key, sort_val, item_no in itertools.product(
            ENDPOINTS, SORT_KEYS, SORT_VALUES, ITEM_NOS):
        # 조합 폭발 방지: 각 엔드포인트당 정렬키 1개만 바뀌는 식으로 제한
        params = {"goodsNo": args.goods_no, "pageIdx": "1",
                  sort_key: sort_val, "itemNo": item_no}
        url = f"{config.BASE}/store/goods/{ep}"
        tried += 1
        try:
            resp = client.get(url, params=params, referer=referer)
        except Exception:
            continue
        if not resp.text.strip():
            continue
        n, sel = count_reviews(resp.text)
        label = f"{ep}?{sort_key}={sort_val}&itemNo='{item_no}'"
        no_data = "등록된 상품평이 없습니다" in resp.text
        print(f"  [{len(resp.text):>6}B] n={n:<3} {'(no_data)' if no_data else ''} {label}")
        # 각 응답을 저장해 두어 실패해도 원문 분석 가능
        fname = f"rev_{ep}_{sort_key}{sort_val}_{item_no or 'empty'}.html"
        (OUT / fname).write_text(resp.text, encoding="utf-8")
        if n > 0:
            extra = find_total_and_score(resp.text)
            print(f"    ✔ REVIEWS FOUND via {sel} — 총계/평점 추정: {extra}")
            hits.append((label, n, sel, fname))
            if len(hits) >= 4:
                break

    print(f"\n총 {tried}개 조합 시도, 리뷰 반환 조합 {len(hits)}개")
    if hits:
        best = max(hits, key=lambda h: h[1])
        print(f"\n>>> 추천 조합: {best[0]}  (리뷰 {best[1]}개, 셀렉터 {best[2]})")
        print(f">>> 원문 저장: probe_out/{best[3]}")
        print("\n이 화면 전체와 함께, 위 원문 파일 첫 부분을 공유해 주세요.")
        print("아래는 첫 리뷰 항목 미리보기입니다:\n")
        html = (OUT / best[3]).read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "lxml")
        li = soup.select_one(best[2])
        if li:
            print(re.sub(r"\s+", " ", li.get_text(" ", strip=True))[:600])
            print("\n--- li 내부 클래스 구조 ---")
            for el in li.find_all(class_=True, limit=40):
                cls = ".".join(el.get("class"))
                txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True))[:50]
                print(f"  {el.name}.{cls}: {txt}")
    else:
        print("\n리뷰를 반환한 조합이 없습니다. probe_out/ 의 응답을 확인해야 합니다.")
        # 마지막 응답 하나라도 저장
    print("\nprobe_reviews done.")


if __name__ == "__main__":
    main()
