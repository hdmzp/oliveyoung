"""리뷰 API 동작 진단 (선택). 실제 수집 코드가 쓰는 엔드포인트를 점검한다.

  python -m scraper.probe_json --goods-no A000000247086
"""
from __future__ import annotations

import argparse
import json

from . import config, reviews
from .http_client import Client


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goods-no", default="A000000247086")
    goods_no = ap.parse_args().goods_no
    client = Client()

    print("== 랭킹 접속 확인 ==")
    from . import ranking
    items = ranking.fetch_ranking(client, "")
    print(f"  전체 랭킹 {len(items)}개 파싱 OK (1위: {items[0]['브랜드']} / {items[0]['상품명'][:30]})")

    print("\n== 리뷰수·별점 (stats) ==")
    print("  " + json.dumps(reviews.fetch_product_stats(client, goods_no), ensure_ascii=False))

    print("\n== 리뷰 목록 첫 페이지 (cursor) ==")
    revs, cid, cscore, has_next = reviews.fetch_review_page(client, goods_no)
    print(f"  {len(revs)}건, hasNext={has_next}")
    for r in revs[:3]:
        print(f"   - {r['작성일']} {r['별점']}점 체험단={r['체험단여부']}({r['리뷰타입']}) "
              f"피부={r['피부타입']} 도움={r['도움수']} | {r['리뷰본문'][:40]}")
    print("\nprobe 완료.")


if __name__ == "__main__":
    main()
