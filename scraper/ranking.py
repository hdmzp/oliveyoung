"""랭킹(판매 베스트) 페이지 수집·파싱.

getBestList.do 는 서버 렌더링 HTML을 돌려준다.
ul.cate_prd_list > li 반복, 각 항목에서 순위/브랜드/상품명/링크/가격/뱃지 추출.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from . import config
from .http_client import Client

log = logging.getLogger(__name__)

_NUM = re.compile(r"[\d,]+")


def _num(text: str | None) -> int | None:
    if not text:
        return None
    m = _NUM.search(text)
    return int(m.group().replace(",", "")) if m else None


def _img_url(li) -> str:
    """썸네일(대표이미지) URL 추출. 지연로딩(data-original 등) + 프로토콜상대 URL 방어."""
    img = li.select_one("a.prd_thumb img") or li.select_one("img")
    if img is None:
        return ""
    url = ""
    for attr in ("src", "data-original", "data-src", "data-lazy", "data-echo"):
        v = (img.get(attr) or "").strip()
        # 지연로딩 플레이스홀더(투명 gif/data URI)는 건너뛰고 실제 URL을 찾는다
        if v and not v.startswith("data:") and "blank" not in v and "loading" not in v:
            url = v
            break
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = config.BASE + url
    return url


def fetch_ranking(client: Client, flt_disp_cat_no: str) -> list[dict]:
    """카테고리 하나의 랭킹 목록을 가져와 파싱한다. flt=""이면 전체."""
    resp = client.get(config.BEST_LIST_URL, params={
        "dispCatNo": config.BEST_DISP_CAT_NO,
        "fltDispCatNo": flt_disp_cat_no,
        "pageIdx": "1",
        "rowsPerPage": "8",
    }, referer=config.BEST_LIST_URL)
    return parse_ranking_html(resp.text, flt_disp_cat_no)


def parse_ranking_html(html: str, flt_disp_cat_no: str) -> list[dict]:
    """TOP100이 여러 개의 ul.cate_prd_list(행당 4개)로 나뉘어 있어 전부 순회한다."""
    soup = BeautifulSoup(html, "lxml")
    category_name = config.CATEGORIES.get(flt_disp_cat_no, flt_disp_cat_no)
    items = []
    seen_goods = set()
    lis = soup.select("ul.cate_prd_list > li")
    if not lis:
        raise ValueError(f"ranking list not found (category={category_name})")
    for idx, li in enumerate(lis, start=1):
        info = li.select_one("div.prd_info")
        if info is None:
            continue
        a = info.select_one("a.prd_thumb") or info.select_one("a[data-ref-goodsno]")
        goods_no = a.get("data-ref-goodsno") if a else None
        if not goods_no:
            href = a.get("href", "") if a else ""
            qs = parse_qs(urlparse(href).query)
            goods_no = (qs.get("goodsNo") or [None])[0]
        if not goods_no:
            log.warning("skip item without goodsNo (category=%s idx=%d)", category_name, idx)
            continue
        if goods_no in seen_goods:  # 같은 목록 내 중복 방어
            continue
        seen_goods.add(goods_no)

        rank_el = info.select_one("span.thumb_flag")
        rank = _num(rank_el.get_text()) if rank_el else idx

        brand_el = info.select_one("span.tx_brand")
        name_el = info.select_one("p.tx_name")

        price_org = _num(t.get_text()) if (t := info.select_one(".prd_price .tx_org .tx_num")) else None
        price_cur = _num(t.get_text()) if (t := info.select_one(".prd_price .tx_cur .tx_num")) else None
        if price_org is None:
            price_org = price_cur  # 할인 없는 상품은 현재가만 노출됨

        flags = {f.get_text(strip=True) for f in info.select(".prd_flag .icon_flag")}

        items.append({
            "카테고리ID": flt_disp_cat_no or "ALL",
            "카테고리": category_name,
            "순위": rank,
            "브랜드": brand_el.get_text(strip=True) if brand_el else "",
            "상품명": name_el.get_text(strip=True) if name_el else "",
            "상품번호": goods_no,
            "상품페이지링크": f"{config.GOODS_DETAIL_URL}?goodsNo={goods_no}",
            "대표이미지URL": _img_url(li),
            "정가": price_org,
            "혜택가": price_cur,
            "할인율": round((1 - price_cur / price_org) * 100, 1)
                     if price_org and price_cur and price_org > 0 else 0,
            "세일": int("세일" in flags),
            "쿠폰": int("쿠폰" in flags),
            "증정": int("증정" in flags),
            "오늘드림": int("오늘드림" in flags),
        })
    return items


def collect_all_rankings(client: Client) -> list[dict]:
    """전체 + 모든 카테고리 랭킹 수집. 카테고리 하나 실패해도 계속 진행."""
    all_items: list[dict] = []
    failures = []
    for cat_id, cat_name in config.CATEGORIES.items():
        try:
            items = fetch_ranking(client, cat_id)
            if not items:
                raise ValueError("0 items parsed")
            log.info("ranking [%s] %d items", cat_name, len(items))
            all_items.extend(items)
        except Exception as exc:
            log.error("ranking [%s] failed: %s", cat_name, exc)
            failures.append((cat_id, cat_name, str(exc)))
    if not all_items:
        raise RuntimeError(f"all ranking categories failed: {failures}")
    return all_items
