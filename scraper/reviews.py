"""상품별 리뷰 요약(리뷰수·별점)과 리뷰 본문(증분) 수집.

상세 페이지는 신규 웹컴포넌트(Lit) 기반이라 소스별 전략을 순서대로 시도하고,
처음 성공한 전략을 이후 상품에도 재사용한다.

- summary: ① 상세 페이지 SSR(declarative shadow DOM) 정규식 ② 레거시 gdas AJAX
- page(리뷰 목록): ① 레거시 gdas AJAX(HTML 파셜) ② probe로 확인된 신규 API(추후 확정)

실제 엔드포인트 동작은 .github/workflows/probe.yml 실행으로 검증하고
이 모듈을 확정한다.
"""
from __future__ import annotations

import hashlib
import logging
import re

from bs4 import BeautifulSoup

from . import config
from .http_client import Client, FetchError

log = logging.getLogger(__name__)

# probe 로 확인 후 확정되는 신규 리뷰 API 템플릿 (None 이면 미사용)
REVIEW_API_TEMPLATE: str | None = None

_RATING_SSR = re.compile(
    r'class="rating-score"[^>]*>\s*(?:<!--.*?-->\s*)*([0-9]+(?:\.[0-9]+)?)', re.S)
_COUNT_SSR = re.compile(
    r'class="total-count"[^>]*>\s*총\s*(?:<!--.*?-->\s*)*([\d,]+)\s*건', re.S)

GDAS_CANDIDATES = [
    (f"{config.BASE}/store/goods/getGdasListAjax.do",
     {"gdasSort": "01", "itemNo": "all_search", "colData": ""}),
    (f"{config.BASE}/store/goods/getGoodsArtcAjax.do",
     {"gdasSort": "01", "itemNo": "all_search", "type": ""}),
]

# 런타임에 결정되는 동작 전략 캐시
_working: dict[str, object] = {"summary": None, "page": None}


def is_trial_review(*texts: str) -> bool:
    joined = " ".join(t for t in texts if t)
    return any(k in joined for k in config.TRIAL_KEYWORDS)


# ---------------------------------------------------------------- summary

def parse_detail_ssr_summary(html: str) -> dict | None:
    """상세 페이지 HTML에서 SSR 된 리뷰 별점/총건수 추출."""
    m_score = _RATING_SSR.search(html)
    m_count = _COUNT_SSR.search(html)
    if not m_score and not m_count:
        return None
    return {
        "리뷰별점": float(m_score.group(1)) if m_score else None,
        "리뷰수": int(m_count.group(1).replace(",", "")) if m_count else None,
    }


def _summary_from_detail(client: Client, goods_no: str) -> dict | None:
    resp = client.get(config.GOODS_DETAIL_URL, params={"goodsNo": goods_no})
    return parse_detail_ssr_summary(resp.text)


def _summary_from_gdas(client: Client, goods_no: str) -> dict | None:
    result = _fetch_gdas_page(client, goods_no, 1)
    if result is None:
        return None
    summary, _reviews, _has_more = result
    return summary if summary.get("리뷰수") is not None else None


def fetch_review_summary(client: Client, goods_no: str) -> dict:
    """리뷰수/별점. 실패 시 FetchError."""
    order = [("detail_ssr", _summary_from_detail), ("gdas", _summary_from_gdas)]
    if _working["summary"]:
        order.sort(key=lambda x: x[0] != _working["summary"])
    last_exc = None
    for name, fn in order:
        try:
            result = fn(client, goods_no)
        except FetchError as exc:
            last_exc = exc
            continue
        if result and (result.get("리뷰수") is not None or result.get("리뷰별점") is not None):
            if _working["summary"] != name:
                log.info("review summary strategy: %s", name)
                _working["summary"] = name
            return result
    raise FetchError(f"no summary strategy worked for {goods_no}: {last_exc}")


# ---------------------------------------------------------------- review pages

def _review_id(goods_no: str, raw_id: str | None, date: str, text: str) -> str:
    if raw_id:
        return raw_id
    h = hashlib.sha1(f"{goods_no}|{date}|{text}".encode()).hexdigest()[:16]
    return f"h_{h}"


def _parse_gdas_html(goods_no: str, html: str) -> tuple[dict, list[dict], bool] | None:
    """레거시 리뷰 파셜(HTML) 파싱 — 방어적으로 여러 셀렉터 후보를 시도."""
    soup = BeautifulSoup(html, "lxml")

    summary = {"리뷰수": None, "리뷰별점": None}
    count_el = soup.select_one("#gdasCount, .gdas_count, [data-review-count]")
    if count_el:
        m = re.search(r"[\d,]+", count_el.get_text())
        if m:
            summary["리뷰수"] = int(m.group().replace(",", ""))
    else:
        m = re.search(r"총\s*([\d,]+)\s*건", soup.get_text(" ", strip=True))
        if m:
            summary["리뷰수"] = int(m.group(1).replace(",", ""))
    score_el = soup.select_one(".score_area .num, .point_area .num, b.point, .grade_num")
    if score_el:
        m = re.search(r"[0-9]+(?:\.[0-9]+)?", score_el.get_text())
        if m:
            summary["리뷰별점"] = float(m.group())

    items = soup.select("ul#gdasList > li, ul.gdas_list > li, .review_list > li, ul.inner_list > li")
    reviews = []
    for li in items:
        text_el = li.select_one(".txt_inner, .review_cont .txt, .cont, .review_txt")
        date_el = li.select_one(".date, .info_date, .day")
        score_el = li.select_one(".score_area .point, .review_point .point, .point")
        badge_els = li.select(".point_flag, .flag, .badge, .ico_flag")
        text = text_el.get_text("\n", strip=True) if text_el else li.get_text(" ", strip=True)[:500]
        date = date_el.get_text(strip=True) if date_el else ""
        rating = None
        if score_el:
            m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*점", score_el.get_text())
            if m:
                rating = float(m.group(1))
        badges = " ".join(b.get_text(strip=True) for b in badge_els)
        raw_id = li.get("data-gdas-seq") or li.get("data-review-id")
        full_text = li.get_text(" ", strip=True)
        reviews.append({
            "리뷰ID": _review_id(goods_no, raw_id, date, text),
            "작성일": date,
            "별점": rating,
            "리뷰본문": text,
            "뱃지": badges,
            "체험단여부": int(is_trial_review(badges, full_text)),
            "피부타입": "",
            "옵션": "",
            "도움수": None,
        })
    if summary["리뷰수"] is None and not reviews:
        return None
    has_more = bool(reviews)
    return summary, reviews, has_more


def _fetch_gdas_page(client: Client, goods_no: str, page_idx: int):
    for url, extra in GDAS_CANDIDATES:
        params = {"goodsNo": goods_no, "pageIdx": str(page_idx), **extra}
        try:
            resp = client.get(url, params=params,
                              referer=f"{config.GOODS_DETAIL_URL}?goodsNo={goods_no}")
        except FetchError:
            continue
        if "text/html" not in resp.headers.get("Content-Type", "") and not resp.text.strip():
            continue
        parsed = _parse_gdas_html(goods_no, resp.text)
        if parsed:
            return parsed
    return None


def fetch_review_page(client: Client, goods_no: str, page_idx: int) -> tuple[list[dict], bool]:
    """리뷰 한 페이지(최신순 지향). 반환: (리뷰 목록, 다음 페이지 존재 추정)."""
    result = _fetch_gdas_page(client, goods_no, page_idx)
    if result is None:
        raise FetchError(f"no review page strategy worked for {goods_no} p{page_idx}")
    _summary, reviews, has_more = result
    return reviews, has_more


def collect_new_reviews(client: Client, goods_no: str, cursor: dict) -> tuple[list[dict], dict]:
    """커서(state) 이후의 신규 리뷰만 수집.

    cursor: {"seen_ids": [...], "latest_date": "YYYY.MM.DD"}
    반환: (신규 리뷰 목록, 갱신된 커서)
    """
    seen = set(cursor.get("seen_ids", []))
    latest_date = cursor.get("latest_date", "")
    new_reviews: list[dict] = []
    first_run = not seen and not latest_date

    for page_idx in range(1, config.MAX_REVIEW_PAGES_PER_DAY + 1):
        reviews, has_more = fetch_review_page(client, goods_no, page_idx)
        if not reviews:
            break
        fresh = [r for r in reviews if r["리뷰ID"] not in seen]
        # 날짜 커서: 이미 수집한 최신 날짜보다 오래된 리뷰만 나오는 페이지면 중단
        if latest_date:
            fresh = [r for r in fresh if not r["작성일"] or r["작성일"] >= latest_date]
        new_reviews.extend(fresh)
        stop = (
            len(fresh) < len(reviews)          # 아는 리뷰를 만남 → 이후는 이미 수집됨
            or not has_more
            or (first_run and page_idx >= 3)   # 첫 실행은 최근 3페이지만 기준점으로
        )
        if stop:
            break

    ids = [r["리뷰ID"] for r in new_reviews] + list(cursor.get("seen_ids", []))
    dates = [r["작성일"] for r in new_reviews if r["작성일"]]
    new_cursor = {
        "seen_ids": ids[:config.SEEN_IDS_KEEP],
        "latest_date": max(dates + [latest_date]) if (dates or latest_date) else "",
    }
    return new_reviews, new_cursor
