"""썸네일 이미지 저수준 특성 추출 (PLAN.md §7-1).

data/images/ 의 아카이브(파일명 = md5(대표이미지URL)[:16] + 확장자)에서
상품번호로 조인 가능한 feature CSV를 만든다.

특성: 밝기, 채도, colorfulness(Hasler-Süsstrunk), 흰 배경 비율(테두리),
엣지 밀도(텍스트/구성 복잡도 proxy), 지배 색상(hue)

사용:  python -m analysis.image_features [--date YYYY-MM-DD]
출력:  analysis/output/image_features_<date>.csv
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import os
from urllib.parse import urlparse

import numpy as np
import pandas as pd
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
IMG_DIR = os.path.join(DATA_DIR, "images")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

ALLOWED_EXT = {"jpg", "jpeg", "png", "gif", "webp"}


def url_to_filename(url: str) -> str:
    """scraper/images.py 와 동일한 규칙."""
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
    ext = os.path.splitext(urlparse(url).path)[1].lstrip(".").lower()
    if ext not in ALLOWED_EXT:
        ext = "jpg"
    return f"{h}.{ext}"


def extract(path: str) -> dict:
    img = Image.open(path).convert("RGB")
    arr = np.asarray(img, dtype=np.float64)
    h, w, _ = arr.shape
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]

    gray = 0.299 * r + 0.587 * g + 0.114 * b
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0.0)

    # Hasler & Süsstrunk (2003) colorfulness
    rg = r - g
    yb = 0.5 * (r + g) - b
    colorfulness = (np.sqrt(rg.std() ** 2 + yb.std() ** 2)
                    + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))

    # 테두리 10% 픽셀 중 거의 흰색(>240) 비율 → 누끼/흰배경 여부 proxy
    m = max(2, int(0.1 * min(h, w)))
    border = np.concatenate([arr[:m].reshape(-1, 3), arr[-m:].reshape(-1, 3),
                             arr[:, :m].reshape(-1, 3), arr[:, -m:].reshape(-1, 3)])
    white_border = float((border.min(axis=1) > 240).mean())

    # 엣지 밀도: 그라디언트 크기 평균 (텍스트 오버레이·구성 복잡도 proxy)
    gy = np.abs(np.diff(gray, axis=0)).mean()
    gx = np.abs(np.diff(gray, axis=1)).mean()

    hsv = np.asarray(img.convert("HSV"), dtype=np.float64)
    strong = hsv[..., 1] > 60  # 채도 있는 픽셀만으로 지배 hue 계산
    dominant_hue = float(np.median(hsv[..., 0][strong])) if strong.any() else np.nan

    return {
        "width": w, "height": h,
        "brightness": float(gray.mean()),
        "saturation": float(sat.mean()),
        "colorfulness": float(colorfulness),
        "white_border_share": white_border,
        "edge_density": float((gx + gy) / 2),
        "dominant_hue": dominant_hue,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="랭킹 스냅샷 날짜 YYYY-MM-DD (기본: 최신)")
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(DATA_DIR, "*_ranking.csv")))
    if args.date:
        paths = [p for p in paths if args.date in os.path.basename(p)]
    if not paths:
        raise SystemExit("랭킹 CSV를 찾을 수 없습니다.")
    snap = pd.read_csv(paths[-1], encoding="utf-8-sig", dtype=str)
    date = os.path.basename(paths[-1]).split("_")[0]
    if "대표이미지URL" not in snap.columns:
        raise SystemExit(f"{date} 랭킹 파일엔 대표이미지URL 컬럼이 없습니다(07-21/22 스키마).")

    rows, missing = [], 0
    for _, row in snap.iterrows():
        url = row.get("대표이미지URL")
        if not isinstance(url, str) or not url:
            continue
        path = os.path.join(IMG_DIR, url_to_filename(url))
        if not os.path.exists(path):
            missing += 1
            continue
        feat = extract(path)
        feat["상품번호"] = row["상품번호"]
        feat["순위"] = int(row["순위"])
        rows.append(feat)

    df = pd.DataFrame(rows)
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"image_features_{date}.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"스냅샷 {date}: 이미지 특성 {len(df)}개 추출 (아카이브 누락 {missing}건)")
    print(f"저장: {out}")

    # 참고용: 순위와의 Spearman 상관
    for col in ["brightness", "saturation", "colorfulness",
                "white_border_share", "edge_density"]:
        rho = df["순위"].rank().corr(df[col].rank())  # tie-corrected Spearman
        print(f"  순위 vs {col:<20} rho={rho:+.3f}")


if __name__ == "__main__":
    main()
