"""썸네일 수동 라벨링용 컨택트시트 생성.

저수준 특성(밝기·채도·구성 복잡도)은 '무엇이 그려져 있는가'를 담지 못한다.
기간 한정 소구, 증정 구성, 순위 클레임, 인물 등장 같은 마케팅 속성은 사람이 보고
분류해야 한다. 이 모듈은 라벨링 대상을 뽑아 번호가 붙은 시트 이미지로 만든다.

표본 설계: 특정 날짜의 카테고리 랭킹에서 순위 구간이 고르게 섞이도록 층화 추출한다.
(상위권만 보면 라벨과 순위의 관계를 볼 수 없다.)

사용:  python -m analysis.contact_sheet --date 2026-08-21 --n 160
출력:  analysis/output/sheets/sheet_XX.png + sheet_index.csv
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from .growth import OUT_DIR, load_rankings
from .image_features import IMG_DIR, url_to_filename

SHEET_DIR = os.path.join(OUT_DIR, "sheets")
COLS, ROWS = 5, 4          # 시트당 20장
CELL = 260
LABEL_H = 34


def _font(size=20):
    for p in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\gulim.ttc"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--n", type=int, default=160)
    args = ap.parse_args()

    rank = load_rankings()
    rank = rank[rank["카테고리"] != "전체"]
    day = pd.Timestamp(args.date) if args.date else rank["수집일자"].max()
    snap = rank[rank["수집일자"] == day].dropna(subset=["대표이미지URL"])
    snap = snap.drop_duplicates("상품번호").copy()
    snap["file"] = [url_to_filename(u) for u in snap["대표이미지URL"]]
    snap = snap[[os.path.exists(os.path.join(IMG_DIR, f)) for f in snap["file"]]]

    # 순위 구간 층화 추출
    bins = [(1, 20), (21, 40), (41, 60), (61, 80), (81, 100)]
    per = args.n // len(bins)
    rng = np.random.RandomState(414)
    picks = []
    for lo, hi in bins:
        s = snap[(snap["순위"] >= lo) & (snap["순위"] <= hi)]
        picks.append(s.sample(min(per, len(s)), random_state=rng.randint(1e6)))
    sel = pd.concat(picks).reset_index(drop=True)
    sel.insert(0, "no", range(1, len(sel) + 1))

    os.makedirs(SHEET_DIR, exist_ok=True)
    for f in os.listdir(SHEET_DIR):
        os.remove(os.path.join(SHEET_DIR, f))

    per_sheet = COLS * ROWS
    font = _font(21)
    n_sheets = (len(sel) + per_sheet - 1) // per_sheet
    for si in range(n_sheets):
        chunk = sel.iloc[si * per_sheet:(si + 1) * per_sheet]
        W = COLS * CELL
        H = ROWS * (CELL + LABEL_H)
        sheet = Image.new("RGB", (W, H), "white")
        drw = ImageDraw.Draw(sheet)
        for i, (_, r) in enumerate(chunk.iterrows()):
            cx, cy = (i % COLS) * CELL, (i // COLS) * (CELL + LABEL_H)
            try:
                im = Image.open(os.path.join(IMG_DIR, r["file"])).convert("RGB")
                im.thumbnail((CELL - 8, CELL - 8))
                sheet.paste(im, (cx + 4, cy + 4))
            except Exception:
                pass
            drw.rectangle([cx, cy, cx + CELL - 1, cy + CELL + LABEL_H - 1],
                          outline="#cccccc")
            drw.text((cx + 6, cy + CELL + 6), f"#{r['no']}  {int(r['순위'])}위",
                     fill="#111111", font=font)
        path = os.path.join(SHEET_DIR, f"sheet_{si + 1:02d}.png")
        sheet.save(path)
        print(f"  {os.path.basename(path)}  ({len(chunk)}장)")

    idx = sel[["no", "상품번호", "브랜드", "상품명", "순위", "카테고리", "file"]]
    idx.to_csv(os.path.join(SHEET_DIR, "sheet_index.csv"),
               index=False, encoding="utf-8-sig")
    print(f"스냅샷 {day.date()} · {len(sel)}장 · 시트 {n_sheets}장")
    print(f"저장: {SHEET_DIR}")


if __name__ == "__main__":
    main()
