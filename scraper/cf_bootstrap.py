"""Cloudflare 브라우저 검증 쿠키(__cf_bm 등)를 실제 브라우저로 확보한다.

로컬(가정용 IP)에서는 브라우저로 사이트를 한 번 정상 방문하면 Cloudflare 가
검증 쿠키를 발급하고, 이 쿠키를 requests 세션에 주입하면 이후 빠른 HTTP 요청이
그대로 통과한다. 쿠키는 수십 분 후 만료되므로 403 재발 시 다시 부트스트랩한다.

Playwright 는 선택 의존성 — 설치돼 있지 않으면 사용하지 않는다.
"""
from __future__ import annotations

import logging

from . import config

log = logging.getLogger(__name__)

_CHALLENGE_MARKERS = ("잠시만", "moment", "challenge", "cf-please-wait")


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def fetch_cf_cookies(warm_url: str | None = None, timeout_s: int = 45) -> tuple[dict, str] | None:
    """브라우저로 접속해 (쿠키 dict, userAgent) 반환. 실패 시 None."""
    from playwright.sync_api import sync_playwright

    warm_url = warm_url or f"{config.BASE}/store/main/getBestList.do?dispCatNo={config.BEST_DISP_CAT_NO}"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=config.USER_AGENT, locale="ko-KR",
            timezone_id="Asia/Seoul", viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        try:
            page.goto(warm_url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
        except Exception as exc:
            log.warning("cf bootstrap navigation failed: %s", exc)
            browser.close()
            return None
        # 챌린지가 자동으로 풀릴 때까지 대기
        for _ in range(timeout_s):
            title = (page.title() or "").lower()
            if not any(m in title for m in _CHALLENGE_MARKERS):
                break
            page.wait_for_timeout(1000)
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        try:
            ua = page.evaluate("navigator.userAgent")
        except Exception:
            ua = config.USER_AGENT
        browser.close()
    if not cookies:
        return None
    log.info("cf bootstrap acquired %d cookies (cf_clearance=%s)",
             len(cookies), "yes" if "cf_clearance" in cookies else "no")
    return cookies, ua
