"""랭킹 썸네일 자동 분류 (Claude API).

수동 라벨링(analysis/labels/img_labels_2026-08-05.csv)과 동일한 기준으로
썸네일의 마케팅 속성 6종을 분류한다:
  model(인간 모델), character(캐릭터), period(기간 한정 소구),
  claim(1위/어워즈/인증 클레임), gift(증정/1+1/더블 구성) + 근거 텍스트

⚠️ 수동 실행 전용 — 일일 파이프라인에는 연결되어 있지 않다.
   Anthropic API(별도 유료, console.anthropic.com)를 사용하므로 명시적으로
   실행할 때만 과금된다. 현재 운영은 무과금(이미지 아카이브만 축적) 방식이며,
   라벨링은 분석 시점에 세션에서 수동으로 하거나 이 스크립트를 배치 실행한다.

사용:
  pip install anthropic                  # 별도 설치 (requirements.txt에 없음)
  export ANTHROPIC_API_KEY=sk-ant-...   # 또는 ant auth login
  python -m analysis.classify_thumbnails                # 최신 랭킹 날짜, 전체 카테고리
  python -m analysis.classify_thumbnails --date 2026-08-05 --validate

- 이미 분류된 상품은 건너뛰므로(재개 가능) 매일 실행해도 신규 썸네일만 과금된다.
- 비용: 상품당 이미지 ~210토큰 + 프롬프트, Opus 5 기준 100장에 수백 원 수준.
- --validate: 같은 날짜의 수동 라벨 CSV와 속성별 일치율을 출력한다.
"""
from __future__ import annotations

import argparse
import base64
import csv
import glob
import hashlib
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
IMG_DIR = DATA_DIR / "images"
LABEL_DIR = ROOT / "analysis" / "labels"

ALLOWED_EXT = {"jpg", "jpeg", "png", "gif", "webp"}
MEDIA_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
               "gif": "image/gif", "webp": "image/webp"}

PROMPT = """이 이미지는 올리브영 랭킹 페이지의 상품 썸네일이다. 아래 6개 속성을 판정하라.

- model: 인간(얼굴·입술·신체 일부 포함)이 등장하면 true. 단, 지름이 화면의 1/10도 안 되는
  작은 원형 인물 배지("OO PICK" 프로필 사진)만 있으면 false. 패키지에 인쇄된 인물 사진은 true.
- character: 만화/일러스트 캐릭터나 마스코트 인형이 눈에 띄게 등장하면 true
  (예: 미니언즈, 인형, 유령 일러스트). 'SURVIVAL BEAUTY' 같은 작은 인증 배지 속
  캐릭터는 false.
- period: 특가/행사 "기간"을 소구하는 텍스트가 있으면 true. 예: "8/4~8/5", "단 하루",
  "오늘의 특가", "7일 특가", "N시간 한정". "선착순"만 있는 경우는 false(기간이 아님).
  period_text에 해당 문구를 그대로 적는다(없으면 빈 문자열).
- claim: 성취/검증 클레임이 있으면 true. 예: "1위", "1등", "어워즈/AWARDS 수상",
  "N만 개 돌파", "품절대란", "SNS 화제템", 만족도 수치, 인증(더마테스트·비건 등).
  "올영픽", "단독기획", "NEW"는 false. claim_text에 대표 문구를 적는다.
- gift: 증정/덤 구성을 소구하면 true. 예: "1+1", "X2 더블기획", "+리필", "증정",
  "GIFT", "7+1", 구성품에 "+" 표기. 단순 대용량("100ml 대용량")만이면 false.

한국어 오버레이 텍스트를 주의 깊게 읽고 판정하라."""


def url_to_filename(url: str) -> str:
    """scraper/images.py 와 동일한 아카이브 파일명 규칙."""
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
    ext = os.path.splitext(urlparse(url).path)[1].lstrip(".").lower()
    if ext not in ALLOWED_EXT:
        ext = "jpg"
    return f"{h}.{ext}"


def load_snapshot(date: str | None):
    paths = sorted(glob.glob(str(DATA_DIR / "*_ranking.csv")))
    if date:
        paths = [p for p in paths if date in os.path.basename(p)]
    if not paths:
        raise SystemExit("랭킹 CSV가 없습니다.")
    path = paths[-1]
    day = os.path.basename(path).split("_")[0]
    with open(path, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r.get("카테고리") == "전체"]
    return day, rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="랭킹 날짜 YYYY-MM-DD (기본: 최신)")
    ap.add_argument("--model", default="claude-opus-5")
    ap.add_argument("--limit", type=int, help="분류할 최대 이미지 수 (테스트용)")
    ap.add_argument("--validate", action="store_true",
                    help="같은 날짜의 수동 라벨과 일치율 비교")
    args = ap.parse_args()

    import anthropic
    from pydantic import BaseModel

    class ThumbLabel(BaseModel):
        model: bool
        character: bool
        period: bool
        period_text: str
        claim: bool
        claim_text: str
        gift: bool

    client = anthropic.Anthropic()
    day, rows = load_snapshot(args.date)
    out_path = LABEL_DIR / f"img_labels_auto_{day}.csv"
    LABEL_DIR.mkdir(parents=True, exist_ok=True)

    done: set[str] = set()
    if out_path.exists():
        with open(out_path, encoding="utf-8-sig") as f:
            done = {r["상품번호"] for r in csv.DictReader(f)}

    fields = ["수집일자", "순위", "상품번호", "model", "character",
              "period", "period_text", "claim", "claim_text", "gift", "error"]
    write_header = not out_path.exists()
    n_ok = n_err = n_skip = 0

    with open(out_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            writer.writeheader()
        todo = [r for r in rows if r["상품번호"] not in done]
        if args.limit:
            todo = todo[: args.limit]
        for i, r in enumerate(todo, 1):
            url = r.get("대표이미지URL") or ""
            img = IMG_DIR / url_to_filename(url) if url else None
            if not img or not img.exists():
                n_skip += 1
                continue
            ext = img.suffix.lstrip(".").lower()
            row = {"수집일자": day, "순위": r["순위"], "상품번호": r["상품번호"],
                   "error": ""}
            try:
                resp = client.messages.parse(
                    model=args.model,
                    max_tokens=3000,
                    output_config={"effort": "low"},
                    output_format=ThumbLabel,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image",
                             "source": {"type": "base64",
                                        "media_type": MEDIA_TYPES.get(ext, "image/jpeg"),
                                        "data": base64.standard_b64encode(
                                            img.read_bytes()).decode()}},
                            {"type": "text", "text": PROMPT},
                        ],
                    }],
                )
                if resp.stop_reason == "refusal" or resp.parsed_output is None:
                    row["error"] = f"refusal:{getattr(resp.stop_details, 'category', '')}"
                    n_err += 1
                else:
                    lab = resp.parsed_output
                    row.update({
                        "model": int(lab.model), "character": int(lab.character),
                        "period": int(lab.period), "period_text": lab.period_text[:80],
                        "claim": int(lab.claim), "claim_text": lab.claim_text[:80],
                        "gift": int(lab.gift),
                    })
                    n_ok += 1
            except anthropic.APIError as exc:
                row["error"] = str(exc)[:200]
                n_err += 1
            writer.writerow(row)
            f.flush()
            if i % 10 == 0 or i == len(todo):
                print(f"진행 {i}/{len(todo)} (성공 {n_ok}, 오류 {n_err})")
            time.sleep(0.2)

    print(f"완료: {out_path} (신규 {n_ok}건, 오류 {n_err}건, "
          f"이미지 없음 {n_skip}건, 기존 {len(done)}건)")

    if args.validate:
        manual = LABEL_DIR / f"img_labels_{day}.csv"
        if not manual.exists():
            print(f"수동 라벨 없음: {manual}")
            return
        with open(manual, encoding="utf-8-sig") as f:
            man = {r["rank"]: r for r in csv.DictReader(f)}
        with open(out_path, encoding="utf-8-sig") as f:
            auto = {r["순위"]: r for r in csv.DictReader(f) if not r["error"]}
        common = set(man) & set(auto)
        pairs = [("model", "model"), ("character", "char"), ("period", "period"),
                 ("claim", "claim"), ("gift", "gift")]
        print(f"\n수동 라벨과 비교 (N={len(common)}):")
        for a_col, m_col in pairs:
            agree = sum(1 for k in common
                        if str(auto[k][a_col]) == str(man[k][m_col]))
            print(f"  {a_col:<10} 일치율 {agree / len(common):.0%}")


if __name__ == "__main__":
    main()
