"""수집 대상/엔드포인트/동작 상수 정의."""

BASE = "https://www.oliveyoung.co.kr"

# 판매랭킹 (전체 TOP100). fltDispCatNo 로 카테고리 필터.
BEST_LIST_URL = f"{BASE}/store/main/getBestList.do"
BEST_DISP_CAT_NO = "900000100100001"

GOODS_DETAIL_URL = f"{BASE}/store/goods/getGoodsDetail.do"

# 랭킹 탭 카테고리 (랭킹 페이지 HTML에서 추출). ""(빈값) = 전체
CATEGORIES = {
    "": "전체",
    "10000010001": "스킨케어",
    "10000010009": "마스크팩",
    "10000010010": "클렌징",
    "10000010011": "선케어",
    "10000010002": "메이크업",
    "10000010012": "네일",
    "10000010006": "뷰티소품",
    "10000010008": "더모 코스메틱",
    "10000010007": "맨즈에딧",
    "10000010005": "향수/디퓨저",
    "10000010004": "헤어케어",
    "10000010003": "바디케어",
    "10000020001": "건강식품",
    "10000020002": "푸드",
    "10000020003": "구강용품",
    "10000020005": "헬스/건강용품",
    "10000020004": "위생용품",
    "10000030007": "패션",
    "10000030005": "홈리빙/가전",
    "10000030006": "취미/팬시",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 정중한 수집 속도: 요청 간 최소 간격(초) + 지터
# 올리브영은 짧은 시간 많은 요청 시 429(Too Many Requests)를 준다 → 여유있게.
MIN_REQUEST_INTERVAL = 1.1
REQUEST_JITTER = 0.5
REQUEST_TIMEOUT = (10, 30)  # (connect, read)

# 호스트별 최소 간격(초). 랭킹(www)은 rate limit 이 엄격, 리뷰 API(m)는 관대.
HOST_INTERVALS = {
    "www.oliveyoung.co.kr": 8.0,   # 랭킹 getBestList — 버스트 제한 회피(넉넉히)
    "m.oliveyoung.co.kr": 0.5,     # 리뷰 stats/cursor — 비교적 여유
}
# 랭킹 카테고리가 연속으로 이만큼 실패하면 rate limit 으로 보고 중단(재실행 시 이어서)
RANKING_ABORT_AFTER_FAILS = 2

# 재시도/차단 완화
MAX_RETRIES = 3          # 너무 많이 재시도하면 오히려 rate limit 을 연장시킴
BACKOFF_BASE = 2.0
# 429(rate limit) 전용 대기: attempt 마다 이 값 × (n+1) 초 (Retry-After 헤더 우선)
RATE_LIMIT_BASE = 15.0
CONSECUTIVE_FAIL_LIMIT = 10     # 연속 실패 시 장시간 휴식 진입
COOLDOWN_SECONDS = 180          # 휴식 시간
MAX_COOLDOWN_ROUNDS = 3         # 휴식 후에도 계속 실패하면 해당 단계 포기

# 증분 리뷰 수집 한도 (하루 상품당 페이지 상한 — 폭주 방지)
MAX_REVIEW_PAGES_PER_DAY = 30
SEEN_IDS_KEEP = 120             # 상품당 중복 판정용으로 기억할 리뷰 ID 수

# ---- 리뷰 API (신 리뷰 마이크로서비스, m.oliveyoung.co.kr) ----
REVIEW_API_HOST = "https://m.oliveyoung.co.kr"
REVIEW_STATS_PATH = "/review/api/v2/reviews/{goods_no}/stats"       # 리뷰수·평균별점·분포
REVIEW_CURSOR_PATH = "/review/api/v2/reviews/cursor"               # 리뷰 목록(POST)
REVIEW_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.oliveyoung.co.kr",
    "Referer": "https://www.oliveyoung.co.kr/",
    "Content-Type": "application/json",
}
REVIEW_PAGE_SIZE = 20             # cursor 한 페이지 리뷰 수
FIRST_RUN_MAX_PAGES = 3           # 최초 실행 시 상품당 최대 페이지(초기 부하 억제)

# 체험단 판별: 리뷰 reviewType 이 "NORMAL" 이 아니면 체험단/기획 리뷰로 본다.
# (원문 reviewType 값도 항상 저장하므로 추후 정밀 분류 가능)
NORMAL_REVIEW_TYPE = "NORMAL"
TRIAL_KEYWORDS = ("체험단", "무상", "제공받아", "제공 받아", "협찬")

STATE_DIR = "state"
DATA_DIR = "data"
