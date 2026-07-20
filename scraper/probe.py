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
from pathlib import Path

from . import config, ranking, reviews
from .http_client import Client

log = logging.getLogger(__name__)
OUT = Path("probe_out")


def _save(name: str, content: str):
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(content, encoding="utf-8")


def probe_block_signature():
    """403 응답의 헤더/본문을 그대로 덤프해 차단 주체(WAF)를 식별한다."""
    print("\n===== [0] block signature (raw request) =====")
    import requests
    try:
        r = requests.get(config.BEST_LIST_URL,
                         params={"dispCatNo": config.BEST_DISP_CAT_NO},
                         headers={"User-Agent": config.USER_AGENT,
                                  "Accept-Language": "ko-KR,ko;q=0.9"},
                         timeout=(10, 30))
        print(f"status={r.status_code}")
        for k in ("Server", "Via", "X-Cache", "X-Amz-Cf-Id", "CF-RAY", "Akamai-GRN",
                  "X-Akamai-Request-ID", "Content-Type", "Set-Cookie"):
            if k in r.headers:
                print(f"  {k}: {r.headers[k][:200]}")
        print("  all headers:", dict(list(r.headers.items())[:20]))
        body = r.text[:800]
        print("  body head:", re.sub(r"\s+", " ", body))
        _save("block_signature.txt", f"{r.status_code}\n{dict(r.headers)}\n\n{r.text[:20000]}")
    except Exception as exc:
        print(f"FAIL: {exc}")


def probe_curl_cffi(goods_no: str):
    """TLS 핑거프린트 기반 차단인지 확인 — 크롬 TLS 로 위장한 요청."""
    print("\n===== [0.5] curl_cffi chrome-impersonated request =====")
    try:
        from curl_cffi import requests as cf_requests
    except ImportError:
        print("curl_cffi not installed — skipping")
        return
    for label, url, params in [
        ("bestlist", config.BEST_LIST_URL,
         {"dispCatNo": config.BEST_DISP_CAT_NO, "fltDispCatNo": "",
          "pageIdx": "1", "rowsPerPage": "8"}),
        ("detail", config.GOODS_DETAIL_URL, {"goodsNo": goods_no}),
    ]:
        try:
            r = cf_requests.get(url, params=params, impersonate="chrome",
                                headers={"Accept-Language": "ko-KR,ko;q=0.9"},
                                timeout=40)
            print(f"{label}: status={r.status_code}, {len(r.text)} bytes")
            _save(f"cffi_{label}.html", r.text)
            if label == "bestlist" and r.status_code == 200:
                from . import ranking as rk
                try:
                    items = rk.parse_ranking_html(r.text, "")
                    print(f"  parsed {len(items)} ranking items ✔")
                except Exception as exc:
                    print(f"  parse failed: {exc}")
            if label == "detail" and r.status_code == 200:
                print(f"  SSR summary: {reviews.parse_detail_ssr_summary(r.text)}")
        except Exception as exc:
            print(f"{label}: FAIL {exc}")


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
        browser = pw.chromium.launch(
            channel="chromium",  # headless shell 대신 정식 크로미움 (UA에 Headless 미표기)
            args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(user_agent=config.USER_AGENT, locale="ko-KR",
                                viewport={"width": 1440, "height": 900})

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
        nav = page.goto(f"{config.GOODS_DETAIL_URL}?goodsNo={goods_no}",
                        wait_until="domcontentloaded", timeout=90000)
        print(f"navigation status: {nav.status if nav else None}, title: {page.title()!r}")
        page.wait_for_timeout(5000)
        # 리뷰 영역까지 스크롤해 리뷰 API 호출 유도
        for _ in range(12):
            page.mouse.wheel(0, 1500)
            page.wait_for_timeout(700)
        page.wait_for_timeout(3000)
        page.screenshot(path=str(OUT / "pw_screenshot.png"), full_page=False)
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

    goods_no = args.goods_no
    steps = [
        ("block_signature", lambda: probe_block_signature()),
        ("curl_cffi", lambda: probe_curl_cffi(goods_no)),
        ("ranking", lambda: probe_ranking(Client())),
        ("detail", lambda: probe_detail(Client(), goods_no)),
        ("gdas", lambda: probe_gdas(Client(), goods_no)),
    ]
    if args.playwright:
        steps.append(("playwright", lambda: probe_playwright(goods_no)))
    for name, fn in steps:
        try:
            fn()
        except Exception as exc:
            print(f"[{name}] UNCAUGHT FAIL: {exc}")
    print("\nprobe done.")


if __name__ == "__main__":
    main()
