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
    wine: css("--wine"),
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
    tip.className = "";                 /* 용어 메모 스타일이 남아 있을 수 있다 */
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
     DATA — 모든 수치는 결과보고서(2026-08-28) 본문·도표 기준
     ========================================================== */

  /* 그림 1. 전체 TOP100 일별 신규 진입 수 (직전일 대비) */
  const churn = [
    ["08-04", 28], ["08-05", 34], ["08-06", 44], ["08-07", 36], ["08-08", 38],
    ["08-09", 42], ["08-10", 48], ["08-11", 35], ["08-12", 32], ["08-13", 34],
    ["08-14", 36], ["08-15", 30], ["08-16", 28], ["08-17", 36], ["08-18", 33],
    ["08-19", 35], ["08-20", 32], ["08-21", 32], ["08-22", 39], ["08-23", 29],
    ["08-24", 39], ["08-25", 27], ["08-26", 34], ["08-27", 31],
  ];
  const churnMean = 35;

  /* 그림 2. 코호트 전이 행렬 — 행 기준 % */
  const cohortRows = ["1–10위", "11–25위", "26–50위", "51–75위", "76–100위"];
  const cohortCols = ["1–10위", "11–25위", "26–50위", "51–75위", "76–100위", "100위 밖"];
  const cohort = [
    [59, 19, 8, 4, 3, 7],
    [13, 42, 22, 6, 3, 13],
    [3, 13, 37, 19, 8, 21],
    [1, 3, 18, 27, 17, 34],
    [1, 2, 8, 16, 24, 49],
  ];

  /* 그림 3. 설명력 분해 (within R², %) */
  const variance = [
    ["리뷰 총량만", 5.8, "n"],
    ["리뷰 증가 속도만", 14.1, "s1"],
    ["두 변수 모두", 14.1, "s1"],
  ];

  /* 그림 4. 카테고리별 리뷰 증가 속도–순위 상관 (음수 = 빠를수록 상위) */
  const catCorr = [
    ["취미/팬시", -0.28, -0.43, -0.16], ["구강용품", -0.28, -0.43, -0.13],
    ["홈리빙/가전", -0.29, -0.48, 0.12], ["스킨케어", -0.29, -0.46, -0.17],
    ["메이크업", -0.29, -0.51, -0.17], ["바디케어", -0.30, -0.48, -0.21],
    ["헬스/건강용품", -0.31, -0.40, -0.12], ["향수/디퓨저", -0.32, -0.53, -0.11],
    ["헤어케어", -0.34, -0.50, -0.21], ["푸드", -0.34, -0.41, -0.24],
    ["더모 코스메틱", -0.35, -0.53, -0.05], ["패션", -0.35, -0.59, -0.16],
    ["마스크팩", -0.38, -0.51, -0.29], ["맨즈에딧", -0.40, -0.55, -0.22],
    ["건강식품", -0.41, -0.53, -0.25], ["뷰티소품", -0.45, -0.55, -0.34],
    ["선케어", -0.46, -0.62, -0.37], ["클렌징", -0.50, -0.67, -0.32],
    ["위생용품", -0.55, -0.69, -0.40], ["네일", -0.61, -0.73, -0.51],
  ];

  /* 그림 5. 상품 평균 별점 분포 (0.1점 구간 상품 수) */
  const ratingBins = [
    [0.0, 1050], [4.1, 40], [4.2, 80], [4.3, 150], [4.4, 330],
    [4.5, 3100], [4.6, 7400], [4.7, 17200], [4.8, 12400],
  ];

  /* 그림 6. 표준화 영향력 (탄력성 절댓값) */
  const elasticity = [["리뷰 증가 속도 (판매량 대리지표)", 0.40, "s1"], ["실제 판매가격", 0.35, "s2"]];

  /* 표 7. 동일 상품 내 프로모션별 순위 변화율 (+ = 개선) */
  const promo = [
    ["쿠폰 배지", 12.9, 5.5], ["증정 배지", 10.0, 5.7],
    ["할인율 (1%p당)", 2.7, 10.1], ["세일 배지", -19.5, 2.9],
  ];

  /* 그림 8. 이벤트 스터디 — 평소 순위 대비 ln(순위) 편차 (음수 = 상위) */
  const eventDays = [-3, -2, -1, 0, 1, 2, 3];
  const eventSeries = {
    쿠폰: [0.098, 0.115, 0.112, -0.410, -0.118, -0.100, -0.055],
    세일: [-0.065, 0.190, 0.220, -0.135, -0.255, -0.128, -0.108],
  };

  /* 표 10. 교차지연 검정 — |t| (클러스터 보정) */
  const lagData = {
    "1일": { fwd: 0.2, rev: 24.6 },
    "3일": { fwd: 0.8, rev: 22.2 },
    "7일": { fwd: 3.8, rev: 20.2 },
  };

  /* 그림 11. 썸네일 시각 특성별 |t| — 판매 요인 통제 전 / 후 */
  const thumbSignal = [
    ["구성 복잡도", 8.3, 4.0], ["색 다양성", 4.3, 2.2],
    ["흰 배경 비율", 2.7, 2.1], ["채도", 2.0, 0.75], ["밝기", 0.4, 1.0],
  ];

  /* 그림 11. 리뷰 본문 문서빈도 상위 어휘 (analysis/review_text.py 산출) */
  const cloudWords = [
    ["피부", 12663], ["느낌", 11740], ["향", 6925], ["꾸준히", 5709],
    ["자극", 4786], ["여름", 4694], ["촉촉", 4505], ["효과", 4455],
    ["부담", 4083], ["재구매", 3731], ["얼굴", 3668], ["제형", 3508],
    ["가격", 3488], ["데일리", 3479], ["아침", 3108], ["부드럽게", 2946],
    ["메이크업", 2897], ["끈적임", 2788], ["매일", 2694], ["화장", 2585],
    ["지속력", 2475], ["만족", 2408], ["거품", 2362], ["시간", 2360],
    ["선크림", 2349], ["성분", 2339], ["크림", 2238], ["자연스럽게", 2237],
    ["가성비", 2183], ["트러블", 2175], ["깔끔하게", 2057], ["가볍게", 2018],
    ["발림성", 1984], ["타입", 1948], ["도움", 1914], ["구성", 1914],
    ["관리", 1830], ["흡수", 1759], ["냄새", 1748], ["세안", 1741],
    ["용량", 1669], ["나면", 1661], ["부드럽고", 1660], ["진정", 1654],
    ["편하고", 1630], ["기획", 1599], ["머리", 1590], ["수분", 1581],
  ];

  /* 그림 12. 소구 속성별 언급률 (%) — 전체 및 카테고리별 */
  const attrNames = ["보습·수분", "발림·제형", "자극·순함", "가격·가성비", "향", "끈적임·마무리", "재구매 의사", "지속력", "트러블·진정", "커버·발색"];
  const attrOverall = [19.6, 18.3, 16.6, 15.1, 14.2, 12.7, 12.5, 9.3, 9.3, 8.9];
  const attrProfile = [
    ["메이크업", 6338, [18.9, 19.3, 3.3, 9.6, 2.9, 16.2, 10.0, 26.9, 6.2, 31.5]],
    ["스킨케어", 6001, [44.9, 36.0, 31.5, 14.6, 5.8, 27.6, 15.4, 6.7, 26.0, 5.6]],
    ["선케어", 4503, [32.0, 35.2, 17.9, 12.7, 4.6, 36.2, 11.1, 6.6, 10.0, 25.4]],
    ["클렌징", 4466, [25.9, 20.4, 47.8, 13.2, 8.0, 8.2, 14.1, 2.6, 12.8, 1.5]],
    ["마스크팩", 4415, [41.9, 16.0, 26.5, 15.7, 3.7, 12.4, 17.5, 6.3, 24.3, 18.7]],
    ["헤어케어", 3803, [9.2, 20.6, 9.9, 14.5, 34.8, 12.4, 13.2, 10.4, 2.9, 3.3]],
    ["푸드", 3357, [1.4, 3.5, 3.2, 17.1, 5.9, 0.6, 14.6, 2.0, 0.5, 0.2]],
    ["바디케어", 3342, [28.1, 19.3, 19.3, 12.0, 45.0, 18.1, 11.2, 8.8, 6.7, 3.6]],
    ["건강식품", 3078, [2.2, 3.8, 2.2, 20.2, 4.1, 0.4, 14.4, 3.0, 0.7, 0.1]],
    ["위생용품", 3048, [9.6, 21.9, 26.4, 21.5, 17.4, 7.5, 15.4, 5.7, 1.5, 4.6]],
    ["뷰티소품", 2770, [4.8, 16.3, 13.5, 20.5, 1.2, 3.0, 12.6, 5.0, 2.3, 9.0]],
    ["네일", 2746, [14.1, 20.2, 4.4, 14.5, 16.2, 8.5, 8.3, 14.9, 0.5, 6.0]],
    ["맨즈에딧", 2737, [21.0, 17.2, 12.9, 13.2, 20.0, 19.3, 10.6, 10.7, 7.9, 8.5]],
    ["헬스/건강용품", 2573, [4.9, 4.8, 9.8, 16.4, 7.7, 2.6, 11.0, 4.4, 20.2, 8.1]],
    ["구강용품", 2520, [1.9, 5.1, 13.5, 17.5, 16.9, 1.3, 14.0, 7.4, 0.1, 0.5]],
    ["향수/디퓨저", 2492, [2.2, 4.3, 3.7, 17.1, 80.2, 4.4, 9.4, 32.5, 0.5, 0.4]],
    ["더모 코스메틱", 2127, [48.0, 33.7, 34.2, 13.1, 10.4, 22.3, 12.1, 7.2, 27.5, 5.7]],
    ["패션", 1724, [1.0, 5.2, 5.8, 16.1, 0.4, 1.3, 8.2, 1.7, 0.4, 6.5]],
    ["홈리빙/가전", 1226, [4.6, 3.7, 6.4, 15.9, 30.3, 1.2, 10.3, 6.8, 0.6, 0.4]],
    ["취미/팬시", 844, [0.5, 4.4, 1.2, 19.5, 0.7, 0.7, 6.0, 2.7, 0.0, 0.4]],
  ];

  /* 표 12. 썸네일 마케팅 소구 속성 (160장 수기 분류) */
  const thumbAttr = [
    ["순위 · 수상 클레임", 61, 38.1], ["증정 · 기획 구성", 53, 33.1],
    ["인물 모델 등장", 43, 26.9], ["기간 한정 소구", 15, 9.4],
  ];


  /* 그림 9. 할인율–판매 반응 유형별 곡선 (0% 구간 대비 ln 판매) */
  const discBands = ["0%", "1–10%", "10–20%", "20–30%", "30–40%", "40%+"];
  const discTypes = [
    ["가속형", "s1", [0, 0.19, 0.13, 0.24, 0.50, 0.63], [0, 0.53, 0.49, 0.78, 0.90, 1.09], 18, 1129],
    ["데스밸리형", "s3", [0, -0.19, -0.11, 0.18, 0.24, 0.34], [0, -0.43, 0.19, 0.61, 0.78, 0.56], 13, 862],
    ["무반응·역행형", "s2", [0, -0.31, -0.41, -0.26, -0.20, -0.11], [0, -0.14, -0.20, -0.01, 0.09, 0.05], 18, 1214],
    ["소액반응형", "neutralInk", [0, 0.24, 0.08, -0.11, 0.05, -0.16], [0, 0.08, 0.13, -0.28, 0.06, -0.06], 7, 469],
  ];

  /* 그림 10. 프로모션 온셋 전후 판매지수 — 실제와 반사실 (사전 평균 = 100) */
  const cfDays = ["D-7", "D-6", "D-5", "D-4", "D-3", "D-2", "D-1", "D+0", "D+1", "D+2", "D+3", "D+4"];
  const cfPre = [104.5, 92.6, 121.9, 101.8, 102.2, 109.3, 74.1];
  const cfPost = {
    "실제(Actual)": [123.5, 119.2, 102.9, 109.5, 100.9],
    "신경망(MLP)": [122.2, 114.7, 104.8, 105.4, 97.5],
    "EARTH(MARS)": [117.1, 112.6, 104.7, 106.5, 99.6],
    "시장대조(DiD)": [114.9, 107.7, 97.0, 98.9, 90.2],
    "ARIMA(1,0,0)": [112.6, 94.4, 106.2, 97.5, 103.9],
    "사전평균(무보정)": [100.0, 101.1, 101.0, 100.0, 101.0],
  };

  const cfStyles = [
    ["실제(Actual)", "ink", 3.2, null],
    ["신경망(MLP)", "s1", 2.2, "6 4"],
    ["EARTH(MARS)", "s2", 2, "6 4"],
    ["시장대조(DiD)", "wine", 1.8, "3 4"],
    ["ARIMA(1,0,0)", "s3", 1.8, "3 4"],
    ["사전평균(무보정)", "neutralInk", 2, "2 5"],
  ];

  /* 그림 13. 카테고리별 비(非)긍정 리뷰 비중 — [카테고리, 긍정%, 3점%, 부정%, 상품수] */
  const revCat = [
    ["취미/팬시", 89.5, 5.9, 4.58, 24], ["네일", 91.7, 5.6, 2.67, 83],
    ["패션", 92.3, 4.8, 2.90, 103], ["헬스/건강용품", 93.5, 4.5, 1.76, 181],
    ["메이크업", 93.8, 4.3, 1.96, 183], ["선케어", 94.3, 3.7, 2.08, 183],
    ["구강용품", 94.5, 4.0, 1.43, 230], ["뷰티소품", 94.5, 3.9, 1.50, 213],
    ["푸드", 94.7, 3.6, 1.61, 211], ["향수/디퓨저", 95.1, 3.2, 1.59, 215],
    ["바디케어", 95.2, 3.4, 1.24, 186], ["헤어케어", 95.2, 3.4, 1.23, 190],
    ["마스크팩", 95.3, 3.4, 1.39, 198], ["홈리빙/가전", 95.4, 3.1, 1.56, 50],
    ["더모 코스메틱", 95.7, 3.0, 1.12, 197], ["클렌징", 95.8, 3.1, 1.08, 173],
    ["스킨케어", 95.9, 2.9, 1.08, 132], ["맨즈에딧", 96.0, 2.7, 0.98, 208],
    ["건강식품", 96.0, 3.0, 0.83, 262], ["위생용품", 96.2, 2.7, 0.92, 180],
  ];

  /* 그림 14. 브랜드별 긍정 비중 산포 — [브랜드, 긍정 비중%, 브랜드 내 상품 간 표준편차%p, 상품수] */
  const revBrand = [
    ["라이브오랄스",88.60,3.05,5], ["베리시",89.00,7.92,10], ["바나실",89.60,5.03,5], ["마르시끄",89.70,2.54,10], ["체이싱래빗",90.60,2.61,5], ["위드샨",90.62,3.36,16],
    ["알로",90.83,2.48,6], ["마른파이브",91.15,2.97,13], ["민티드",91.20,3.03,5], ["센시안",91.45,5.30,11], ["리무브",91.50,3.02,6], ["이지덤뷰티",91.60,4.51,5],
    ["해서린",92.00,4.00,5], ["에이딕트",92.12,2.95,8], ["웨이크메이크",92.12,2.03,24], ["디오디너리",92.40,1.67,5], ["유시몰",92.56,3.75,27], ["셀라딕스",92.60,1.67,5],
    ["케어플러스",92.63,5.18,19], ["비플레인",92.71,8.09,17], ["반디",92.80,3.43,10], ["센녹",92.80,2.17,5], ["파넬",92.83,3.25,6], ["크런틴",92.83,3.82,6],
    ["리브러쉬",92.88,2.30,8], ["다슈",92.89,4.46,27], ["필리밀리",92.91,4.36,68], ["쏘내추럴",93.00,3.29,6], ["데싱디바",93.14,2.61,7], ["힌스",93.17,2.14,6],
    ["비너스",93.17,2.32,6], ["그린몬스터",93.17,2.71,6], ["메디큐브",93.19,2.20,16], ["청미정",93.20,1.48,5], ["나르카",93.20,1.30,5], ["푸드올로지",93.33,2.82,24],
    ["발란스핏",93.40,3.05,5], ["컬러그램",93.50,1.38,6], ["프로티원",93.50,3.56,6], ["네이밍",93.57,2.07,7], ["식물나라",93.61,2.87,31], ["케라스타즈",93.62,1.85,8],
    ["나르시소 로드리게즈",93.67,2.66,6], ["코스노리",93.71,3.25,7], ["아리얼",93.75,4.56,8], ["낫포유",93.80,1.64,5], ["테일러",93.80,2.68,5], ["grn+",93.80,1.48,5],
    ["아뜰리에페이",93.86,2.85,7], ["페리오",93.89,2.89,9], ["뷰센",93.92,3.18,12], ["코자아",94.00,2.45,6], ["퓌",94.00,1.69,8], ["칼로(Kalo)",94.00,1.22,5],
    ["프롬리에",94.00,2.35,5], ["플르부아",94.00,1.67,6], ["일소",94.08,2.02,12], ["박준뷰티랩",94.11,2.57,9], ["플라이밀",94.14,2.97,7], ["낫띵베럴",94.20,1.30,5],
    ["홀리카홀리카",94.20,3.03,5], ["아누아",94.21,2.28,28], ["유세린",94.25,2.05,12], ["에스쁘아",94.29,2.14,7], ["로레알",94.33,2.35,9], ["라로슈포제",94.38,2.25,32],
    ["바이오던스",94.40,2.01,10], ["테라브레스",94.42,5.14,12], ["에뛰드",94.42,2.43,12], ["라운드어라운드",94.42,2.02,12], ["정샘물",94.43,1.62,7], ["더툴랩",94.43,1.27,7],
    ["메디필",94.50,2.14,8], ["투쿨포스쿨",94.50,1.64,6], ["넥스케어",94.57,3.99,7], ["아떼",94.57,1.72,7], ["달바",94.58,3.20,12], ["팁토우",94.60,1.95,5],
    ["피카소",94.62,2.87,13], ["바른생각",94.64,2.06,14], ["브링그린",94.67,1.94,27], ["동국제약",94.67,3.44,6], ["탄탄",94.67,1.51,6], ["버버리",94.67,2.34,6],
    ["올리브영",94.70,3.36,37], ["조선미녀",94.78,1.92,9], ["롬앤",94.80,2.10,10], ["크리스탈",94.80,0.45,5], ["이즈앤트리",94.80,1.30,5], ["바이탈뷰티",94.86,1.57,7],
    ["라보에이치",94.89,1.05,9], ["티젠",94.89,2.26,9], ["구달",94.92,1.98,13], ["한율",95.00,0.76,8], ["니베아",95.00,1.67,6], ["클린",95.00,1.69,8],
    ["딜라이트 프로젝트",95.00,2.34,31], ["미쟝센",95.00,2.28,11], ["듀이트리",95.08,2.50,12], ["그라펜",95.10,3.60,10], ["올더베러",95.11,1.45,19], ["이지듀",95.12,1.73,8],
    ["토르홉",95.14,1.86,7], ["코링코",95.17,0.75,6], ["아비브",95.18,2.46,17], ["루치펠로",95.19,2.26,16], ["라네즈",95.25,3.24,8], ["프리메라",95.29,0.76,7],
    ["해피바스",95.29,2.29,7], ["닥터포헤어",95.30,1.25,10], ["아벤느",95.33,1.41,9], ["이니스프리",95.36,3.59,11], ["화이트",95.36,3.20,11], ["아로마티카",95.38,1.41,8],
    ["바이오가",95.38,1.92,8], ["넘버즈인",95.39,1.12,23], ["오니스트",95.40,1.52,5], ["바닐라코",95.47,2.76,19], ["헤트라스",95.50,1.69,8], ["보다나",95.50,3.39,6],
    ["코스알엑스",95.50,3.02,8], ["클리오",95.56,1.13,9], ["큐라덴",95.60,1.14,5], ["키스미",95.60,2.30,5], ["아비노",95.60,1.67,5], ["위시어",95.60,0.55,5],
    ["멈칫",95.60,1.34,5], ["바이오힐보",95.62,2.13,21], ["락토핏",95.62,3.89,8], ["셀퓨전씨",95.67,1.41,9], ["에스네이처",95.69,1.18,13], ["이너시아",95.75,2.19,8],
    ["에스트라",95.76,1.44,33], ["마녀공장",95.78,1.30,9], ["존슨즈",95.80,1.48,5], ["아크네스",95.80,0.84,5], ["올리오",95.83,1.47,6], ["페리페라",95.83,1.17,6],
    ["바이오더마",95.85,1.92,33], ["멜라메이트",95.86,0.38,7], ["바이오코어유산균",95.86,1.35,7], ["제로이드",95.91,0.90,23], ["스튜디오17",95.92,1.68,12], ["메디힐",95.97,1.77,30],
    ["쏘피",96.00,1.18,11], ["닥터디퍼런트",96.00,2.00,5], ["가그린",96.00,2.24,5], ["랑방",96.00,1.26,11], ["오랄비",96.00,1.41,5], ["지미추",96.00,1.41,6],
    ["유리아쥬",96.00,3.30,8], ["토리든",96.12,2.30,25], ["폴프랜즈",96.12,0.99,8], ["쉬크",96.14,1.21,7], ["어노브",96.14,2.11,14], ["나른",96.17,1.75,12],
    ["덴티스테",96.18,1.42,17], ["바이컬러",96.20,0.84,5], ["리쥬란",96.20,1.61,15], ["닥터자르트",96.20,0.84,5], ["비욘드",96.20,2.05,5], ["아리아나그란데",96.20,0.84,5],
    ["갸스비",96.22,1.79,9], ["헤라",96.25,1.39,8], ["메이크프렘",96.25,1.49,8], ["라엘",96.25,1.36,12], ["오브제",96.28,3.03,18], ["세타필",96.29,2.21,7],
    ["비비랩",96.33,1.56,12], ["스킨푸드",96.33,0.52,6], ["라곰",96.33,1.37,6], ["셀리맥스",96.38,1.85,8], ["존바바토스",96.40,0.89,5], ["닥터지",96.43,1.50,23],
    ["라운드랩",96.44,1.52,45], ["리스테린",96.46,1.39,13], ["아이디얼포맨",96.50,2.18,14], ["디어스킨",96.50,2.27,8], ["네이처메이드",96.50,0.84,6], ["피지오겔",96.53,1.31,19],
    ["일리윤",96.54,1.67,24], ["캘빈클라인",96.56,1.01,9], ["닥터텅스",96.60,2.30,5], ["츠바키",96.60,1.34,5], ["웰라쥬",96.71,0.95,7], ["파티온",96.73,1.19,11],
    ["포맨트",96.76,1.52,17], ["프롬랩스",96.80,1.30,5], ["비페스타",96.80,1.48,5], ["AHC",96.89,1.05,9], ["세노비스",96.93,1.33,14], ["스킨1004",97.00,1.22,5],
    ["휴족시간",97.00,0.89,6], ["스너글",97.00,0.85,12], ["아이오페",97.06,1.12,16], ["비레디",97.14,1.35,7], ["아토팜",97.17,0.98,6], ["유기농본",97.20,0.45,5],
    ["센카",97.20,1.64,5], ["우르오스",97.27,0.79,11], ["뉴오리진",97.40,0.55,5], ["동아제약",97.50,1.05,6], ["고려은단",97.54,0.78,13], ["순수한면",97.60,1.82,5],
    ["질레트",97.71,0.92,17], ["정관장",97.71,0.76,7], ["시루콧토",97.71,0.95,7], ["오쏘몰",97.71,0.49,7], ["좋은느낌",97.74,0.73,19], ["덴프스",97.75,0.89,8],
    ["크리넥스",97.80,1.64,5], ["VT",98.00,1.41,10], ["옵티프리",98.33,0.52,6],
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
      if (i % 3 === 0) {
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
    const maxY = 18000;
    const xS = (v) => x0 + (v / 5.2) * (x1 - x0);
    const yS = (v) => y1 - (v / maxY) * (y1 - y0);
    const bw = xS(0.1) - xS(0);

    [0, 5000, 10000, 15000].forEach((v) => {
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

    txt(svg, x1 + 46, T + 34, "영향력 비율 0.88", { "font-size": 13, fill: col.s3, "font-weight": 800 });
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

    const series = [["쿠폰", col.s1, "쿠폰 부착 (937건)"], ["세일", col.s3, "세일 부착 (148건)"]];
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

  /* --- 그림 11. 리뷰 어휘 워드클라우드 --- */
  function drawCloud() {
    const col = C(), W = 980, H = 420;
    const svg = makeSvg("chCloud", W, H);
    if (!svg) return;

    const max = cloudWords[0][1], min = cloudWords[cloudWords.length - 1][1];
    const size = (n) => 15 + 40 * Math.sqrt((n - min) / (max - min));
    /* 크기가 주 인코딩, 색은 3단계 보조 — 작은 글자도 읽히는 명도만 사용한다 */
    const shade = (n) => {
      const r = (n - min) / (max - min);
      if (r > 0.34) return col.seq[5];
      if (r > 0.12) return col.seq[4];
      return col.ink2;
    };

    const placed = [];
    const cx = W / 2, cy = H / 2;
    const hits = (b) => placed.some((p) =>
      !(b.x + b.w < p.x || p.x + p.w < b.x || b.y + b.h < p.y || p.y + p.h < b.y));

    cloudWords.forEach(([word, n], i) => {
      const fs = size(n);
      const w = word.length * fs * 1.02 + 10;
      const h = fs * 1.25;
      /* 아르키메데스 나선을 따라 겹치지 않는 자리를 찾는다 */
      let x = cx, y = cy, ok = false;
      for (let t = 0; t < 3200; t++) {
        const a = t * 0.32;
        const rad = 4 + a * 2.6;
        x = cx + rad * Math.cos(a) * 1.55 - w / 2;
        y = cy + rad * Math.sin(a) * 0.72 - h / 2;
        if (x < 4 || y < 4 || x + w > W - 4 || y + h > H - 4) continue;
        if (!hits({ x, y, w, h })) { ok = true; break; }
      }
      if (!ok) return;
      placed.push({ x, y, w, h });
      const t = txt(svg, x + w / 2, y + h * 0.78, word, {
        "text-anchor": "middle", "font-size": fs.toFixed(1),
        "font-weight": i < 8 ? 800 : 700, fill: shade(n),
      });
      hover(t, word, [
        ["언급 리뷰", `${fmt(n, 0)}건`, shade(n)],
        ["전체 대비", `${(n / 68996 * 100).toFixed(1)}%`],
      ]);
    });
  }

  /* --- 그림 12. 카테고리 × 소구 속성 언급률 히트맵 --- */
  function drawAttr() {
    const col = C(), W = 980, rows = attrProfile.length;
    const L = 118, R = 16, T = 62, B = 34, ch = 24;
    const H = T + rows * ch + B;
    const svg = makeSvg("chAttr", W, H);
    if (!svg) return;
    const cw = (W - L - R) / attrNames.length;

    const ramp = (v) => {
      const steps = [[0, 0], [5, 1], [10, 2], [18, 3], [28, 4], [42, 5]];
      let idx = 0;
      for (const [th, i] of steps) if (v >= th) idx = i;
      return col.seq[idx];
    };

    attrNames.forEach((name, j) => {
      const cx = L + j * cw + cw / 2;
      const parts = name.split("·");
      /* 한 줄짜리 이름도 '전체 n%' 와 같은 베이스라인에 맞춰 헤더가 들쭉날쭉하지 않게 한다 */
      if (parts[1]) {
        txt(svg, cx, T - 32, parts[0], { "text-anchor": "middle", "font-size": 11.5, fill: col.ink, "font-weight": 700 });
        txt(svg, cx, T - 19, parts[1], { "text-anchor": "middle", "font-size": 11.5, fill: col.ink, "font-weight": 700 });
      } else {
        txt(svg, cx, T - 19, parts[0], { "text-anchor": "middle", "font-size": 11.5, fill: col.ink, "font-weight": 700 });
      }
      txt(svg, cx, T - 5, `전체 ${attrOverall[j]}%`, {
        "text-anchor": "middle", "font-size": 10, fill: col.muted,
      });
    });

    attrProfile.forEach(([cat, n, rates], i) => {
      const y = T + i * ch;
      txt(svg, L - 10, y + ch / 2 + 4, cat, { "text-anchor": "end", "font-size": 11.5, fill: col.ink2 });
      const best = Math.max(...rates);
      rates.forEach((v, j) => {
        const x = L + j * cw;
        const fill = ramp(v);
        const cell = el("rect", {
          x: x + 1, y: y + 1, width: cw - 2, height: ch - 2, rx: 3, fill,
          stroke: v === best ? col.s3 : "transparent", "stroke-width": v === best ? 1.6 : 0,
        }, svg);
        txt(svg, x + cw / 2, y + ch / 2 + 4, v.toFixed(1), {
          "text-anchor": "middle", "font-size": 11,
          "font-weight": v >= 28 ? 800 : 600,
          fill: v >= 10 ? readable(fill) : col.ink2,
        });
        hover(cell, `${cat} — ${attrNames[j]}`, [
          ["언급률", `${v.toFixed(1)}%`, fill],
          ["전체 평균", `${attrOverall[j]}%`],
          ["리뷰 수", `${fmt(n, 0)}건`],
        ]);
      });
    });

    txt(svg, L + (W - L - R) / 2, H - 10, "카테고리별 리뷰에서 각 속성을 언급한 비율 · 코랄 테두리는 그 카테고리에서 가장 많이 언급된 속성", {
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

  /* --- 그림 9. 할인 반응 유형별 곡선 --- */
  let discMode = "qty";
  function drawDiscCurve() {
    const col = C(), W = 980, H = 360;
    const svg = makeSvg("chDiscCurve", W, H);
    if (!svg) return;
    const L = 56, R = 168, T = 24, B = 54;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const qty = discMode === "qty";
    const lo = qty ? -0.6 : -0.6, hi = qty ? 0.8 : 1.2;
    const xS = (i) => x0 + (i / (discBands.length - 1)) * (x1 - x0);
    const yS = (v) => y1 - ((v - lo) / (hi - lo)) * (y1 - y0);

    const ticks = qty ? [-0.6, -0.4, -0.2, 0, 0.2, 0.4, 0.6, 0.8]
                      : [-0.6, -0.3, 0, 0.3, 0.6, 0.9, 1.2];
    ticks.forEach((v) => {
      const y = yS(v);
      el("line", { x1: x0, y1: y, x2: x1, y2: y, stroke: v === 0 ? col.axis : col.grid, "stroke-width": v === 0 ? 1.5 : 1 }, svg);
      txt(svg, x0 - 9, y + 4, v.toFixed(1), { "text-anchor": "end", "font-size": 11, fill: col.muted });
    });
    discBands.forEach((b, i) => {
      txt(svg, xS(i), y1 + 19, b, { "text-anchor": "middle", "font-size": 11.5, fill: i === 0 ? col.ink2 : col.muted, "font-weight": i === 0 ? 750 : 400 });
    });
    txt(svg, x0 + 4, y0 + 12, "↑ 비할인 대비 더 팔린다", { "font-size": 11, fill: col.muted });

    discTypes.forEach(([name, ckey, q, r, cells, items], si) => {
      const vals = qty ? q : r;
      const color = col[ckey];
      const d = vals.map((v, i) => `${i === 0 ? "M" : "L"}${xS(i)},${yS(v)}`).join(" ");
      el("path", { d, fill: "none", stroke: color, "stroke-width": 2.4, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
      vals.forEach((v, i) => {
        const c = el("circle", { cx: xS(i), cy: yS(v), r: 4.4, fill: color, stroke: col.surface, "stroke-width": 2 }, svg);
        hover(c, `${name} · 할인 ${discBands[i]}`, [
          [qty ? "판매수량 ln 차이" : "판매금액 ln 차이", v.toFixed(2), color],
          ["비할인 대비", `${v >= 0 ? "+" : ""}${(100 * (Math.exp(v) - 1)).toFixed(0)}%`],
          ["소속", `셀 ${cells}개 · 상품 ${fmt(items, 0)}개`],
        ]);
      });
      const last = vals[vals.length - 1];
      txt(svg, x1 + 12, yS(last) + 4 + (si === 3 ? 12 : si === 2 ? -4 : 0), name, { "font-size": 12, fill: color, "font-weight": 750 });
    });
    txt(svg, (x0 + x1) / 2, H - 8, "할인율 구간 · 0% 구간을 기준선으로 둔 " + (qty ? "판매수량" : "판매금액") + " 로그 차이", {
      "text-anchor": "middle", "font-size": 11.5, fill: col.muted,
    });
  }

  /* --- 그림 10. 반사실 경로 --- */
  function drawCfPath() {
    const col = C(), W = 980, H = 380;
    const svg = makeSvg("chCfPath", W, H);
    if (!svg) return;
    const L = 52, R = 92, T = 26, B = 54;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const lo = 65, hi = 130;
    const xS = (i) => x0 + (i / (cfDays.length - 1)) * (x1 - x0);
    const yS = (v) => y1 - ((v - lo) / (hi - lo)) * (y1 - y0);

    [70, 80, 90, 100, 110, 120, 130].forEach((v) => {
      const y = yS(v);
      el("line", { x1: x0, y1: y, x2: x1, y2: y, stroke: v === 100 ? col.axis : col.grid, "stroke-width": v === 100 ? 1.5 : 1 }, svg);
      txt(svg, x0 - 9, y + 4, String(v), { "text-anchor": "end", "font-size": 11, fill: col.muted });
    });
    cfDays.forEach((d, i) => {
      txt(svg, xS(i), y1 + 19, d, { "text-anchor": "middle", "font-size": 11, fill: i === 7 ? col.ink2 : col.muted, "font-weight": i === 7 ? 750 : 400 });
    });
    el("line", { x1: xS(7), y1: y0, x2: xS(7), y2: y1, stroke: col.axis, "stroke-width": 1.5, "stroke-dasharray": "5 4" }, svg);
    txt(svg, xS(7) + 6, y0 + 12, "프로모션 시작", { "font-size": 11, fill: col.ink2, "font-weight": 700 });

    /* 실제와 최우수 반사실 사이의 간격 = 증분 효과 */
    const act = cfPost["실제(Actual)"], nn = cfPost["신경망(MLP)"];
    const gap = act.map((v, i) => `${i === 0 ? "M" : "L"}${xS(7 + i)},${yS(v)}`).join(" ")
      + " " + nn.map((v, i) => `L${xS(11 - i)},${yS(nn[4 - i])}`).join(" ") + " Z";
    el("path", { d: gap, fill: col.s1, opacity: .16 }, svg);

    /* 사전 구간은 모든 계열이 동일 */
    const pre = cfPre.map((v, i) => `${i === 0 ? "M" : "L"}${xS(i)},${yS(v)}`).join(" ");
    el("path", { d: pre, fill: "none", stroke: col.ink2, "stroke-width": 2.6, "stroke-linejoin": "round" }, svg);
    cfPre.forEach((v, i) => {
      const c = el("circle", { cx: xS(i), cy: yS(v), r: 4, fill: col.ink2, stroke: col.surface, "stroke-width": 2 }, svg);
      hover(c, `${cfDays[i]} · 프로모션 이전`, [["판매지수", v.toFixed(1), col.ink2]]);
    });

    cfStyles.forEach(([name, ckey, wdt, dash]) => {
      const vals = cfPost[name], color = col[ckey];
      const pts = [[6, cfPre[6]]].concat(vals.map((v, i) => [7 + i, v]));
      const d = pts.map(([i, v], k) => `${k === 0 ? "M" : "L"}${xS(i)},${yS(v)}`).join(" ");
      const at = { d, fill: "none", stroke: color, "stroke-width": wdt, "stroke-linejoin": "round", "stroke-linecap": "round" };
      if (dash) at["stroke-dasharray"] = dash;
      el("path", at, svg);
      vals.forEach((v, i) => {
        const c = el("circle", { cx: xS(7 + i), cy: yS(v), r: name === "실제(Actual)" ? 4.8 : 3.6, fill: color, stroke: col.surface, "stroke-width": 2 }, svg);
        hover(c, `${cfDays[7 + i]} · ${name}`, [
          ["판매지수", v.toFixed(1), color],
          ["실제와의 차이", name === "실제(Actual)" ? "—" : `${(act[i] - v >= 0 ? "+" : "")}${(act[i] - v).toFixed(1)}p`],
        ]);
      });
      if (name === "실제(Actual)") {
        txt(svg, x1 + 10, yS(vals[4]) + 4, "실제", { "font-size": 12, fill: color, "font-weight": 800 });
      }
    });
    txt(svg, (x0 + x1) / 2, H - 8, "프로모션 시작일 기준 관측 순서 · 사전 7관측 평균 = 100", {
      "text-anchor": "middle", "font-size": 11.5, fill: col.muted,
    });
  }

  /* --- 그림 13. 카테고리별 비긍정 리뷰 비중 --- */
  function drawRevCat() {
    const col = C(), rowH = 24, W = 980;
    const H = revCat.length * rowH + 76;
    const svg = makeSvg("chRevCat", W, H);
    if (!svg) return;
    const L = 118, R = 190, T = 34, B = 34;
    const x0 = L, x1 = W - R;
    const maxV = 11;
    const xS = (v) => x0 + (v / maxV) * (x1 - x0);

    [0, 2, 4, 6, 8, 10].forEach((v) => {
      el("line", { x1: xS(v), y1: T - 12, x2: xS(v), y2: H - B, stroke: col.grid, "stroke-width": 1 }, svg);
      txt(svg, xS(v), T - 18, `${v}%`, { "text-anchor": "middle", "font-size": 11, fill: col.muted });
    });

    const sorted = revCat.slice().sort((a, b) => (100 - a[1]) - (100 - b[1])).reverse();
    sorted.forEach((r, i) => {
      const [name, pos, mid, neg, n] = r;
      const y = T + i * rowH;
      txt(svg, L - 12, y + 15, name, { "text-anchor": "end", "font-size": 11.5, fill: col.ink2, "font-weight": 650 });
      const wMid = xS(mid) - x0, wNeg = xS(neg) - x0;
      const a = el("path", { d: barPath(x0, y + 4, wMid, rowH - 10, 3, "right"), fill: col.neutral }, svg);
      const b = el("path", { d: barPath(x0 + wMid, y + 4, wNeg, rowH - 10, 3, "right"), fill: col.s3 }, svg);
      const rows = [["3점", `${mid.toFixed(1)}%`, col.neutral], ["부정(2점 이하)", `${neg.toFixed(2)}%`, col.s3],
                    ["긍정(4점 이상)", `${pos.toFixed(1)}%`, col.s1], ["상품 수", `${n}개`]];
      hover(a, name, rows); hover(b, name, rows);
      txt(svg, x0 + wMid + wNeg + 10, y + 15, `긍정 ${pos.toFixed(1)}%`, { "font-size": 11.5, fill: col.ink2, "font-weight": 700 });
    });
    txt(svg, (x0 + x1) / 2, H - 8, "긍정(4점 이상)이 아닌 리뷰의 비중 — 회색 3점 · 코랄 부정(2점 이하)", {
      "text-anchor": "middle", "font-size": 11.5, fill: col.muted,
    });
  }

  /* --- 그림 14. 브랜드별 긍정 비중 산포 --- */
  function drawRevBrand() {
    const col = C(), W = 980, H = 400;
    const svg = makeSvg("chRevBrand", W, H);
    if (!svg) return;
    const L = 56, R = 24, T = 26, B = 56;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const xlo = 88, xhi = 99, ylo = 0, yhi = 8.5;
    const xS = (v) => x0 + ((v - xlo) / (xhi - xlo)) * (x1 - x0);
    const yS = (v) => y1 - ((v - ylo) / (yhi - ylo)) * (y1 - y0);

    [0, 2, 4, 6, 8].forEach((v) => {
      const y = yS(v);
      el("line", { x1: x0, y1: y, x2: x1, y2: y, stroke: col.grid, "stroke-width": 1 }, svg);
      txt(svg, x0 - 9, y + 4, v.toFixed(0), { "text-anchor": "end", "font-size": 11, fill: col.muted });
    });
    [88, 90, 92, 94, 96, 98].forEach((v) => {
      txt(svg, xS(v), y1 + 19, `${v}%`, { "text-anchor": "middle", "font-size": 11.5, fill: col.muted });
    });

    /* 추세선 — 단순 최소제곱 */
    let sx = 0, sy = 0, sxx = 0, sxy = 0;
    revBrand.forEach(([, p, sd]) => { sx += p; sy += sd; sxx += p * p; sxy += p * sd; });
    const n = revBrand.length, b1 = (n * sxy - sx * sy) / (n * sxx - sx * sx), b0 = (sy - b1 * sx) / n;
    el("line", { x1: xS(xlo), y1: yS(b0 + b1 * xlo), x2: xS(xhi), y2: yS(b0 + b1 * xhi),
                 stroke: col.s3, "stroke-width": 2, "stroke-dasharray": "6 5", opacity: .85 }, svg);

    revBrand.forEach(([name, pos, sd, items]) => {
      const r = Math.max(3, Math.min(9, Math.sqrt(items) * 1.25));
      const c = el("circle", { cx: xS(Math.max(xlo, Math.min(xhi, pos))), cy: yS(Math.min(yhi, sd)), r,
                               fill: col.s1, opacity: .42, stroke: col.s1, "stroke-width": 1 }, svg);
      hover(c, name, [["긍정 리뷰 비중", `${pos.toFixed(1)}%`, col.s1],
                      ["브랜드 내 상품 간 편차", `${sd.toFixed(2)}%p`],
                      ["상품 수", `${items}개`]]);
    });
    txt(svg, x1 - 6, y0 + 14, "ρ = −0.66 (p < 0.001)", { "text-anchor": "end", "font-size": 12, fill: col.s3, "font-weight": 750 });
    txt(svg, x0 + 4, y0 + 14, "↑ 상품마다 평이 들쭉날쭉", { "font-size": 11, fill: col.muted });
    txt(svg, (x0 + x1) / 2, H - 8, "가로: 브랜드 평균 긍정 리뷰 비중 · 세로: 그 브랜드 상품 간 표준편차 · 원 크기 = 상품 수", {
      "text-anchor": "middle", "font-size": 11.5, fill: col.muted,
    });
  }


  /* ==========================================================
     용어집 — 본문 형광펜에 마우스를 올리면 뜨는 메모
     data-gl 키로 연결한다. 새 용어는 여기에만 추가하면 된다.
     ========================================================== */
  const GLOSSARY = {
    "transition": ["전이 행렬(Transition Matrix)이란?",
      "오늘 어느 상태에 있던 대상이 내일 어느 상태로 옮겨가는지를 상태 × 상태 표에 비율로 적어 넣은 것이다. 여기서 '상태'는 순위 구간(1–10위, 11–25위 …)이고, 각 칸은 '오늘 이 구간에 있던 상품 중 내일 저 구간에 있는 비율'이다. 대각선이 높으면 고착, 낮으면 고회전 구조다."],
    "variance-decomp": ["분산 분해란?",
      "결과값이 흩어진 정도(분산)를 '어떤 변수가 얼마만큼 설명하는가'로 쪼개는 작업이다. 변수를 하나씩 넣어 설명된 분산(R²)이 얼마나 늘어나는지 보면 그 변수가 다른 변수에 없는 정보를 얼마나 더하는지 알 수 있다. 넣으나 빼나 R²가 같다면 그 변수의 고유 기여는 0이다."],
    "fe": ["개체 고정효과 모형이란?",
      "개체(여기서는 상품)마다 고유한 상수를 따로 두어, 기간 내내 변하지 않는 개체 특성을 통째로 걷어내는 회귀 모형이다. 브랜드력·가격대처럼 고정된 요인이 자동으로 상쇄되므로 남는 것은 '같은 상품이 시점에 따라 달라진 부분'뿐이다. 상품 간 비교가 아니라 상품 안 비교가 된다."],
    "shape-kmeans": ["형태 기반 군집화란?",
      "곡선을 진폭(크기)으로 나눠 모양만 남긴 뒤 비슷한 모양끼리 묶는 군집화다. '반응이 큰가 작은가'가 아니라 '어떻게 생겼는가'로 묶이므로, 반응 폭이 서로 다른 상품군도 곡선의 생김새가 같으면 한 유형으로 모인다."],
    "death-valley": ["데스밸리(Death Valley)형이란?",
      "얕은 할인 구간에서는 반응이 오히려 죽어 있다가, 일정 임계점을 넘어야 (+)로 살아나는 곡선 모양이다. 골짜기를 건너기 전까지는 할인 예산이 매출로 돌아오지 않는다는 뜻이라, 어중간한 상시 할인이 가장 비효율적인 구간이 된다."],
    "holdout": ["홀드아웃 검증이란?",
      "가진 데이터의 일부를 학습에서 빼두었다가, 학습이 끝난 모형으로 그 떼어 둔 몫을 예측시켜 성능을 재는 방법이다. 모형이 외운 답을 다시 채점하는 게 아니라 처음 보는 자료로 채점하므로 과적합된 모형이 걸러진다. 여기서는 통제군 상품의 4분의 1을 떼어 냈다."],
    "did": ["시장대조(이중차분, DiD)란?",
      "처치를 받은 쪽의 전후 변화에서, 처치를 받지 않은 대조군의 같은 기간 변화를 빼는 방법이다. 시장 전체가 오르내린 몫이 상쇄되므로 프로모션 고유의 몫만 남는다. 다만 개체 자신의 반등까지는 걷어내지 못한다."],
    "arima": ["ARIMA란?",
      "시계열을 자기 과거값(AR) · 차분(I) · 과거 예측오차(MA) 세 부품으로 설명하는 고전 예측 모형이다. ARIMA(1,0,0)은 '바로 직전 값 하나로 다음 값을 설명한다'는 뜻이다. 과거 관측이 적으면 차수 추정이 흔들려 예측이 불안정해진다."],
    "earth": ["EARTH(MARS 근사)란?",
      "변수 구간마다 기울기가 꺾이는 조각별 직선을 이어 붙여 비선형 관계를 잡는 회귀 기법이다(MARS = Multivariate Adaptive Regression Splines). 여기서는 스플라인 기저를 선형회귀에 넣어 같은 성질을 구현했다. 직선 하나로는 못 잡는 굴곡을 잡으면서도 신경망보다 형태를 읽기 쉽다."],
    "mlp": ["신경망(MLP)이란?",
      "입력을 여러 층의 은닉 노드에 통과시키며 비선형 조합을 학습하는 모형이다(MLP = Multi-Layer Perceptron, 다층 퍼셉트론). 관계의 모양을 미리 정하지 않아 유연하지만 계수를 해석할 수 없어, 여기서는 '왜'가 아니라 '얼마나 정확히 맞히는가'에만 쓴다."],
    "binary-retention": ["이항 잔류 모형이란?",
      "결과를 '남았다 / 이탈했다' 두 값으로만 두고 잔류 확률을 추정하는 모형이다. 순위 숫자 자체가 아니라 100위 안에 살아남았는지만 보므로, 하루하루 순위가 몇 계단씩 흔들리는 잡음에 휘둘리지 않는다."],
    "clpm": ["교차지연 패널 회귀모형이란?",
      "두 변수를 서로의 과거값으로 예측해 어느 쪽이 앞서는지 가르는 모형이다. '어제 리뷰 → 오늘 순위'와 '어제 순위 → 오늘 리뷰' 두 방향을 같은 자료로 함께 추정한 뒤, 신호가 큰 쪽을 선행 관계로 읽는다."],
  };

  /* 형광펜 용어에 메모를 붙인다 — 마우스 · 키보드 · 터치 모두 지원 */
  function initGlossary() {
    let open = null;
    const show = (node) => {
      const def = GLOSSARY[node.dataset.gl];
      if (!def || !tip) return;
      tip.innerHTML = "";
      tip.className = "tip-gl";
      const q = document.createElement("div");
      q.className = "tp-q";
      q.textContent = "Q. " + def[0];
      const a = document.createElement("div");
      a.className = "tp-a";
      a.textContent = def[1];
      tip.appendChild(q);
      tip.appendChild(a);
      tip.style.display = "block";
      /* 커서를 따라다니면 읽기 어려우므로 용어 아래에 고정한다 */
      const r = node.getBoundingClientRect(), t = tip.getBoundingClientRect();
      let x = r.left, y = r.bottom + 8;
      if (x + t.width > innerWidth - 10) x = Math.max(10, innerWidth - t.width - 10);
      if (y + t.height > innerHeight - 10) y = Math.max(10, r.top - t.height - 8);
      tip.style.left = x + "px";
      tip.style.top = y + "px";
      open = node;
    };
    const hide = () => {
      if (!tip) return;
      tip.style.display = "none";
      tip.className = "";
      open = null;
    };
    document.querySelectorAll("[data-gl]").forEach((node) => {
      node.classList.add("gl");
      node.tabIndex = 0;
      node.setAttribute("role", "button");
      const def = GLOSSARY[node.dataset.gl];
      if (def) node.setAttribute("aria-label", node.textContent + " — 용어 설명 보기");
      node.addEventListener("mouseenter", () => show(node));
      node.addEventListener("mouseleave", hide);
      node.addEventListener("focus", () => show(node));
      node.addEventListener("blur", hide);
      /* 클릭은 열기 전용 — 토글로 두면 데스크톱에서 mouseenter 로 뜬 메모가
         곧바로 닫힌다. 닫기는 마우스를 떼거나 바깥을 누를 때 처리한다. */
      node.addEventListener("click", (e) => {
        e.preventDefault();
        show(node);
      });
    });
    /* 터치에서 바깥을 누르면 닫힌다 */
    document.addEventListener("click", (e) => {
      if (open && !e.target.closest("[data-gl]")) hide();
    });
    addEventListener("scroll", () => { if (open) hide(); }, { passive: true });
    addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
  }

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
    drawCloud();
    drawAttr();
    drawDiscCurve();
    drawCfPath();
    drawRevCat();
    drawRevBrand();

    const col = C();
    legend("lgEvent", [["쿠폰 부착 (937건)", col.s1, "line"], ["세일 부착 (148건)", col.s3, "line"]]);
    legend("lgThumb", [["판매 요인 통제 전", col.neutral], ["판매 요인 통제 후", col.s1]]);
    legend("lgVariance", [["리뷰 총량", col.neutral], ["리뷰 증가 속도 포함", col.s1]]);
    legend("lgElasticity", [["리뷰 증가 속도 (판매량 대리)", col.s1], ["실제 판매가격", col.s2]]);
    legend("lgPromo", [["순위 개선", col.s1], ["순위 악화", col.s3]]);
    legend("lgDiscCurve", discTypes.map(([n, k]) => [n, col[k], "line"]));
    legend("lgCfPath", cfStyles.map(([n, k]) => [n, col[k], "line"]));
    legend("lgRevCat", [["3점", col.neutral], ["부정 (2점 이하)", col.s3]]);
  }

  function initControls() {
    document.querySelectorAll("#segDisc button").forEach((b) => {
      b.addEventListener("click", () => {
        document.querySelectorAll("#segDisc button").forEach((x) => x.classList.toggle("on", x === b));
        discMode = b.dataset.disc;
        drawDiscCurve();
        const note = document.getElementById("discNote");
        if (note) note.textContent = discMode === "qty"
          ? "판매수량 기준 — 가속형만 할인율이 오를수록 반응이 커진다. 데스밸리형은 20%를 넘겨야 (+)로 돌아선다."
          : "판매금액 기준 — 할인으로 단가가 깎이는데도 가속형·데스밸리형은 금액이 함께 늘어난다. 무반응·역행형은 금액으로도 0 부근이다.";
      });
    });
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

  /* 목차 — 분석 결과 하위 절 펼치기/접기 */
  function initTocToggle() {
    const btn = document.getElementById("tocToggle");
    const panel = document.getElementById("tocSub");
    if (!btn || !panel) return;
    const label = btn.querySelector(".tt-text");
    const set = (open) => {
      panel.hidden = !open;
      btn.setAttribute("aria-expanded", String(open));
      if (label) label.textContent = open ? "접기" : "13개 절 펼치기";
    };
    btn.addEventListener("click", () => set(panel.hidden));
    /* 하위 절 링크로 들어온 경우 펼친 상태로 시작한다 */
    if (/^#r5\d+$/.test(location.hash)) set(true);
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
    initTocToggle();
    initGlossary();
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
