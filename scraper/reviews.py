"""올리브영 신 리뷰 API(m.oliveyoung.co.kr) 수집.

- 리뷰수/평균별점/별점분포:  GET  /review/api/v2/reviews/{goodsNo}/stats
- 리뷰 목록(본문·별점·작성일·체험단·피부): POST /review/api/v2/reviews/cursor

리뷰 목록은 "도움순(best)" 고정 정렬로만 제공되므로, 신규 리뷰는
reviewId(전역 증가 정수)를 커서 상태(seen_ids)에 기록해 중복 없이 수집한다.
"""
from __future__ import annotations

import logging

from . import config
from .http_client import Client, FetchError

log = logging.getLogger(__name__)


def is_trial(review_type: str | None) -> int:
    """reviewType 이 NORMAL 이 아니면 체험단/기획 리뷰로 간주."""
    return int(bool(review_type) and review_type != config.NORMAL_REVIEW_TYPE)


# ----------------------------------------------------------- 리뷰수/별점

def fetch_product_stats(client: Client, goods_no: str) -> dict:
    """리뷰수·평균별점·별점분포. 리뷰 없으면 0/None."""
    url = config.REVIEW_API_HOST + config.REVIEW_STATS_PATH.format(goods_no=goods_no)
    resp = client.request("GET", url, headers=config.REVIEW_HEADERS)
    body = resp.json()
    data = body.get("data")
    if not data:  # NOT_FOUND 등 (리뷰 없는 상품)
        return {"리뷰수": 0, "리뷰별점": None,
                "별점5비율": None, "별점4비율": None, "별점3비율": None,
                "별점2비율": None, "별점1비율": None}
    rd = data.get("ratingDistribution") or {}
    dist = {s.get("rating"): s.get("percentage")
            for s in rd.get("ratingStatDtos", [])}
    return {
        "리뷰수": data.get("reviewCount"),
        "리뷰별점": rd.get("averageRating"),
        "별점5비율": dist.get(5), "별점4비율": dist.get(4), "별점3비율": dist.get(3),
        "별점2비율": dist.get(2), "별점1비율": dist.get(1),
    }


# ----------------------------------------------------------- 리뷰 목록

def _parse_review(r: dict) -> dict:
    prof = r.get("profileDto") or {}
    goods = r.get("goodsDto") or {}
    rtype = r.get("reviewType", "")
    return {
        "리뷰ID": r.get("reviewId"),
        "작성일": r.get("createdDateTime", ""),
        "별점": r.get("reviewScore"),
        "체험단여부": is_trial(rtype),
        "리뷰타입": rtype,
        "옵션": goods.get("optionName", ""),
        "피부타입": prof.get("skinType", "") or "",
        "피부톤": prof.get("skinTone", "") or "",
        "피부고민": ",".join(prof.get("skinTrouble") or []),
        "도움수": r.get("recommendCount"),
        "유용점수": r.get("usefulPoint"),
        "포토여부": int(bool(r.get("hasPhoto"))),
        "재구매": int(bool(r.get("isRepurchase"))),
        "닉네임": prof.get("memberNickname", "") or "",
        "리뷰본문": r.get("content", "") or "",
    }


def fetch_review_page(client: Client, goods_no: str,
                      cursor_id=None, cursor_score=None):
    """리뷰 한 페이지. 반환: (리뷰 목록, next_cursor_id, next_cursor_score, has_next)."""
    body = {
        "goodsNumber": goods_no,
        "sort": "RECENT",
        "cursorId": cursor_id,
        "cursorScore": cursor_score,
        "pageSize": config.REVIEW_PAGE_SIZE,
    }
    resp = client.request("POST", config.REVIEW_API_HOST + config.REVIEW_CURSOR_PATH,
                          json=body, headers=config.REVIEW_HEADERS)
    data = resp.json().get("data") or {}
    reviews = [_parse_review(r) for r in data.get("goodsReviewList", [])]
    return reviews, data.get("nextCursorId"), data.get("nextCursorScore"), \
        bool(data.get("hasNext"))


def collect_new_reviews(client: Client, goods_no: str, cursor: dict) -> tuple[list[dict], dict]:
    """seen_ids 이후의 신규 리뷰만 수집.

    cursor: {"seen_ids": [reviewId, ...]}
    반환: (신규 리뷰 목록, 갱신된 커서)
    """
    seen = set(cursor.get("seen_ids", []))
    first_run = not seen
    new_reviews: list[dict] = []
    cid, cscore = None, None

    for page in range(config.MAX_REVIEW_PAGES_PER_DAY):
        reviews, cid, cscore, has_next = fetch_review_page(client, goods_no, cid, cscore)
        if not reviews:
            break
        fresh = [r for r in reviews if r["리뷰ID"] not in seen]
        new_reviews.extend(fresh)
        hit_seen = len(fresh) < len(reviews)  # 이미 수집한 리뷰에 도달
        if not has_next or hit_seen:
            break
        if first_run and page + 1 >= config.FIRST_RUN_MAX_PAGES:
            break

    ids = [r["리뷰ID"] for r in new_reviews] + list(cursor.get("seen_ids", []))
    # 순서 유지 중복 제거 후 상한 유지
    deduped, saw = [], set()
    for i in ids:
        if i not in saw:
            saw.add(i); deduped.append(i)
    return new_reviews, {"seen_ids": deduped[:config.SEEN_IDS_KEEP]}
