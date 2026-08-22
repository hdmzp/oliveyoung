"""결과보고서 docx → 웹 리포트(eda.html) 생성.

docx 를 단일 원본으로 삼아 웹 페이지를 만든다. 보고서를 고치면
python -m report.build_report && python -m report.build_web
두 줄로 문서와 웹이 함께 갱신된다.

사용:  python -m report.build_web [--out <경로>]
"""
from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCX = os.path.join(ROOT, "올리브영_랭킹_분석_결과보고서.docx")

STEP_LABELS = ("분석 질문", "분석 방법", "예상한 결과", "실제 결과", "인사이트")

CSS = """
:root{color-scheme:light only;
 --page:#f7f7f4;--surface:#fff;--surface-2:#fbfbf8;--ink:#14150f;--ink-2:#4a4c42;
 --muted:#8a8c80;--rule:#d9dace;--accent:#5c7026;--accent-soft:#eef2e2;--accent-ink:#3f4e18;
 --warn-bg:#fbf7ec;--warn-bd:#d9cba8;--warn-ink:#7a5410;}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
 font-family:'Pretendard',-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif;
 font-size:15px;line-height:1.78;-webkit-font-smoothing:antialiased}
.wrap{max-width:940px;margin:0 auto;padding:40px 22px 90px}
.cover{border-bottom:2px solid var(--accent);padding-bottom:24px;margin-bottom:28px}
.eyebrow{color:var(--accent);font-weight:800;font-size:11.5px;letter-spacing:.14em;
 text-transform:uppercase;margin-bottom:10px}
h1.doc{font-size:29px;line-height:1.35;margin:0 0 10px;letter-spacing:-.02em;font-weight:800}
.sub{color:var(--ink-2);font-size:16px;margin:0 0 10px}
.meta{color:var(--muted);font-size:13px;margin:0}
h2{font-size:21px;margin:40px 0 12px;padding-top:14px;border-top:1px solid var(--rule);
 letter-spacing:-.01em;font-weight:800}
h3{font-size:17px;margin:26px 0 8px;font-weight:700;color:var(--accent-ink)}
p{margin:0 0 14px}
ul{margin:0 0 16px;padding-left:20px}
li{margin:0 0 7px}
.steplab{display:inline-block;font-size:11.5px;font-weight:800;letter-spacing:.08em;
 color:var(--accent);background:var(--accent-soft);border-radius:4px;
 padding:3px 9px;margin:16px 0 6px}
.callout{background:var(--warn-bg);border:1px solid var(--warn-bd);border-radius:8px;
 padding:13px 16px;margin:16px 0 20px;color:var(--warn-ink);font-weight:700}
figure{margin:18px 0 22px;text-align:center}
figure img{max-width:100%;height:auto;border:1px solid var(--rule);border-radius:8px;
 background:#fff}
figcaption{color:var(--muted);font-size:12.5px;margin-top:8px}
table{border-collapse:collapse;width:100%;margin:16px 0 8px;font-size:13.5px;
 background:var(--surface)}
th,td{border:1px solid var(--rule);padding:8px 10px;text-align:left;vertical-align:top}
th{background:var(--accent-soft);font-weight:700}
.tabwrap{overflow-x:auto}
.cap{color:var(--muted);font-size:12.5px;text-align:center;margin:2px 0 22px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:18px 0}
.grid2 .cell{border:1px solid var(--rule);border-radius:8px;padding:12px;background:var(--surface)}
.grid2 img{width:100%;height:auto;border-radius:6px}
.grid2 b{display:block;margin:8px 0 4px;font-size:13.5px}
.grid2 span{color:var(--ink-2);font-size:12.5px;line-height:1.6}
@media(max-width:700px){.grid2{grid-template-columns:1fr}}
.foot{margin-top:44px;padding-top:16px;border-top:1px solid var(--rule);
 color:var(--muted);font-size:12.5px}
"""


def convert(docx: str, workdir: str) -> str:
    subprocess.run(["pandoc", docx, "-t", "html", "--extract-media=.",
                    "-o", "frag.html"], cwd=workdir, check=True)
    return open(os.path.join(workdir, "frag.html"), encoding="utf-8").read()


def transform(frag: str) -> tuple[str, str, str, str]:
    """pandoc 조각을 웹 리포트 본문으로 다듬는다."""
    # 표지 3줄 분리
    paras = re.findall(r"<p>(.*?)</p>", frag, re.S)
    title = re.sub(r"<[^>]+>", "", paras[0]).strip()
    subtitle = re.sub(r"<[^>]+>", "", paras[1]).strip()
    meta = re.sub(r"<[^>]+>", "", paras[2]).strip()
    body = frag[frag.index("</p>", frag.index(paras[2])) + 4:]

    # 제목: <p><strong>…</strong></p> → h2/h3
    def head_sub(m):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
        if t in STEP_LABELS:
            return f'<div class="steplab">{html.escape(t)}</div>'
        if re.match(r"^\d+\.\d+\s", t):
            return f"<h3>{html.escape(t)}</h3>"
        if re.match(r"^(요약|\d+\.\s)", t):
            return f"<h2>{html.escape(t)}</h2>"
        return f'<p class="callout">{html.escape(t)}</p>'

    body = re.sub(r"<p><strong>(.*?)</strong></p>", head_sub, body, flags=re.S)

    # 그림 + 캡션
    body = re.sub(r'<p><img src="([^"]+)"[^>]*/?></p>\s*<p>(그림[^<]*)</p>',
                  lambda m: f'<figure><img src="assets/{os.path.basename(m.group(1))}" '
                            f'alt=""><figcaption>{html.escape(m.group(2).strip())}'
                            f'</figcaption></figure>', body, flags=re.S)
    body = re.sub(r'<p><img src="([^"]+)"[^>]*/?></p>',
                  lambda m: f'<figure><img src="assets/{os.path.basename(m.group(1))}" '
                            f'alt=""></figure>', body)
    # 남은 표/그림 캡션
    body = re.sub(r"<p>((?:표|그림)\s*\d[^<]*)</p>",
                  lambda m: f'<p class="cap">{html.escape(m.group(1).strip())}</p>', body)
    # 표 가로 스크롤 래핑
    body = re.sub(r"<table", '<div class="tabwrap"><table', body)
    body = re.sub(r"</table>", "</table></div>", body)
    return title, subtitle, meta, body


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="eda.html 출력 경로")
    args = ap.parse_args()

    out_html = os.path.abspath(args.out)
    site = os.path.dirname(out_html)
    assets = os.path.join(site, "assets")

    tmp = tempfile.mkdtemp()
    try:
        frag = convert(DOCX, tmp)
        title, subtitle, meta, body = transform(frag)
        os.makedirs(assets, exist_ok=True)
        src_media = os.path.join(tmp, "media")
        n = 0
        for f in sorted(os.listdir(src_media)):
            shutil.copy(os.path.join(src_media, f), os.path.join(assets, f))
            n += 1
        page = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)} — 결과보고서</title>
<meta name="description" content="{html.escape(subtitle)}">
<meta name="theme-color" content="#5c7026">
<link rel="icon" type="image/png" href="./favicon.png">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="cover">
    <div class="eyebrow">Olive Young Ranking Analysis</div>
    <h1 class="doc">{html.escape(title)}</h1>
    <p class="sub">{html.escape(subtitle)}</p>
    <p class="meta">{html.escape(meta)}</p>
  </header>
  {body}
  <p class="foot">이 페이지는 결과보고서 원본(docx)에서 자동 생성된다.
  수집 데이터가 갱신되면 분석·그림·보고서를 다시 만든 뒤 같은 절차로 갱신된다.</p>
</div>
</body>
</html>
"""
        open(out_html, "w", encoding="utf-8").write(page)
        print(f"생성: {out_html} ({len(page):,} bytes)")
        print(f"  이미지 {n}장 → {assets}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
