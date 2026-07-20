"""공용 유틸: KST 시간, 데드라인, atomic 파일 저장, CSV append."""
from __future__ import annotations

import csv
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))


def kst_now() -> datetime:
    return datetime.now(tz=KST)


def kst_today() -> str:
    return kst_now().strftime("%Y-%m-%d")


def _retry_io(fn, attempts: int = 10, base: float = 0.3):
    """OneDrive/백신 등이 파일을 잠깐 잠글 때(PermissionError) 재시도."""
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(base * (i + 1))


class Deadline:
    """잡 시작 시점 기준 마감. 마감 도달 시 체크포인트 저장 후 정상 종료용."""

    def __init__(self, minutes: float | None):
        self._deadline = time.monotonic() + minutes * 60 if minutes else None

    @property
    def reached(self) -> bool:
        return self._deadline is not None and time.monotonic() >= self._deadline

    @property
    def remaining_minutes(self) -> float:
        if self._deadline is None:
            return float("inf")
        return max(0.0, (self._deadline - time.monotonic()) / 60)


def atomic_write_json(path: str | Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        _retry_io(lambda: os.replace(tmp, path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_json(path: str | Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_csv_atomic(path: str | Path, fieldnames: list[str], rows: list[dict]) -> None:
    """전체 덮어쓰기 CSV — 임시파일 작성 후 rename (중단돼도 파일 안 깨짐)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        _retry_io(lambda: os.replace(tmp, path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class CsvAppender:
    """수집 즉시 append 기록 — 중단돼도 그때까지의 데이터 보존.

    파일이 없으면 헤더부터 쓴다. utf-8-sig 로 저장해 엑셀에서도 바로 열림.
    """

    def __init__(self, path: str | Path, fieldnames: list[str]):
        self.path = Path(path)
        self.fieldnames = fieldnames
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._new_file = not self.path.exists() or self.path.stat().st_size == 0

    def append_rows(self, rows: list[dict]) -> None:
        if not rows:
            return

        def _write():
            mode = "w" if self._new_file else "a"
            with open(self.path, mode, encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames, extrasaction="ignore")
                if self._new_file:
                    writer.writeheader()
                    self._new_file = False
                writer.writerows(rows)
                f.flush()
                os.fsync(f.fileno())

        _retry_io(_write)
