"""Cloudflare 검증 쿠키(cf_clearance 등)를 설치된 브라우저로 확보한다.

requests 만으로는 Cloudflare 챌린지(403)를 못 넘는 환경에서, 실제 Edge/Chrome 를
잠깐 띄워 사이트를 정상 방문 → 검증 쿠키 + userAgent 를 받아 requests 세션에 주입한다.
cf_clearance 는 userAgent 에 묶이므로 쿠키와 UA 를 함께 가져와 일치시킨다.

Playwright 필요 (pip install playwright). 브라우저 다운로드는 불필요 —
설치된 Edge(msedge)/Chrome(chrome) 채널을 사용한다.
"""
from __future__ import annotations

import logging

from . import config

log = logging.getLogger(__name__)

_CHALLENGE = ("잠시만", "moment", "just a moment", "cf-please-wait", "checking")


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def fetch_cf_cookies(warm_url: str | None = None, timeout_s: int = 60):
    """설치된 브라우저로 접속해 (쿠키 리스트, userAgent) 반환. 실패 시 None."""
    from playwright.sync_api import sync_playwright

    warm_url = warm_url or (f"{config.BEST_LIST_URL}?dispCatNo={config.BEST_DISP_CAT_NO}")
    with sync_playwright() as pw:
        browser = None
        for channel in ("msedge", "chrome"):
            try:
                browser = pw.chromium.launch(
                    channel=channel, headless=False,
                    args=["--disable-blink-features=AutomationControlled"])
                log.info("cf bootstrap: %s 브라우저로 쿠키 확보 중...", channel)
                break
            except Exception as exc:
                log.warning("cf bootstrap: %s 실행 실패 (%s)", channel, str(exc)[:60])
        if browser is None:
            log.warning("cf bootstrap: Edge/Chrome 를 실행할 수 없습니다")
            return None

        ctx = browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul",
                                  viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        try:
            page.goto(warm_url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
            for _ in range(timeout_s):  # 챌린지가 풀릴 때까지 대기
                title = (page.title() or "").lower()
                if not any(m in title for m in _CHALLENGE):
                    break
                page.wait_for_timeout(1000)
            cookies = ctx.cookies()
            try:
                ua = page.evaluate("navigator.userAgent")
            except Exception:
                ua = config.USER_AGENT
        finally:
            browser.close()

    has_clearance = any(c.get("name") == "cf_clearance" for c in cookies)
    log.info("cf bootstrap: 쿠키 %d개 확보 (cf_clearance=%s)",
             len(cookies), "있음" if has_clearance else "없음")
    return cookies, ua
