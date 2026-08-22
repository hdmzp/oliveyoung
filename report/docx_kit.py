"""보고서 docx 생성 도구 — 기존 보고서의 서식을 그대로 재현하는 빌더.

기존 문서에서 styles.xml·numbering.xml·theme 등 서식 골격을 그대로 가져오고,
본문(document.xml)만 새로 만든다. 덕분에 글꼴·표 스타일·목록 번호가 기존과 같다.
"""
from __future__ import annotations

import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field

FONT = ('<w:rFonts w:ascii="Malgun Gothic" w:eastAsia="Malgun Gothic" '
        'w:hAnsi="Malgun Gothic"/>')
HDR_FILL = "EFF2E6"
PAGE_W = 9026          # 본문 폭(dxa)


def esc(t: str) -> str:
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _run(text, *, size=20, bold=False, color=None, italic=False):
    rpr = [FONT]
    rpr.append("<w:b/><w:bCs/>" if bold else '<w:b w:val="false"/><w:bCs w:val="false"/>')
    if italic:
        rpr.append("<w:i/>")
    if color:
        rpr.append(f'<w:color w:val="{color}"/>')
    rpr.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    return (f'<w:r><w:rPr>{"".join(rpr)}</w:rPr>'
            f'<w:t xml:space="preserve">{esc(text)}</w:t></w:r>')


def para(text="", *, size=20, bold=False, color=None, after=180, line=300,
         align=None, before=0, runs=None):
    jc = f'<w:jc w:val="{align}"/>' if align else ""
    sp = f'<w:spacing w:after="{after}"' + (f' w:before="{before}"' if before else "")
    sp += f' w:line="{line}"/>' if line else "/>"
    inner = runs if runs is not None else _run(text, size=size, bold=bold, color=color)
    return f'<w:p><w:pPr>{sp}{jc}</w:pPr>{inner}</w:p>'


def heading(text, level=1):
    """제목 문단. outlineLvl 을 함께 넣어야 Word 탐색창과 pandoc 이 제목으로 인식한다."""
    size = {1: 26, 2: 23, 3: 21}[level]
    return (f'<w:p><w:pPr><w:pStyle w:val="Heading{level}"/>'
            f'<w:spacing w:after="140" w:before="{360 if level == 1 else 260}"/>'
            f'<w:outlineLvl w:val="{level - 1}"/></w:pPr>'
            f'{_run(text, size=size, bold=True)}</w:p>')


def caption(text):
    return para(text, size=17, color="777777", align="center", after=280, before=80,
                line=0)


def bullet(text, *, num_id=2, size=20):
    return (f'<w:p><w:pPr><w:pStyle w:val="ListParagraph"/><w:numPr>'
            f'<w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>'
            f'<w:spacing w:after="120" w:line="300"/></w:pPr>'
            f'{_run(text, size=size)}</w:p>')


def callout(text, *, color="8A5A00"):
    """옅은 테두리 한 줄 강조 박스."""
    return (f'<w:p><w:pPr><w:pBdr>'
            f'<w:top w:val="single" w:sz="4" w:space="6" w:color="D9CBA8"/>'
            f'<w:left w:val="single" w:sz="4" w:space="6" w:color="D9CBA8"/>'
            f'<w:bottom w:val="single" w:sz="4" w:space="6" w:color="D9CBA8"/>'
            f'<w:right w:val="single" w:sz="4" w:space="6" w:color="D9CBA8"/></w:pBdr>'
            f'<w:shd w:val="clear" w:fill="FBF7EC"/>'
            f'<w:spacing w:after="220" w:before="120" w:line="300"/></w:pPr>'
            f'{_run(text, size=20, color=color, bold=True)}</w:p>')


def step(label, text, *, color="1F6FB2"):
    """'분석 질문' 같은 단계 라벨 + 본문을 한 덩어리로 낸다."""
    lab = (f'<w:p><w:pPr><w:spacing w:after="40" w:before="140"/></w:pPr>'
           f'{_run(label, size=18, bold=True, color=color)}</w:p>')
    return lab + para(text, after=150)


def steps(*pairs):
    return "".join(step(l, t) for l, t in pairs)


_TC_MAR = ('<w:tcMar><w:top w:type="dxa" w:w="70"/><w:left w:type="dxa" w:w="100"/>'
           '<w:bottom w:type="dxa" w:w="70"/><w:right w:type="dxa" w:w="100"/></w:tcMar>')


def _cell(text, w, header, *, align=None, size=17):
    shd = f'<w:shd w:fill="{HDR_FILL}" w:val="clear"/>' if header else ""
    jc = f'<w:jc w:val="{align}"/>' if align else ""
    return (f'<w:tc><w:tcPr><w:tcW w:type="dxa" w:w="{w}"/>{shd}{_TC_MAR}</w:tcPr>'
            f'<w:p><w:pPr><w:spacing w:after="0" w:line="264" '
            f'w:lineRule="auto"/>{jc}</w:pPr>'
            f'{_run(text, size=size, bold=header)}</w:p></w:tc>')


def table(headers, rows, widths=None, *, aligns=None, size=17):
    n = len(headers)
    if widths is None:
        base = PAGE_W // n
        widths = [base] * n
        widths[0] += PAGE_W - base * n
    aligns = aligns or [None] * n
    if sum(widths) > PAGE_W:
        raise ValueError(f"열 너비 합계 {sum(widths)} 가 본문 폭 {PAGE_W} 를 넘습니다")
    borders = ("<w:tblBorders>"
               + "".join(f'<w:{s} w:val="single" w:color="C9C9C4" w:sz="4"/>'
                         for s in ("top", "left", "bottom", "right",
                                   "insideH", "insideV"))
               + "</w:tblBorders>")
    out = [f'<w:tbl><w:tblPr><w:tblW w:type="dxa" w:w="{sum(widths)}"/>{borders}'
           f'</w:tblPr><w:tblGrid>'
           + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>",
           "<w:tr><w:trPr><w:tblHeader/></w:trPr>"
           + "".join(_cell(h, w, True, align="center", size=size)
                     for h, w in zip(headers, widths)) + "</w:tr>"]
    for r in rows:
        out.append("<w:tr>" + "".join(
            _cell(c, w, False, align=a, size=size)
            for c, w, a in zip(r, widths, aligns)) + "</w:tr>")
    return "".join(out) + "</w:tbl>"


@dataclass
class Doc:
    blocks: list = field(default_factory=list)
    images: dict = field(default_factory=dict)   # rid -> 로컬 경로
    _next_rid: int = 100
    _next_did: int = 1000

    def add(self, *xml):
        self.blocks.extend(xml)

    def image(self, path, width_in=6.1, *, align="center", after=80):
        """인라인 이미지. 원본 비율을 유지한다."""
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        cx = int(width_in * 914400)
        cy = int(cx * h / w)
        rid = f"rIdX{self._next_rid}"
        self._next_rid += 1
        did = self._next_did
        self._next_did += 1
        self.images[rid] = path
        d = (f'<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
             f'<wp:extent cx="{cx}" cy="{cy}"/>'
             f'<wp:effectExtent t="0" r="0" b="0" l="0"/>'
             f'<wp:docPr id="{did}" name="fig{did}" descr="" title=""/>'
             f'<wp:cNvGraphicFramePr><a:graphicFrameLocks '
             f'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
             f'noChangeAspect="1"/></wp:cNvGraphicFramePr>'
             f'<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
             f'<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
             f'<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
             f'<pic:nvPicPr><pic:cNvPr id="0" name="" descr=""/><pic:cNvPicPr>'
             f'<a:picLocks noChangeAspect="1" noChangeArrowheads="1"/></pic:cNvPicPr>'
             f'</pic:nvPicPr><pic:blipFill><a:blip r:embed="{rid}" cstate="none"/>'
             f'<a:srcRect/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
             f'<pic:spPr bwMode="auto"><a:xfrm><a:off x="0" y="0"/>'
             f'<a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
             f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
             f'</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>')
        jc = f'<w:jc w:val="{align}"/>' if align else ""
        self.blocks.append(f'<w:p><w:pPr><w:spacing w:after="{after}"/>{jc}</w:pPr>'
                           f'<w:r>{d}</w:r></w:p>')

    def image_cell(self, path, w, width_in, title, desc):
        """표 셀 안의 이미지 + 설명 (예시 이미지 격자용)."""
        from PIL import Image
        with Image.open(path) as im:
            iw, ih = im.size
        cx = int(width_in * 914400)
        cy = int(cx * ih / iw)
        rid = f"rIdX{self._next_rid}"
        self._next_rid += 1
        did = self._next_did
        self._next_did += 1
        self.images[rid] = path
        d = (f'<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
             f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent t="0" r="0" b="0" l="0"/>'
             f'<wp:docPr id="{did}" name="ex{did}" descr="" title=""/>'
             f'<wp:cNvGraphicFramePr><a:graphicFrameLocks '
             f'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
             f'noChangeAspect="1"/></wp:cNvGraphicFramePr>'
             f'<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
             f'<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
             f'<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
             f'<pic:nvPicPr><pic:cNvPr id="0" name="" descr=""/><pic:cNvPicPr>'
             f'<a:picLocks noChangeAspect="1" noChangeArrowheads="1"/></pic:cNvPicPr>'
             f'</pic:nvPicPr><pic:blipFill><a:blip r:embed="{rid}" cstate="none"/>'
             f'<a:srcRect/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
             f'<pic:spPr bwMode="auto"><a:xfrm><a:off x="0" y="0"/>'
             f'<a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
             f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
             f'</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>')
        return (f'<w:tc><w:tcPr><w:tcW w:type="dxa" w:w="{w}"/>{_TC_MAR}</w:tcPr>'
                f'<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:after="60"/></w:pPr>'
                f'<w:r>{d}</w:r></w:p>'
                f'<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:after="40"/></w:pPr>'
                f'{_run(title, size=17, bold=True)}</w:p>'
                f'<w:p><w:pPr><w:spacing w:after="60"/></w:pPr>'
                f'{_run(desc, size=16, color="555555")}</w:p></w:tc>')

    def grid(self, cells, ncol=2):
        w = PAGE_W // ncol
        borders = ("<w:tblBorders>"
                   + "".join(f'<w:{s} w:val="single" w:color="E3E3E0" w:sz="4"/>'
                             for s in ("top", "left", "bottom", "right",
                                       "insideH", "insideV"))
                   + "</w:tblBorders>")
        out = [f'<w:tbl><w:tblPr><w:tblW w:type="dxa" w:w="{w * ncol}"/>{borders}'
               f'</w:tblPr><w:tblGrid>'
               + "".join(f'<w:gridCol w:w="{w}"/>' for _ in range(ncol)) + "</w:tblGrid>"]
        for i in range(0, len(cells), ncol):
            out.append("<w:tr>" + "".join(cells[i:i + ncol]) + "</w:tr>")
        self.blocks.append("".join(out) + "</w:tbl>")

    def cell_width(self, ncol=2):
        return PAGE_W // ncol


def build(doc: Doc, skeleton: str, out_path: str):
    """skeleton docx 의 서식을 재사용해 새 docx 를 만든다."""
    import tempfile
    tmp = tempfile.mkdtemp()
    with zipfile.ZipFile(skeleton) as z:
        z.extractall(tmp)
    # 기존 본문·미디어 제거
    media = os.path.join(tmp, "word", "media")
    shutil.rmtree(media, ignore_errors=True)
    os.makedirs(media, exist_ok=True)

    docp = os.path.join(tmp, "word", "document.xml")
    old = open(docp, encoding="utf-8").read()
    head = old[:old.index(">", old.index("<w:document")) + 1]
    sect = re.search(r"<w:sectPr\b.*?</w:sectPr>", old, re.S)
    sect_xml = sect.group(0) if sect else ""
    body = "".join(doc.blocks) + sect_xml
    open(docp, "w", encoding="utf-8").write(f"{head}<w:body>{body}</w:body></w:document>")

    # 관계 파일 재작성 (이미지만 교체)
    relp = os.path.join(tmp, "word", "_rels", "document.xml.rels")
    rel = open(relp, encoding="utf-8").read()
    rel = re.sub(r'<Relationship[^>]*?/relationships/image"[^>]*?/>', "", rel)
    add = []
    for rid, src in doc.images.items():
        fn = f"{rid}{os.path.splitext(src)[1].lower()}"
        shutil.copy(src, os.path.join(media, fn))
        add.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org'
                   f'/officeDocument/2006/relationships/image" Target="media/{fn}"/>')
    rel = rel.replace("</Relationships>", "".join(add) + "</Relationships>")
    open(relp, "w", encoding="utf-8").write(rel)

    # 대상 파일이 열려 있으면(Word 등) 덮어쓸 수 없으므로 대체 경로로 저장한다.
    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except PermissionError:
            base, ext = os.path.splitext(out_path)
            out_path = f"{base}_수정본{ext}"
            print(f"⚠ 원본이 열려 있어 대신 저장합니다: {os.path.basename(out_path)}")
            if os.path.exists(out_path):
                os.remove(out_path)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(tmp):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, tmp).replace("\\", "/"))
    shutil.rmtree(tmp, ignore_errors=True)
    return out_path
