"""웹 리포트(index.html)를 그대로 DOCX 로 옮긴다.

보고서를 두 곳에서 따로 쓰면 반드시 어긋나므로, **index.html 을 원본으로 두고**
DOCX 는 거기서 생성한다. 웹 리포트를 고치면 이 스크립트만 다시 돌리면 된다.

차트는 SVG 를 브라우저가 그리므로, Playwright 로 각 차트 박스를 PNG 로 찍어
문서에 끼워 넣는다. 브라우저가 없으면 차트를 건너뛰고 본문만 만든다.

사용:  python -m report.web_to_docx [--out report_v6.docx]
"""
from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from report.docx_kit import Doc, build, caption, heading, para, table  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "index.html")
SKELETON = os.path.join(ROOT, "report_v5.docx")   # 서식(글꼴·표 스타일)만 재사용
PORT = 8971


# ---------------------------------------------------------------- HTML 파싱

class Block:
    def __init__(self, kind, **kw):
        self.kind = kind
        self.__dict__.update(kw)


TAG = re.compile(r"<[^>]+>")
SKIP_SEC = ("r513",)          # 썸네일 절은 별도 갱신 예정이라 제외


def text_of(fragment: str) -> str:
    """인라인 태그를 걷어내고 한 줄 텍스트로 만든다."""
    t = TAG.sub("", fragment)          # 인라인 태그 자리에 공백을 넣으면 '평균 하나 로' 처럼 벌어진다
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def parse_table(frag: str) -> tuple[list[str], list[list[str]]]:
    head: list[str] = []
    rows: list[list[str]] = []
    for tr in re.findall(r"<tr\b.*?</tr>", frag, re.S):
        ths = re.findall(r"<th\b[^>]*>(.*?)</th>", tr, re.S)
        tds = re.findall(r"<td\b[^>]*>(.*?)</td>", tr, re.S)
        if ths and not head:
            head = [text_of(x) for x in ths]
        elif tds:
            rows.append([text_of(x) for x in tds])
    return head, rows


def read_blocks(raw: str) -> list[Block]:
    """본문을 문서 순서대로 훑어 블록 목록을 만든다.

    HTMLParser 로 상태를 들고 다니면 <b>·<span> 같은 인라인 태그에서 문단이
    잘린다. 블록 요소만 정규식으로 순서대로 집어내는 편이 안전하다.
    """
    body = raw[raw.index("<main"):raw.index("</main>")]
    pat = re.compile(
        r"<h2\b[^>]*>(?P<h2>.*?)</h2>"
        r"|<h3\b(?P<h3a>[^>]*)>(?P<h3>.*?)</h3>"
        r"|<table\b.*?</table>"
        r"|<p\b[^>]*>(?P<p>.*?)</p>"
        r"|<li\b[^>]*>(?P<li>.*?)</li>"
        r"|<div class=\"fig-title\"[^>]*>(?P<ft>.*?)</div>"
        r"|<div class=\"fig-sub\"[^>]*>(?P<fs>.*?)</div>"
        r"|<div class=\"fig-note\"[^>]*>(?P<fn>.*?)</div>"
        r"|<span class=\"c-tag\"[^>]*>(?P<ct>.*?)</span>"
        r"|<div class=\"chart-box[^\"]*\" id=\"(?P<chart>[^\"]+)\""
        r"|<img[^>]*src=\"(?P<img>[^\"]+)\"",
        re.S)
    out: list[Block] = []
    skipping = False
    for m in pat.finditer(body):
        frag = m.group(0)
        if m.group("h3") is not None:
            skipping = any(f'id="{sec}"' in (m.group("h3a") or "") for sec in SKIP_SEC)
            if not skipping:
                out.append(Block("h3", text=text_of(m.group("h3"))))
            continue
        if m.group("h2") is not None:
            skipping = False
            out.append(Block("h2", text=text_of(m.group("h2"))))
            continue
        if skipping:
            continue
        if frag.startswith("<table"):
            head, rows = parse_table(frag)
            if rows:
                out.append(Block("table", head=head, rows=rows))
        elif m.group("p") is not None:
            t = text_of(m.group("p"))
            if t:
                out.append(Block("cap" if 'class="tbl-cap"' in frag else "p", text=t))
        elif m.group("li") is not None:
            t = text_of(m.group("li"))
            if t:
                out.append(Block("li", text=t))
        elif m.group("ft") is not None:
            out.append(Block("figtitle", text=text_of(m.group("ft"))))
        elif m.group("fs") is not None or m.group("fn") is not None:
            out.append(Block("note", text=text_of(m.group("fs") or m.group("fn"))))
        elif m.group("ct") is not None:
            out.append(Block("tag", text=text_of(m.group("ct"))))
        elif m.group("chart") is not None:
            out.append(Block("chart", cid=m.group("chart")))
        elif m.group("img") is not None:
            out.append(Block("image", src=m.group("img")))
    return out


# ---------------------------------------------------------------- 차트 캡처

def capture_charts(out_dir: str) -> dict[str, str]:
    """로컬 서버를 띄우고 차트 박스를 PNG 로 찍는다. 실패하면 빈 dict."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("⚠ Playwright 없음 — 차트 없이 생성합니다")
        return {}
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT),
                            "--directory", ROOT],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    shots: dict[str, str] = {}
    try:
        exe = "/opt/pw-browsers/chromium"
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=exe if os.path.exists(exe) else None)
            pg = b.new_page(viewport={"width": 1280, "height": 1000},
                            device_scale_factor=2)
            pg.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="networkidle")
            pg.wait_for_timeout(2000)
            for el in pg.query_selector_all(".chart-box[id]"):
                cid = el.get_attribute("id")
                try:
                    el.scroll_into_view_if_needed()
                    pg.wait_for_timeout(120)
                    path = os.path.join(out_dir, f"{cid}.png")
                    el.screenshot(path=path)
                    shots[cid] = path
                except Exception:
                    pass
            b.close()
    except Exception as e:
        print("⚠ 차트 캡처 실패:", e)
    finally:
        srv.terminate()
    return shots


# ---------------------------------------------------------------- 조립

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "report_v6.docx"))
    args = ap.parse_args()

    raw = open(SRC, encoding="utf-8").read()
    blocks = read_blocks(raw)

    tmp = tempfile.mkdtemp()
    shots = capture_charts(tmp)

    # 표지 — 웹 리포트의 제목·부제·메타를 그대로 쓴다
    title = re.search(r"<h1[^>]*>(.*?)</h1>", raw, re.S)
    meta = re.search(r'<div class="hero-meta">(.*?)</div>', raw, re.S)
    strip = lambda t: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip()

    d = Doc()
    A = d.add
    A(para("올리브영 판매 랭킹 결정요인 분석", size=34, bold=True, after=60, line=0))
    if title:
        A(para(strip(title.group(1)), size=22, color="555555", after=140, line=0))
    if meta:
        A(para(strip(meta.group(1)), size=18, color="777777", after=320, line=0))

    for b in blocks:
        if b.kind == "h2":
            A(heading(b.text, 1))
        elif b.kind == "h3":
            A(heading(b.text, 2))
        elif b.kind == "figtitle":
            A(para(b.text, size=19, bold=True, after=60))
        elif b.kind == "note":
            A(para(b.text, size=17, color="666666", after=140))
        elif b.kind == "tag":
            A(para(b.text, size=18, bold=True, color="1F6FB2", after=60))
        elif b.kind == "p":
            A(para(b.text))
        elif b.kind == "li":
            A(para("· " + b.text, size=20, after=100))
        elif b.kind == "cap":
            A(para(b.text, size=17, color="666666", after=200))
        elif b.kind == "table":
            A(table(b.head or [""] * len(b.rows[0]), b.rows))
        elif b.kind == "chart":
            path = shots.get(b.cid)
            if path and os.path.exists(path):
                d.image(path, width_in=6.1)   # image() 가 직접 블록을 추가한다
        elif b.kind == "image":
            path = os.path.join(ROOT, b.src.lstrip("./"))
            if os.path.exists(path):
                d.image(path, width_in=4.6)

    out = build(d, SKELETON, args.out)
    print(f"생성: {out}  ({os.path.getsize(out)/1e6:.1f}MB)")
    print(f"차트 {len(shots)}개 포함 · 블록 {len(blocks)}개")


if __name__ == "__main__":
    main()
