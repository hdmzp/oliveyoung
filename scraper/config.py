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
MIN_REQUEST_INTERVAL = 0.35
REQUEST_JITTER = 0.25
REQUEST_TIMEOUT = (10, 30)  # (connect, read)

# 재시도/차단 완화
MAX_RETRIES = 4
BACKOFF_BASE = 2.0
CONSECUTIVE_FAIL_LIMIT = 8      # 연속 실패 시 장시간 휴식 진입
COOLDOWN_SECONDS = 180          # 휴식 시간
MAX_COOLDOWN_ROUNDS = 3         # 휴식 후에도 계속 실패하면 해당 단계 포기

# 증분 리뷰 수집 한도 (하루 상품당 페이지 상한 — 폭주 방지)
MAX_REVIEW_PAGES_PER_DAY = 30
SEEN_IDS_KEEP = 120             # 상품당 중복 판정용으로 기억할 리뷰 ID 수

# 체험단 판별 키워드 (뱃지/문구에 포함 시 True)
TRIAL_KEYWORDS = ("체험단", "무상", "제공받아", "제공 받아", "협찬")

STATE_DIR = "state"
DATA_DIR = "data"
