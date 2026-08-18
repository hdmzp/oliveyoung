"""썸네일 저수준 특성 뱅크 — 이미지 파일 단위로 한 번만 추출해 캐시한다.

analysis/image_features.py 는 랭킹 스냅샷 한 날짜를 받아 그때마다 이미지를 다시
연다. 같은 이미지가 여러 날 랭킹에 등장하므로 패널 분석에서는 낭비가 크다.
이 모듈은 data/images/ 의 파일 하나당 한 번만 특성을 뽑아 CSV 로 쌓고, 이미 뽑은
파일은 건너뛴다(증분). 랭킹 CSV 의 대표이미지URL → 파일명 규칙으로 조인한다.

사용:  python -m analysis.image_bank [--limit N]
출력:  analysis/output/image_bank.csv  (파일명 기준, 증분 갱신)
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np
import pandas as pd

from .image_features import IMG_DIR, OUT_DIR, extract

BANK = os.path.join(OUT_DIR, "image_bank.csv")
ALLOWED = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="이번 실행에서 처리할 최대 장수")
    args = ap.parse_args()

    files = [f for f in sorted(os.listdir(IMG_DIR))
             if f.lower().endswith(ALLOWED)]
    done: set[str] = set()
    if os.path.exists(BANK):
        done = set(pd.read_csv(BANK, encoding="utf-8-sig")["file"].astype(str))
    todo = [f for f in files if f not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"이미지 {len(files):,}장 · 기추출 {len(done):,} · 이번 처리 {len(todo):,}")

    rows, bad, t0 = [], 0, time.time()
    for i, f in enumerate(todo, 1):
        try:
            feat = extract(os.path.join(IMG_DIR, f))
        except Exception:
            bad += 1
            continue
        feat["file"] = f
        rows.append(feat)
        if i % 500 == 0:
            print(f"  {i:,}/{len(todo):,}  ({time.time() - t0:.0f}s)")

    if rows:
        df = pd.DataFrame(rows)
        if os.path.exists(BANK):
            df = pd.concat([pd.read_csv(BANK, encoding="utf-8-sig"), df],
                           ignore_index=True)
        os.makedirs(OUT_DIR, exist_ok=True)
        df.to_csv(BANK, index=False, encoding="utf-8-sig")
    print(f"완료: 신규 {len(rows):,}장 · 실패 {bad}장 · {time.time() - t0:.0f}s")
    print(f"저장: {BANK}")


if __name__ == "__main__":
    main()
