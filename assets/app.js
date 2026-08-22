/* ==========================================================
   올리브영 판매 랭킹 결정요인 분석 — 차트
   순수 SVG/JS, 외부 라이브러리 없음
   색: 딥 그린(기본) · 네이비(대비) · 코랄(강조 1점)
   ========================================================== */
(function () {
  "use strict";

  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const C = () => ({
    s1: css("--s1"), s2: css("--s2"), s3: css("--s3"),
    ink: css("--ink"), ink2: css("--ink-2"), muted: css("--muted"),
    grid: css("--grid"), axis: css("--axis"), surface: css("--surface"),
    neutral: css("--neutral-fill"), neutralInk: css("--neutral-ink"),
    seq: [css("--seq-0"), css("--seq-1"), css("--seq-2"), css("--seq-3"), css("--seq-4"), css("--seq-5")],
  });

  const NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs, parent) {
    const node = document.createElementNS(NS, tag);
    for (const k in attrs) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  }
  function txt(parent, x, y, str, attrs) {
    const t = el("text", Object.assign({ x, y }, attrs || {}), parent);
    t.textContent = str;
    return t;
  }
  const fmt = (n, d) => Number(n).toLocaleString("ko-KR", {
    maximumFractionDigits: d == null ? 1 : d, minimumFractionDigits: d == null ? 0 : d,
  });

  /* ---------- tooltip ---------- */
  const tip = document.getElementById("tip");
  function showTip(evt, title, rows) {
    tip.innerHTML = "";
    const t = document.createElement("div");
    t.className = "tp-t";
    t.textContent = title;
    tip.appendChild(t);
    (rows || []).forEach(([label, value, color]) => {
      const r = document.createElement("div");
      r.className = "tp-row";
      if (color) {
        const k = document.createElement("span");
        k.className = "k";
        k.style.background = color;
        r.appendChild(k);
      }
      const s = document.createElement("span");
      s.textContent = label;
      r.appendChild(s);
      if (value !== undefined && value !== null && value !== "") {
        const b = document.createElement("b");
        b.textContent = value;
        r.appendChild(b);
      }
      tip.appendChild(r);
    });
    tip.style.display = "block";
    moveTip(evt);
  }
  function moveTip(evt) {
    const pad = 14;
    let x = evt.clientX + pad, y = evt.clientY + pad;
    const r = tip.getBoundingClientRect();
    if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - pad;
    if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - pad;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  function hideTip() { tip.style.display = "none"; }
  function hover(node, title, rows) {
    node.style.cursor = "default";
    node.addEventListener("mouseenter", (e) => showTip(e, title, rows));
    node.addEventListener("mousemove", moveTip);
    node.addEventListener("mouseleave", hideTip);
  }

  /* 데이터 끝만 둥근 막대 — dir: "up" | "right" | "left" */
  function barPath(x, y, w, h, r, dir) {
    if (w <= 0 || h <= 0) return "";
    if (dir === "up") {
      r = Math.min(r, w / 2, h);
      return `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`;
    }
    if (dir === "left") {
      r = Math.min(r, h / 2, w);
      return `M${x + w},${y} L${x + r},${y} Q${x},${y} ${x},${y + r} L${x},${y + h - r} Q${x},${y + h} ${x + r},${y + h} L${x + w},${y + h} Z`;
    }
    r = Math.min(r, h / 2, w);
    return `M${x},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h} L${x},${y + h} Z`;
  }

  /* 배경 위에서 읽히는 글자색 (상대 휘도 기준) */
  function readable(bg) {
    const m = /^#?([0-9a-f]{6})$/i.exec((bg || "").trim());
    if (!m) return "#000";
    const n = parseInt(m[1], 16);
    const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    const L = 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
    return L > 0.22 ? "#0b1410" : "#ffffff";
  }

  function makeSvg(id, w, h) {
    const box = document.getElementById(id);
    if (!box) return null;
    box.innerHTML = "";
    return el("svg", { viewBox: `0 0 ${w} ${h}`, role: "img" }, box);
  }
  function legend(id, items) {
    const box = document.getElementById(id);
    if (!box) return;
    box.innerHTML = "";
    items.forEach(([label, color, shape]) => {
      const li = document.createElement("span");
      li.className = "li";
      const sw = document.createElement("span");
      sw.className = shape === "line" ? "ln" : "sw";
      sw.style.background = color;
      li.appendChild(sw);
      li.appendChild(document.createTextNode(label));
      box.appendChild(li);
    });
  }

  /* ==========================================================
     DATA — 모든 수치는 결과보고서(2026-08-22) 본문·도표 기준
     ========================================================== */

  /* 그림 1. 전체 TOP100 일별 신규 진입 수 (직전일 대비) */
  const churn = [
    ["08-04", 28], ["08-05", 34], ["08-06", 44], ["08-07", 36], ["08-08", 38],
    ["08-09", 42], ["08-10", 48], ["08-11", 35], ["08-12", 32], ["08-13", 34],
    ["08-14", 36], ["08-15", 30], ["08-16", 28], ["08-17", 36], ["08-18", 33],
    ["08-19", 35], ["08-20", 32], ["08-21", 32], ["08-22", 39],
  ];
  const churnMean = 35;

  /* 그림 2. 코호트 전이 행렬 — 행 기준 % */
  const cohortRows = ["1–10위", "11–25위", "26–50위", "51–75위", "76–100위"];
  const cohortCols = ["1–10위", "11–25위", "26–50위", "51–75위", "76–100위", "100위 밖"];
  const cohort = [
    [59, 19, 8, 4, 3, 8],
    [13, 42, 22, 7, 3, 13],
    [3, 14, 36, 18, 8, 21],
    [1, 3, 18, 27, 17, 34],
    [1, 2, 8, 16, 24, 50],
  ];

  /* 그림 3. 설명력 분해 (within R², %) */
  const variance = [
    ["리뷰 총량만", 6.0, "n"],
    ["리뷰 증가 속도만", 14.0, "s1"],
    ["두 변수 모두", 14.0, "s1"],
  ];

  /* 그림 4. 카테고리별 리뷰 증가 속도–순위 상관 (음수 = 빠를수록 상위) */
  const catCorr = [
    ["홈리빙/가전", -0.28, -0.48, 0.12], ["구강용품", -0.28, -0.43, -0.13],
    ["스킨케어", -0.29, -0.44, -0.17], ["헤어케어", -0.30, -0.50, -0.21],
    ["메이크업", -0.31, -0.51, -0.17], ["바디케어", -0.31, -0.48, -0.21],
    ["헬스/건강용품", -0.31, -0.40, -0.12], ["취미/팬시", -0.31, -0.43, -0.21],
    ["향수/디퓨저", -0.33, -0.53, -0.11], ["패션", -0.34, -0.59, -0.16],
    ["푸드", -0.34, -0.41, -0.26], ["더모 코스메틱", -0.35, -0.53, -0.05],
    ["마스크팩", -0.37, -0.51, -0.29], ["맨즈에딧", -0.39, -0.55, -0.22],
    ["건강식품", -0.41, -0.53, -0.25], ["뷰티소품", -0.44, -0.54, -0.34],
    ["선케어", -0.46, -0.62, -0.37], ["클렌징", -0.47, -0.63, -0.32],
    ["위생용품", -0.55, -0.69, -0.40], ["네일", -0.61, -0.73, -0.51],
  ];

  /* 그림 5. 상품 평균 별점 분포 (0.1점 구간 상품 수) */
  const ratingBins = [
    [0.0, 750], [4.1, 30], [4.2, 60], [4.3, 110], [4.4, 250],
    [4.5, 2400], [4.6, 5700], [4.7, 13100], [4.8, 9500],
  ];

  /* 그림 6. 표준화 영향력 (탄력성 절댓값) */
  const elasticity = [["리뷰 증가 속도 (판매량 대리지표)", 0.41, "s1"], ["실제 판매가격", 0.36, "s2"]];

  /* 표 7. 동일 상품 내 프로모션별 순위 변화율 (+ = 개선) */
  const promo = [
    ["쿠폰 배지", 10.9, 4.0], ["증정 배지", 9.9, 4.8],
    ["할인율 (1%p당)", 2.9, 9.3], ["세일 배지", -28.7, 3.6],
  ];

  /* 그림 8. 이벤트 스터디 — 평소 순위 대비 ln(순위) 편차 (음수 = 상위) */
  const eventDays = [-3, -2, -1, 0, 1, 2, 3];
  const eventSeries = {
    쿠폰: [0.150, 0.080, 0.085, -0.400, -0.100, -0.090, -0.045],
    세일: [-0.020, 0.175, 0.255, -0.085, -0.090, -0.065, -0.080],
  };

  /* 표 10. 교차지연 검정 — |t| (클러스터 보정) */
  const lagData = {
    "1일": { fwd: 0.4, rev: 23.8 },
    "3일": { fwd: 0.5, rev: 21.8 },
    "7일": { fwd: 2.9, rev: 18.7 },
  };

  /* 그림 11. 썸네일 시각 특성별 |t| — 판매 요인 통제 전 / 후 */
  const thumbSignal = [
    ["구성 복잡도", 8.3, 4.2], ["색 다양성", 3.9, 1.65],
    ["흰 배경 비율", 2.35, 1.7], ["채도", 1.7, 0.2], ["밝기", 0.1, 0.65],
  ];

  /* 표 12. 썸네일 마케팅 소구 속성 (160장 수기 분류) */
  const thumbAttr = [
    ["순위 · 수상 클레임", 61, 38.1], ["증정 · 기획 구성", 53, 33.1],
    ["인물 모델 등장", 43, 26.9], ["기간 한정 소구", 15, 9.4],
  ];

  /* ==========================================================
     CHARTS
     ========================================================== */

  /* --- 그림 1. 일별 신규 진입 --- */
  function drawChurn() {
    const col = C(), W = 980, H = 320;
    const svg = makeSvg("chChurn", W, H);
    if (!svg) return;
    const L = 46, R = 16, T = 22, B = 52;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const maxY = 55;
    const yS = (v) => y1 - (v / maxY) * (y1 - y0);

    [0, 10, 20, 30, 40, 50].forEach((v) => {
      const y = yS(v);
      el("line", { x1: x0, y1: y, x2: x1, y2: y, stroke: col.grid, "stroke-width": 1 }, svg);
      txt(svg, x0 - 9, y + 4, String(v), { "text-anchor": "end", "font-size": 11, fill: col.muted });
    });

    const n = churn.length, gap = 2;
    const step = (x1 - x0) / n, bw = step - 6;
    churn.forEach(([d, v], i) => {
      const isMax = v === 48;
      const x = x0 + i * step + gap;
      const y = yS(v);
      const p = el("path", {
        d: barPath(x, y, bw - gap, y1 - y, 4, "up"),
        fill: isMax ? col.s3 : col.s1,
      }, svg);
      hover(p, `2026-${d}`, [["신규 진입", `${v}개`, isMax ? col.s3 : col.s1],
                             ["평균 대비", `${v - churnMean > 0 ? "+" : ""}${v - churnMean}개`]]);
      if (i % 2 === 0) {
        txt(svg, x + (bw - gap) / 2, y1 + 18, d, {
          "text-anchor": "middle", "font-size": 10.5, fill: col.muted,
        });
      }
    });

    const ym = yS(churnMean);
    el("line", { x1: x0, y1: ym, x2: x1, y2: ym, stroke: col.ink2, "stroke-width": 1.5, "stroke-dasharray": "5 4", opacity: .7 }, svg);
    txt(svg, x0 + 6, ym - 8, `일평균 ${churnMean}개`, { "font-size": 11.5, fill: col.ink2, "font-weight": 700 });

    const xMax = x0 + 6 * step + (bw) / 2;
    txt(svg, xMax, yS(48) - 12, "최다 48개", { "text-anchor": "middle", "font-size": 12, fill: col.s3, "font-weight": 800 });
    txt(svg, x0 - 9, y0 - 6, "개", { "text-anchor": "end", "font-size": 10.5, fill: col.muted });
    txt(svg, (x0 + x1) / 2, H - 8, "수집일 (2026년) · 직전 수집일 대비 신규 진입 상품 수", {
      "text-anchor": "middle", "font-size": 11.5, fill: col.muted,
    });
  }

  /* --- 그림 2. 코호트 전이 히트맵 --- */
  function drawCohort() {
    const col = C(), W = 980, H = 400;
    const svg = makeSvg("chCohort", W, H);
    if (!svg) return;
    const L = 100, R = 78, T = 46, B = 54;
    const cw = (W - L - R) / cohortCols.length;
    const ch = (H - T - B) / cohortRows.length;

    const ramp = (v) => {
      const steps = [[0, 0], [8, 1], [18, 2], [30, 3], [45, 4], [60, 5]];
      let idx = 0;
      for (const [th, i] of steps) if (v >= th) idx = i;
      return col.seq[idx];
    };

    cohortCols.forEach((c, j) => {
      txt(svg, L + j * cw + cw / 2, T - 14, c, { "text-anchor": "middle", "font-size": 11.5, fill: col.ink2, "font-weight": 650 });
    });
    cohortRows.forEach((r, i) => {
      txt(svg, L - 12, T + i * ch + ch / 2 + 4, r, { "text-anchor": "end", "font-size": 11.5, fill: col.ink2, "font-weight": 650 });
    });

    cohort.forEach((row, i) => row.forEach((v, j) => {
      const x = L + j * cw, y = T + i * ch;
      const fillCol = ramp(v);
      const key = (i === 0 && j === 0) || (i === 4 && j === 5);
      const cell = el("rect", {
        x: x + 1, y: y + 1, width: cw - 2, height: ch - 2, rx: 3,
        fill: fillCol,
        stroke: key ? col.s3 : "transparent", "stroke-width": key ? 2 : 0,
      }, svg);
      txt(svg, x + cw / 2, y + ch / 2 + 4, String(v), {
        "text-anchor": "middle", "font-size": v >= 30 ? 13 : 12,
        "font-weight": v >= 20 ? 800 : 600,
        fill: v >= 20 ? readable(fillCol) : col.ink,
      });
      hover(cell, `${cohortRows[i]} → ${cohortCols[j]}`, [
        ["전이 비율", `${v}%`, fillCol],
        ["읽는 법", i === j ? "같은 구간 유지" : (j === 5 ? "TOP100 이탈" : (j > i ? "하락" : "상승"))],
      ]);
    }));

    /* 범례 — 단일 색상 순차 램프 */
    const lx = W - R + 16, lyTop = T, lh = (H - T - B);
    col.seq.forEach((c, i) => {
      el("rect", { x: lx, y: lyTop + lh - (i + 1) * (lh / 6), width: 14, height: lh / 6, fill: c }, svg);
    });
    [["0%", 0], ["30%", 3], ["60%+", 6]].forEach(([lab, i]) => {
      txt(svg, lx + 19, lyTop + lh - i * (lh / 6) + 4, lab, { "font-size": 10.5, fill: col.muted });
    });

    txt(svg, L + (W - L - R) / 2, H - 10, "다음 날 순위 구간", { "text-anchor": "middle", "font-size": 12, fill: col.ink2, "font-weight": 650 });
    txt(svg, 30, T + (H - T - B) / 2, "당일 순위 구간", {
      "font-size": 12, fill: col.ink2, "font-weight": 650, "text-anchor": "middle",
      transform: `rotate(-90 30 ${T + (H - T - B) / 2})`,
    });
  }

  /* --- 그림 3. 설명력 분해 --- */
  function drawVariance() {
    const col = C(), W = 980, H = 230;
    const svg = makeSvg("chVariance", W, H);
    if (!svg) return;
    const L = 150, R = 210, T = 18, B = 44;
    const x0 = L, x1 = W - R, maxX = 20;
    const xS = (v) => x0 + (v / maxX) * (x1 - x0);
    const rowH = (H - T - B) / variance.length;

    [0, 5, 10, 15, 20].forEach((v) => {
      const x = xS(v);
      el("line", { x1: x, y1: T, x2: x, y2: H - B, stroke: col.grid, "stroke-width": 1 }, svg);
      txt(svg, x, H - B + 17, `${v}%`, { "text-anchor": "middle", "font-size": 11, fill: col.muted });
    });

    variance.forEach(([lab, v, kind], i) => {
      const bh = rowH - 20, y = T + i * rowH + 10;
      const fill = kind === "s1" ? col.s1 : col.neutral;
      const p = el("path", { d: barPath(x0, y, xS(v) - x0, bh, 4, "right"), fill }, svg);
      hover(p, lab, [["설명력 (within R²)", `${v.toFixed(1)}%`, fill]]);
      txt(svg, x0 - 12, y + bh / 2 + 4, lab, { "text-anchor": "end", "font-size": 12.5, fill: col.ink, "font-weight": 650 });
      txt(svg, xS(v) + 9, y + bh / 2 + 4, `${v.toFixed(1)}%`, { "font-size": 12.5, fill: col.ink2, "font-weight": 700 });
    });

    const yLast = T + 2 * rowH + 10 + (rowH - 20) / 2;
    txt(svg, xS(14) + 62, yLast - 5, "총량을 추가해도", { "font-size": 12, fill: col.s3, "font-weight": 750 });
    txt(svg, xS(14) + 62, yLast + 11, "설명력이 늘지 않는다", { "font-size": 12, fill: col.s3, "font-weight": 750 });
    txt(svg, (x0 + x1) / 2, H - 8, "같은 카테고리 · 같은 날 안에서 순위 차이를 설명하는 정도 (within R²)", {
      "text-anchor": "middle", "font-size": 11.5, fill: col.muted,
    });
  }

  /* --- 그림 4. 카테고리별 상관 --- */
  function drawCategory() {
    const col = C(), W = 980, H = 470;
    const svg = makeSvg("chCategory", W, H);
    if (!svg) return;
    const L = 120, R = 30, T = 14, B = 46;
    const x0 = L, x1 = W - R;
    const lo = -0.8, hi = 0.2;
    const xS = (v) => x0 + ((v - lo) / (hi - lo)) * (x1 - x0);
    const rowH = (H - T - B) / catCorr.length;

    [-0.8, -0.6, -0.4, -0.2, 0.0, 0.2].forEach((v) => {
      const x = xS(v);
      el("line", { x1: x, y1: T, x2: x, y2: H - B, stroke: col.grid, "stroke-width": 1 }, svg);
      txt(svg, x, H - B + 17, v.toFixed(1), { "text-anchor": "middle", "font-size": 11, fill: col.muted });
    });
    const xz = xS(0);
    el("line", { x1: xz, y1: T, x2: xz, y2: H - B, stroke: col.s3, "stroke-width": 1.6, "stroke-dasharray": "5 4" }, svg);
    txt(svg, xz + 7, H - B - 6, "무관계선 (0)", { "font-size": 11, fill: col.s3, "font-weight": 700 });

    catCorr.forEach(([name, r, lo_, hi_], i) => {
      const y = T + i * rowH + rowH / 2;
      el("line", { x1: xS(lo_), y1: y, x2: xS(hi_), y2: y, stroke: col.axis, "stroke-width": 2, "stroke-linecap": "round" }, svg);
      const dot = el("circle", { cx: xS(r), cy: y, r: 5, fill: col.s1, stroke: col.surface, "stroke-width": 2 }, svg);
      hover(dot, name, [
        ["상관 (ρ)", r.toFixed(2), col.s1],
        ["신뢰구간", `${lo_.toFixed(2)} ~ ${hi_.toFixed(2)}`],
      ]);
      txt(svg, L - 12, y + 4, name, { "text-anchor": "end", "font-size": 11.5, fill: col.ink2 });
    });
    txt(svg, (x0 + x1) / 2, H - 8, "리뷰 증가 속도와 순위의 상관 (음수 = 빠를수록 상위권)", {
      "text-anchor": "middle", "font-size": 11.5, fill: col.muted,
    });
  }

  /* --- 그림 5. 별점 분포 --- */
  function drawRating() {
    const col = C(), W = 980, H = 300;
    const svg = makeSvg("chRating", W, H);
    if (!svg) return;
    const L = 58, R = 150, T = 20, B = 48;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const maxY = 14000;
    const xS = (v) => x0 + (v / 5.2) * (x1 - x0);
    const yS = (v) => y1 - (v / maxY) * (y1 - y0);
    const bw = xS(0.1) - xS(0);

    [0, 4000, 8000, 12000].forEach((v) => {
      const y = yS(v);
      el("line", { x1: x0, y1: y, x2: x1, y2: y, stroke: col.grid, "stroke-width": 1 }, svg);
      txt(svg, x0 - 9, y + 4, fmt(v, 0), { "text-anchor": "end", "font-size": 11, fill: col.muted });
    });
    [0, 1, 2, 3, 4, 5].forEach((v) => {
      txt(svg, xS(v), y1 + 18, String(v), { "text-anchor": "middle", "font-size": 11, fill: col.muted });
    });

    ratingBins.forEach(([b, v]) => {
      const y = yS(v);
      const p = el("path", { d: barPath(xS(b) + 1, y, bw - 2, y1 - y, 3, "up"), fill: col.s1 }, svg);
      hover(p, b === 0 ? "별점 미집계 (리뷰 없음)" : `별점 ${b.toFixed(1)} ~ ${(b + 0.1).toFixed(1)}점`,
        [["상품 수", `${fmt(v, 0)}개`, col.s1]]);
    });

    const xm = xS(4.8);
    el("line", { x1: xm, y1: y0 - 6, x2: xm, y2: y1, stroke: col.s3, "stroke-width": 2 }, svg);
    txt(svg, xm + 8, y0 + 12, "중위 4.80점", { "font-size": 12.5, fill: col.s3, "font-weight": 800 });
    txt(svg, xm + 8, y0 + 30, "거의 모든 상품이", { "font-size": 11.5, fill: col.muted });
    txt(svg, xm + 8, y0 + 45, "만점 부근에 몰려 있다", { "font-size": 11.5, fill: col.muted });
    txt(svg, (x0 + x1) / 2, H - 8, "상품 평균 별점 (점)", { "text-anchor": "middle", "font-size": 11.5, fill: col.muted });
    txt(svg, x0 - 9, y0 - 6, "상품 수", { "text-anchor": "end", "font-size": 10.5, fill: col.muted });
  }

  /* --- 그림 6. 탄력성 비교 --- */
  function drawElasticity() {
    const col = C(), W = 980, H = 210;
    const svg = makeSvg("chElasticity", W, H);
    if (!svg) return;
    const L = 210, R = 180, T = 16, B = 44;
    const x0 = L, x1 = W - R, maxX = 0.5;
    const xS = (v) => x0 + (v / maxX) * (x1 - x0);
    const rowH = (H - T - B) / elasticity.length;

    [0, 0.1, 0.2, 0.3, 0.4, 0.5].forEach((v) => {
      const x = xS(v);
      el("line", { x1: x, y1: T, x2: x, y2: H - B, stroke: col.grid, "stroke-width": 1 }, svg);
      txt(svg, x, H - B + 17, v.toFixed(1), { "text-anchor": "middle", "font-size": 11, fill: col.muted });
    });

    elasticity.forEach(([lab, v, kind], i) => {
      const bh = rowH - 22, y = T + i * rowH + 11;
      const fill = kind === "s1" ? col.s1 : col.s2;
      const p = el("path", { d: barPath(x0, y, xS(v) - x0, bh, 4, "right"), fill }, svg);
      hover(p, lab, [["표준화 영향력", v.toFixed(2), fill]]);
      const parts = lab.split(" (");
      txt(svg, x0 - 12, y + bh / 2 + (parts[1] ? -2 : 4), parts[0], { "text-anchor": "end", "font-size": 12.5, fill: col.ink, "font-weight": 650 });
      if (parts[1]) txt(svg, x0 - 12, y + bh / 2 + 14, `(${parts[1]}`, { "text-anchor": "end", "font-size": 11, fill: col.muted });
      txt(svg, xS(v) + 9, y + bh / 2 + 4, v.toFixed(2), { "font-size": 13, fill: col.ink, "font-weight": 750 });
    });

    txt(svg, x1 + 46, T + 34, "영향력 비율 0.87", { "font-size": 13, fill: col.s3, "font-weight": 800 });
    txt(svg, x1 + 46, T + 52, "→ 가격과 판매량이", { "font-size": 11.5, fill: col.muted });
    txt(svg, x1 + 46, T + 67, "거의 대등하다", { "font-size": 11.5, fill: col.muted });
    txt(svg, (x0 + x1) / 2, H - 8, "순위에 미치는 영향력의 크기 (탄력성 절댓값)", {
      "text-anchor": "middle", "font-size": 11.5, fill: col.muted,
    });
  }

  /* --- 표 7. 프로모션별 순위 변화율 (발산형) --- */
  function drawPromo() {
    const col = C(), W = 980, H = 280;
    const svg = makeSvg("chPromo", W, H);
    if (!svg) return;
    const L = 150, R = 60, T = 30, B = 48;
    const x0 = L, x1 = W - R;
    const lo = -32, hi = 16;
    const xS = (v) => x0 + ((v - lo) / (hi - lo)) * (x1 - x0);
    const rowH = (H - T - B) / promo.length;

    [-30, -20, -10, 0, 10].forEach((v) => {
      const x = xS(v);
      el("line", { x1: x, y1: T, x2: x, y2: H - B, stroke: v === 0 ? col.axis : col.grid, "stroke-width": v === 0 ? 1.5 : 1 }, svg);
      txt(svg, x, H - B + 17, v === 0 ? "0" : `${Math.abs(v)}%`, { "text-anchor": "middle", "font-size": 11, fill: col.muted });
    });
    txt(svg, xS(8), T - 12, "순위 개선 →", { "text-anchor": "middle", "font-size": 11.5, fill: col.s1, "font-weight": 750 });
    txt(svg, xS(-20), T - 12, "← 순위 악화", { "text-anchor": "middle", "font-size": 11.5, fill: col.s3, "font-weight": 750 });

    promo.forEach(([lab, v, t], i) => {
      const bh = rowH - 20, y = T + i * rowH + 10;
      const good = v > 0;
      const fill = good ? col.s1 : col.s3;
      const w = Math.abs(xS(v) - xS(0));
      const p = el("path", {
        d: good ? barPath(xS(0), y, w, bh, 4, "right") : barPath(xS(v), y, w, bh, 4, "left"),
        fill,
      }, svg);
      hover(p, lab, [
        ["순위 변화", `${Math.abs(v).toFixed(1)}% ${good ? "개선" : "악화"}`, fill],
        ["신호 강도 |t|", t.toFixed(1)],
        ["판정", "|t| > 2 — 유의"],
      ]);
      txt(svg, x0 - 12, y + bh / 2 + 4, lab, { "text-anchor": "end", "font-size": 12.5, fill: col.ink, "font-weight": 650 });
      txt(svg, good ? xS(v) + 9 : xS(v) + 10, y + bh / 2 + 4, `${Math.abs(v).toFixed(1)}%`, {
        "text-anchor": "start", "font-size": 12.5,
        fill: good ? col.ink : "#fff", "font-weight": 750,
      });
    });
    txt(svg, (x0 + x1) / 2, H - 8, "동일 상품 내 배지 부착일과 미부착일의 순위 변화율 (개체 고정효과)", {
      "text-anchor": "middle", "font-size": 11.5, fill: col.muted,
    });
  }

  /* --- 그림 8. 이벤트 스터디 --- */
  function drawEvent() {
    const col = C(), W = 980, H = 340;
    const svg = makeSvg("chEvent", W, H);
    if (!svg) return;
    const L = 62, R = 156, T = 24, B = 50;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const lo = -0.45, hi = 0.30;
    const xS = (d) => x0 + ((d + 3) / 6) * (x1 - x0);
    const yS = (v) => y0 + ((v - lo) / (hi - lo)) * (y1 - y0); /* 음수가 위 = 상위 */

    [-0.4, -0.3, -0.2, -0.1, 0, 0.1, 0.2, 0.3].forEach((v) => {
      const y = yS(v);
      el("line", { x1: x0, y1: y, x2: x1, y2: y, stroke: v === 0 ? col.axis : col.grid, "stroke-width": v === 0 ? 1.5 : 1 }, svg);
      txt(svg, x0 - 9, y + 4, v.toFixed(1), { "text-anchor": "end", "font-size": 11, fill: col.muted });
    });
    eventDays.forEach((d) => {
      txt(svg, xS(d), y1 + 19, d === 0 ? "D-Day" : (d > 0 ? `+${d}` : `${d}`), {
        "text-anchor": "middle", "font-size": 11.5, fill: d === 0 ? col.ink2 : col.muted, "font-weight": d === 0 ? 750 : 400,
      });
    });
    el("line", { x1: xS(0), y1: y0, x2: xS(0), y2: y1, stroke: col.axis, "stroke-width": 1.5, "stroke-dasharray": "5 4" }, svg);
    txt(svg, x0 + 4, y0 + 12, "↑ 평소보다 상위", { "font-size": 11, fill: col.muted });

    const series = [["쿠폰", col.s1, "쿠폰 부착 (705건)"], ["세일", col.s3, "세일 부착 (124건)"]];
    series.forEach(([key, color, label]) => {
      const vals = eventSeries[key];
      const d = vals.map((v, i) => `${i === 0 ? "M" : "L"}${xS(eventDays[i])},${yS(v)}`).join(" ");
      el("path", { d, fill: "none", stroke: color, "stroke-width": 2.4, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
      vals.forEach((v, i) => {
        const c = el("circle", { cx: xS(eventDays[i]), cy: yS(v), r: 4.6, fill: color, stroke: col.surface, "stroke-width": 2 }, svg);
        hover(c, `${label} · ${eventDays[i] === 0 ? "부착 당일" : `${eventDays[i] > 0 ? "+" : ""}${eventDays[i]}일`}`, [
          ["평소 대비 ln(순위)", v.toFixed(3), color],
          ["해석", v < 0 ? "평소보다 상위" : "평소보다 하위"],
        ]);
      });
      const last = vals[vals.length - 1];
      txt(svg, x1 + 12, yS(last) + (key === "쿠폰" ? 14 : -2), label, { "font-size": 12, fill: color, "font-weight": 750 });
    });

    txt(svg, (x0 + x1) / 2, H - 8, "배지 부착일 기준 경과일 · 값이 작을수록(위쪽) 평소보다 상위", {
      "text-anchor": "middle", "font-size": 11.5, fill: col.muted,
    });
  }

  /* --- 표 10. 교차지연 (시차 전환) --- */
  let lagKey = "1일";
  function drawLag() {
    const col = C(), W = 980, H = 250;
    const svg = makeSvg("chLag", W, H);
    if (!svg) return;
    const L = 210, R = 90, T = 26, B = 46;
    const x0 = L, x1 = W - R, maxX = 26;
    const xS = (v) => x0 + (v / maxX) * (x1 - x0);
    const d = lagData[lagKey];
    /* 부호까지 반영: 정방향 경로가 유의해도 7일 시차에서는 방향이 반대(순위 하락)다 */
    const fwdKind = d.fwd >= 2 ? "reverse" : "none";
    const rows = [
      [`전일 리뷰 증가 → 당일 순위 상승`, d.fwd, fwdKind],
      [`전일 랭킹 상위 → 당일 리뷰 증가`, d.rev, "signal"],
    ];
    const rowH = (H - T - B) / rows.length;

    [0, 5, 10, 15, 20, 25].forEach((v) => {
      const x = xS(v);
      el("line", { x1: x, y1: T, x2: x, y2: H - B, stroke: col.grid, "stroke-width": 1 }, svg);
      txt(svg, x, H - B + 17, String(v), { "text-anchor": "middle", "font-size": 11, fill: col.muted });
    });

    const kindFill = { signal: col.s1, reverse: col.s3, none: col.neutral };
    const kindVerdict = {
      signal: "유의 (|t| > 2)",
      reverse: "유의하나 부호가 반대 — 순위 하락",
      none: "미검출 (|t| ≤ 2)",
    };
    rows.forEach(([lab, v, kind], i) => {
      const bh = rowH - 26, y = T + i * rowH + 13;
      const fill = kindFill[kind];
      const p = el("path", { d: barPath(x0, y, Math.max(xS(v) - x0, 2), bh, 4, "right"), fill }, svg);
      hover(p, lab, [
        ["신호 강도 |t|", v.toFixed(1), fill],
        ["시차", lagKey],
        ["판정", kindVerdict[kind]],
      ]);
      const seg = lab.split(" → ");
      txt(svg, x0 - 12, y + bh / 2 - 3, seg[0] + " →", { "text-anchor": "end", "font-size": 12, fill: col.ink, "font-weight": 650 });
      txt(svg, x0 - 12, y + bh / 2 + 13, seg[1], { "text-anchor": "end", "font-size": 12, fill: col.ink2 });
      txt(svg, xS(v) + 9, y + bh / 2 + 4, v.toFixed(1), {
        "font-size": 12.5, fill: kind === "none" ? col.neutralInk : col.ink, "font-weight": 750,
      });
    });

    legend("lgLag", [
      ["순위 → 리뷰 (유의)", col.s1],
      ...(fwdKind === "reverse" ? [["리뷰 → 순위 (역방향 유의)", col.s3]] : []),
      ...(fwdKind === "none" ? [["리뷰 → 순위 (미검출)", col.neutral]] : []),
    ]);

    const xt = xS(2);
    el("line", { x1: xt, y1: T - 6, x2: xt, y2: H - B, stroke: col.s3, "stroke-width": 1.8, "stroke-dasharray": "5 4" }, svg);
    txt(svg, xt + 7, T - 10, "신호 판정선 (|t| = 2)", { "font-size": 11.5, fill: col.s3, "font-weight": 750 });
    txt(svg, (x0 + x1) / 2, H - 8, "통계적 신호의 강도 (상품 클러스터 보정 |t|)", {
      "text-anchor": "middle", "font-size": 11.5, fill: col.muted,
    });
  }

  /* --- 그림 11. 썸네일 시각 특성 --- */
  function drawThumbSignal() {
    const col = C(), W = 980, H = 330;
    const svg = makeSvg("chThumb", W, H);
    if (!svg) return;
    const L = 150, R = 70, T = 24, B = 48;
    const x0 = L, x1 = W - R, maxX = 10;
    const xS = (v) => x0 + (v / maxX) * (x1 - x0);
    const rowH = (H - T - B) / thumbSignal.length;

    [0, 2, 4, 6, 8, 10].forEach((v) => {
      const x = xS(v);
      el("line", { x1: x, y1: T, x2: x, y2: H - B, stroke: col.grid, "stroke-width": 1 }, svg);
      txt(svg, x, H - B + 17, String(v), { "text-anchor": "middle", "font-size": 11, fill: col.muted });
    });

    thumbSignal.forEach(([lab, before, after], i) => {
      const bh = (rowH - 16) / 2 - 1;
      const yTop = T + i * rowH + 8;
      const b1 = el("path", { d: barPath(x0, yTop, Math.max(xS(before) - x0, 2), bh, 3, "right"), fill: col.neutral }, svg);
      const b2 = el("path", { d: barPath(x0, yTop + bh + 2, Math.max(xS(after) - x0, 2), bh, 3, "right"), fill: col.s1 }, svg);
      hover(b1, `${lab} — 판매 요인 통제 전`, [["신호 강도 |t|", before.toFixed(2), col.neutral]]);
      hover(b2, `${lab} — 판매 요인 통제 후`, [
        ["신호 강도 |t|", after.toFixed(2), col.s1],
        ["판정", after >= 2 ? "유의하게 잔존" : "신호 소멸"],
      ]);
      txt(svg, x0 - 12, yTop + rowH / 2 - 2, lab, { "text-anchor": "end", "font-size": 12.5, fill: col.ink, "font-weight": 650 });
      if (i === 0) {
        txt(svg, xS(before) + 9, yTop + bh / 2 + 4, "통제 전", { "font-size": 11.5, fill: col.neutralInk, "font-weight": 700 });
        txt(svg, xS(after) + 9, yTop + bh + 2 + bh / 2 + 4, "통제 후", { "font-size": 11.5, fill: col.s1, "font-weight": 800 });
      }
    });

    const xt = xS(2);
    el("line", { x1: xt, y1: T - 6, x2: xt, y2: H - B, stroke: col.s3, "stroke-width": 1.8, "stroke-dasharray": "5 4" }, svg);
    txt(svg, xt + 7, T - 10, "이 선을 넘어야 신뢰할 수 있는 신호", { "font-size": 11.5, fill: col.s3, "font-weight": 750 });
    txt(svg, (x0 + x1) / 2, H - 8, "통계적 신호의 강도 (상품 클러스터 보정 |t|)", {
      "text-anchor": "middle", "font-size": 11.5, fill: col.muted,
    });
  }

  /* --- 표 12. 썸네일 마케팅 속성 --- */
  function drawThumbAttr() {
    const col = C(), W = 980, H = 250;
    const svg = makeSvg("chThumbAttr", W, H);
    if (!svg) return;
    const L = 160, R = 90, T = 16, B = 46;
    const x0 = L, x1 = W - R, maxX = 45;
    const xS = (v) => x0 + (v / maxX) * (x1 - x0);
    const rowH = (H - T - B) / thumbAttr.length;

    [0, 10, 20, 30, 40].forEach((v) => {
      const x = xS(v);
      el("line", { x1: x, y1: T, x2: x, y2: H - B, stroke: col.grid, "stroke-width": 1 }, svg);
      txt(svg, x, H - B + 17, `${v}%`, { "text-anchor": "middle", "font-size": 11, fill: col.muted });
    });

    thumbAttr.forEach(([lab, n, pct], i) => {
      const bh = rowH - 20, y = T + i * rowH + 10;
      const p = el("path", { d: barPath(x0, y, xS(pct) - x0, bh, 4, "right"), fill: col.s2 }, svg);
      hover(p, lab, [
        ["해당 썸네일", `${n}장 / 160장`, col.s2],
        ["표본 내 비중", `${pct.toFixed(1)}%`],
        ["순위 연관성", "상위권 방향 · 통계적 미확정"],
      ]);
      txt(svg, x0 - 12, y + bh / 2 + 4, lab, { "text-anchor": "end", "font-size": 12.5, fill: col.ink, "font-weight": 650 });
      txt(svg, xS(pct) + 9, y + bh / 2 + 4, `${pct.toFixed(1)}%`, { "font-size": 12.5, fill: col.ink2, "font-weight": 700 });
    });
    txt(svg, (x0 + x1) / 2, H - 8, "160장 수기 분류 표본 내 비중 · 4개 속성 모두 상위권 방향이나 통계적으로는 미확정", {
      "text-anchor": "middle", "font-size": 11.5, fill: col.muted,
    });
  }

  /* ==========================================================
     INIT
     ========================================================== */
  function drawAll() {
    drawChurn();
    drawCohort();
    drawVariance();
    drawCategory();
    drawRating();
    drawElasticity();
    drawPromo();
    drawEvent();
    drawLag();
    drawThumbSignal();
    drawThumbAttr();

    const col = C();
    legend("lgEvent", [["쿠폰 부착 (705건)", col.s1, "line"], ["세일 부착 (124건)", col.s3, "line"]]);
    legend("lgThumb", [["판매 요인 통제 전", col.neutral], ["판매 요인 통제 후", col.s1]]);
    legend("lgVariance", [["리뷰 총량", col.neutral], ["리뷰 증가 속도 포함", col.s1]]);
    legend("lgElasticity", [["리뷰 증가 속도 (판매량 대리)", col.s1], ["실제 판매가격", col.s2]]);
    legend("lgPromo", [["순위 개선", col.s1], ["순위 악화", col.s3]]);
  }

  function initControls() {
    document.querySelectorAll("#segLag button").forEach((b) => {
      b.addEventListener("click", () => {
        document.querySelectorAll("#segLag button").forEach((x) => x.classList.toggle("on", x === b));
        lagKey = b.dataset.lag;
        drawLag();
        const note = document.getElementById("lagNote");
        if (note) note.textContent = {
          "1일": "1일 시차 — 전일 리뷰 증가는 당일 순위를 전혀 예측하지 못한다 (|t| = 0.4).",
          "3일": "3일 시차 — 배송·작성 지연을 고려해 넓혀도 결과는 같다 (|t| = 0.5).",
          "7일": "7일 시차 — 유의해지지만 부호가 음(−)이다. 리뷰가 급증했던 상품일수록 이후 순위가 되돌림된다.",
        }[lagKey];
      });
    });
  }

  /* 스크롤 스파이 — 현재 섹션 표시 */
  function initSpy() {
    const links = [...document.querySelectorAll(".nav-links a")];
    const map = new Map();
    links.forEach((a) => {
      const id = a.getAttribute("href").slice(1);
      const sec = document.getElementById(id);
      if (sec) map.set(sec, a);
    });
    if (!map.size) return;
    const obs = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          links.forEach((a) => a.style.removeProperty("color"));
          const a = map.get(e.target);
          if (a) a.style.color = "var(--accent)";
        }
      });
    }, { rootMargin: "-56px 0px -70% 0px" });
    map.forEach((_, sec) => obs.observe(sec));
  }

  function boot() {
    drawAll();
    initControls();
    initSpy();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  /* 다크/라이트 전환 시 색 토큰 다시 읽어 재렌더 */
  if (window.matchMedia) {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const rerender = () => { drawAll(); };
    if (mq.addEventListener) mq.addEventListener("change", rerender);
    else if (mq.addListener) mq.addListener(rerender);
  }
})();
