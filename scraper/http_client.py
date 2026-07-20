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
from urllib.parse import urlparse

import requests

from . import config

log = logging.getLogger(__name__)


class FetchError(Exception):
    """재시도를 모두 소진한 요청 실패."""


class Client:
    def __init__(self):
        self.session = requests.Session()
        # 실제 크롬 브라우저처럼 보이는 헤더 (Cloudflare 봇 감지 완화)
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                       "image/avif,image/webp,image/apng,*/*;q=0.8"),
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Connection": "keep-alive",
        })
        self._last_request_at: dict[str, float] = {}  # host -> monotonic
        self._consecutive_failures = 0
        self._cooldown_rounds = 0
        self.request_count = 0

    def _throttle(self, url: str):
        host = urlparse(url).netloc
        interval = config.HOST_INTERVALS.get(host, config.MIN_REQUEST_INTERVAL)
        last = self._last_request_at.get(host, 0.0)
        wait = (last + interval + random.uniform(0, config.REQUEST_JITTER)) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request_at[host] = time.monotonic()

    def get(self, url: str, params: dict | None = None, referer: str | None = None) -> requests.Response:
        return self.request("GET", url, params=params, referer=referer)

    def request(self, method: str, url: str, params: dict | None = None,
                json: dict | None = None, headers: dict | None = None,
                referer: str | None = None) -> requests.Response:
        hdr = dict(headers or {})
        if referer:
            hdr["Referer"] = referer
        last_exc: Exception | None = None
        for attempt in range(config.MAX_RETRIES):
            self._throttle(url)
            self.request_count += 1
            try:
                resp = self.session.request(method, url, params=params, json=json,
                                            headers=hdr, timeout=config.REQUEST_TIMEOUT)
                if resp.status_code == 429:
                    # rate limit: Retry-After 헤더가 있으면 그만큼, 없으면 길게 대기
                    ra = resp.headers.get("Retry-After", "")
                    wait = (float(ra) if ra.replace(".", "", 1).isdigit()
                            else config.RATE_LIMIT_BASE * (attempt + 1)) + random.uniform(0, 3)
                    log.warning("429 rate limited (%s/%s) %s — %.0fs 대기 후 재시도",
                                attempt + 1, config.MAX_RETRIES, url, wait)
                    last_exc = FetchError("HTTP 429")
                    time.sleep(wait)
                    continue
                if resp.status_code in (500, 502, 503, 504):
                    raise FetchError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                self._on_success()
                return resp
            except (requests.RequestException, FetchError) as exc:
                last_exc = exc
                delay = config.BACKOFF_BASE ** attempt + random.uniform(0, 1)
                log.warning("request failed (%s/%s) %s %s params=%s: %s — retry in %.1fs",
                            attempt + 1, config.MAX_RETRIES, method, url, params, exc, delay)
                time.sleep(delay)
        self._on_failure()
        raise FetchError(f"{method} {url} failed after {config.MAX_RETRIES} retries: {last_exc}")

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
