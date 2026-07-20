"""장시간 실행을 견디는 HTTP 클라이언트.

- 세션 재사용 + 브라우저 UA
- 요청 간 최소 간격 + 지터 (정중한 속도 유지)
- 지수 백오프 재시도 (429/5xx/네트워크 오류)
- 연속 실패 시 쿨다운(장시간 휴식) 후 재개 — 일시적 차단 완화
"""
from __future__ import annotations

import logging
import random
import time

import requests

from . import config

log = logging.getLogger(__name__)


class FetchError(Exception):
    """재시도를 모두 소진한 요청 실패."""


class Client:
    def __init__(self, cf_bootstrap: bool = False):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        })
        self._last_request_at = 0.0
        self._consecutive_failures = 0
        self._cooldown_rounds = 0
        self.request_count = 0
        # Cloudflare 브라우저 검증 쿠키 부트스트랩 (로컬 실행용)
        self._cf_bootstrap = cf_bootstrap
        self._cf_bootstrapped = False
        if cf_bootstrap:
            self._try_cf_bootstrap()

    def _try_cf_bootstrap(self) -> bool:
        from . import cf_bootstrap
        if not cf_bootstrap.playwright_available():
            log.warning("cf bootstrap requested but Playwright not installed — "
                        "run: pip install playwright && python -m playwright install chromium")
            return False
        try:
            result = cf_bootstrap.fetch_cf_cookies()
        except Exception as exc:
            msg = str(exc)
            if "Executable doesn't exist" in msg or "playwright install" in msg:
                log.warning("Chromium 미설치 — 실행: python -m playwright install chromium")
            else:
                log.warning("cf bootstrap failed: %s", exc)
            return False
        if not result:
            log.warning("cf bootstrap returned no cookies")
            return False
        cookies, ua = result
        for name, value in cookies.items():
            self.session.cookies.set(name, value, domain=".oliveyoung.co.kr")
        if ua:
            self.session.headers["User-Agent"] = ua
        self._cf_bootstrapped = True
        return True

    def _throttle(self):
        wait = (self._last_request_at + config.MIN_REQUEST_INTERVAL
                + random.uniform(0, config.REQUEST_JITTER)) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def get(self, url: str, params: dict | None = None, referer: str | None = None) -> requests.Response:
        headers = {"Referer": referer} if referer else {}
        last_exc: Exception | None = None
        for attempt in range(config.MAX_RETRIES):
            self._throttle()
            self.request_count += 1
            try:
                resp = self.session.get(url, params=params, headers=headers,
                                        timeout=config.REQUEST_TIMEOUT)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise FetchError(f"HTTP {resp.status_code}")
                if resp.status_code == 403 and self._cf_bootstrap:
                    # Cloudflare 검증 쿠키 만료 추정 → 브라우저로 재확보 후 재시도
                    log.warning("403 with cf bootstrap enabled — refreshing cf cookies")
                    self._try_cf_bootstrap()
                    raise FetchError("HTTP 403 (cf challenge)")
                resp.raise_for_status()
                self._on_success()
                return resp
            except (requests.RequestException, FetchError) as exc:
                last_exc = exc
                delay = config.BACKOFF_BASE ** attempt + random.uniform(0, 1)
                log.warning("request failed (%s/%s) %s params=%s: %s — retry in %.1fs",
                            attempt + 1, config.MAX_RETRIES, url, params, exc, delay)
                time.sleep(delay)
        self._on_failure()
        raise FetchError(f"GET {url} failed after {config.MAX_RETRIES} retries: {last_exc}")

    def _on_success(self):
        self._consecutive_failures = 0
        self._cooldown_rounds = 0

    def _on_failure(self):
        self._consecutive_failures += 1
        if self._consecutive_failures >= config.CONSECUTIVE_FAIL_LIMIT:
            self._cooldown_rounds += 1
            if self._cooldown_rounds > config.MAX_COOLDOWN_ROUNDS:
                raise FetchError(
                    f"aborting: still failing after {config.MAX_COOLDOWN_ROUNDS} cooldown rounds")
            log.warning("%d consecutive failures — cooling down %ds (round %d/%d)",
                        self._consecutive_failures, config.COOLDOWN_SECONDS,
                        self._cooldown_rounds, config.MAX_COOLDOWN_ROUNDS)
            time.sleep(config.COOLDOWN_SECONDS)
            self._consecutive_failures = 0
