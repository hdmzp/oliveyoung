"""엔드포인트 검증용 프로브 (GitHub Actions 에서 workflow_dispatch 로 실행).

- 랭킹 페이지: 접속/파싱 가능 여부
- 상세 페이지: SSR 리뷰 요약 존재 여부
- 레거시 gdas AJAX 후보: 응답 상태/내용
- (옵션) Playwright 로 상세 페이지를 열어 리뷰 API 네트워크 캡처

결과 요약은 stdout(런 로그)으로, 원문 응답은 probe_out/ (아티팩트)로 남긴다.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from . import config, ranking, reviews
from .http_client import Client

log = logging.getLogger(__name__)
OUT = Path("probe_out")


def _save(name: str, content: str):
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(content, encoding="utf-8")


def probe_ranking(client: Client):
    print("\n===== [1] ranking getBestList.do =====")
    try:
        items = ranking.fetch_ranking(client, "")
        print(f"OK: parsed {len(items)} items; first={json.dumps(items[0], ensure_ascii=False)}")
        return [it["상품번호"] for it in items[:3]]
    except Exception as exc:
        print(f"FAIL: {exc}")
        return []


def probe_detail(client: Client, goods_no: str):
    print(f"\n===== [2] goods detail SSR (goodsNo={goods_no}) =====")
    try:
        resp = client.get(config.GOODS_DETAIL_URL, params={"goodsNo": goods_no})
        _save(f"detail_{goods_no}.html", resp.text)
        print(f"HTTP {resp.status_code}, {len(resp.text)} bytes")
        summary = reviews.parse_detail_ssr_summary(resp.text)
        print(f"SSR summary: {summary}")
        for marker in ("rating-score", "total-count", "oy-review", "shadowrootmode"):
            print(f"  marker '{marker}': {resp.text.count(marker)} hits")
    except Exception as exc:
        print(f"FAIL: {exc}")


def probe_gdas(client: Client, goods_no: str):
    print(f"\n===== [3] legacy gdas candidates (goodsNo={goods_no}) =====")
    for url, extra in reviews.GDAS_CANDIDATES:
        params = {"goodsNo": goods_no, "pageIdx": "1", **extra}
        try:
            resp = client.get(url, params=params,
                              referer=f"{config.GOODS_DETAIL_URL}?goodsNo={goods_no}")
            name = url.rsplit("/", 1)[-1]
            _save(f"gdas_{name}_{goods_no}.txt", resp.text)
            snippet = re.sub(r"\s+", " ", resp.text[:400])
            print(f"{name}: HTTP {resp.status_code}, {len(resp.text)} bytes, "
                  f"ct={resp.headers.get('Content-Type')}\n  snippet: {snippet}")
        except Exception as exc:
            print(f"{url}: FAIL {exc}")


def probe_playwright(goods_no: str):
    print(f"\n===== [4] playwright network capture (goodsNo={goods_no}) =====")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed — skipping")
        return
    captured = []
    interesting = re.compile(r"review|gdas|artc|rating|star", re.I)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(user_agent=config.USER_AGENT)

        def on_response(response):
            url = response.url
            if interesting.search(url) and "image" not in (response.headers.get("content-type") or ""):
                try:
                    body = response.text()
                except Exception:
                    body = "<binary/unavailable>"
                captured.append({"url": url, "status": response.status,
                                 "content_type": response.headers.get("content-type", ""),
                                 "body_head": body[:1500]})
                idx = len(captured)
                _save(f"pw_capture_{idx:02d}.txt", f"{url}\n\n{body[:200000]}")

        page.on("response", on_response)
        page.goto(f"{config.GOODS_DETAIL_URL}?goodsNo={goods_no}",
                  wait_until="networkidle", timeout=60000)
        # 리뷰 영역까지 스크롤해 리뷰 API 호출 유도
        for _ in range(12):
            page.mouse.wheel(0, 1500)
            page.wait_for_timeout(700)
        page.wait_for_timeout(3000)
        html = page.content()
        _save(f"pw_rendered_{goods_no}.html", html)
        print(f"rendered DOM: {len(html)} bytes; SSR summary on rendered DOM: "
              f"{reviews.parse_detail_ssr_summary(html)}")
        browser.close()
    print(f"captured {len(captured)} review-related responses:")
    for c in captured:
        print(f"  [{c['status']}] {c['content_type']} {c['url']}")
    _save("pw_summary.json", json.dumps(captured, ensure_ascii=False, indent=1))


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--goods-no", default="A000000247086")
    ap.add_argument("--playwright", action="store_true")
    args = ap.parse_args()

    client = Client()
    top = probe_ranking(client)
    goods_no = args.goods_no or (top[0] if top else None)
    if not goods_no:
        sys.exit(1)
    probe_detail(client, goods_no)
    probe_gdas(client, goods_no)
    if args.playwright:
        probe_playwright(goods_no)
    print("\nprobe done.")


if __name__ == "__main__":
    main()
