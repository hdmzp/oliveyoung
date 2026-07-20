"""getGdasListJson.do (리뷰 JSON) 응답 구조를 뽑아낸다.

이 엔드포인트가 9KB 응답을 반환하는 것이 확인됨 → JSON 을 디코드해
최상위 키, 리뷰 목록 위치, 각 리뷰의 필드(별점·작성일·본문·체험단 뱃지 등)를
사람이 읽기 쉽게 출력한다. 이 출력으로 reviews.py 를 확정한다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import config
from .http_client import Client

OUT = Path("probe_out")


def describe(obj, indent=0, path="") -> None:
    pad = "  " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                kind = f"{type(v).__name__}[{len(v)}]" if isinstance(v, list) else "dict"
                print(f"{pad}{k}: {kind}")
                # 리스트/딕트는 첫 요소만 파고든다
                if isinstance(v, list) and v:
                    describe(v[0], indent + 1, f"{path}.{k}[0]")
                elif isinstance(v, dict):
                    describe(v, indent + 1, f"{path}.{k}")
            else:
                s = repr(v)
                if len(s) > 90:
                    s = s[:90] + "…"
                print(f"{pad}{k}: {s}")
    elif isinstance(obj, list):
        print(f"{pad}(list[{len(obj)}])")
        if obj:
            describe(obj[0], indent + 1, f"{path}[0]")
    else:
        print(f"{pad}{obj!r}")


def try_endpoint(client: Client, ep: str, params: dict, referer: str):
    url = f"{config.BASE}/store/goods/{ep}"
    try:
        resp = client.get(url, params=params, referer=referer)
    except Exception as exc:
        print(f"  요청 실패: {exc}")
        return None
    ct = resp.headers.get("Content-Type", "")
    print(f"  HTTP {resp.status_code}, {len(resp.text)}B, ct={ct}")
    fname = f"json_{ep}_{params.get('pageIdx','')}_{params.get('sortType') or params.get('gdasSort','')}.txt"
    (OUT / fname).write_text(resp.text, encoding="utf-8")
    try:
        data = json.loads(resp.text)
    except json.JSONDecodeError:
        print("  → JSON 아님 (원문 앞부분):")
        print("   ", resp.text[:300].replace("\n", " "))
        return None
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goods-no", default="A000000247086")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    client = Client()
    referer = f"{config.GOODS_DETAIL_URL}?goodsNo={args.goods_no}"
    # 세션 워밍
    try:
        client.get(config.GOODS_DETAIL_URL, params={"goodsNo": args.goods_no})
    except Exception:
        pass

    # 파라미터 후보들 — 리뷰가 실제로 담긴 응답을 찾는다
    candidates = [
        ("getGdasListJson.do", {"goodsNo": args.goods_no, "pageIdx": "1", "gdasSort": "01"}),
        ("getGdasListJson.do", {"goodsNo": args.goods_no, "pageIdx": "1", "sortType": "01"}),
        ("getGdasListJson.do", {"goodsNo": args.goods_no, "pageIdx": "1",
                                 "gdasSort": "01", "itemNo": "all_search", "keywordGdasSrchValue": ""}),
    ]

    for i, (ep, params) in enumerate(candidates, 1):
        print(f"\n===== 후보 {i}: {ep} params={params} =====")
        data = try_endpoint(client, ep, params, referer)
        if data is None:
            continue
        print("\n  --- JSON 구조 ---")
        describe(data, indent=1)
        # 리뷰 리스트로 보이는 키를 자동 탐색해 첫 리뷰 전체를 덤프
        review_list = _guess_review_list(data)
        if review_list:
            print(f"\n  --- 첫 리뷰 항목 전체 필드 ({len(review_list)}개 중 1번째) ---")
            print(json.dumps(review_list[0], ensure_ascii=False, indent=2)[:2500])
            break
    print("\nprobe_json done. 위 'JSON 구조'와 '첫 리뷰 항목' 출력을 공유해 주세요.")


def _guess_review_list(data):
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data
    if isinstance(data, dict):
        # 값이 dict 리스트인 키를 찾는다 (가장 긴 것)
        best = None
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                if best is None or len(v) > len(best):
                    best = v
        if best:
            return best
        # 한 단계 더 (예: {"data": {"gdasList": [...]}} )
        for v in data.values():
            if isinstance(v, dict):
                r = _guess_review_list(v)
                if r:
                    return r
    return None


if __name__ == "__main__":
    main()
