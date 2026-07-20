# 올리브영 데이터 수집

올리브영 랭킹(전체 + 20개 카테고리)과 상품별 리뷰 데이터를 **매일 KST 오전 10시**에
로컬 PC 에서 자동 수집해 CSV 로 저장하고, GitHub 리포에 push 하는 파이프라인.

> ⚠️ **왜 로컬 실행인가**: 올리브영은 Cloudflare 봇 차단을 사용해 GitHub Actions 등
> 데이터센터 IP 를 차단한다. 가정용 IP 를 쓰는 로컬 PC 에서는 일반 요청으로 정상 수집된다.

## 빠른 시작 (로컬 PC)

```bash
git clone <repo-url> && cd oliveyoung
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m scraper.probe_json                          # 접속·API 동작 확인(선택)
python -m scraper.main --max-products 10              # 소규모 테스트
python -m scraper.main --deadline-minutes 320         # 전체 수집 1회
```

> `truststore` 가 Windows 인증서 저장소를 사용하므로, 백신/프록시의 HTTPS 검사가 있는
> 환경에서도 `CERTIFICATE_VERIFY_FAILED` 없이 동작한다.

## 매일 자동 실행 등록

### Windows (작업 스케줄러)
1. 작업 스케줄러 → 작업 만들기 → "가장 높은 권한으로 실행" 체크
2. 트리거: 매일 오전 10:00
3. 동작: 프로그램 시작
   - 프로그램: `powershell.exe`
   - 인수: `-ExecutionPolicy Bypass -File C:\path\to\oliveyoung\run_local.ps1`

### macOS / Linux (cron)
`crontab -e` (PC 시간대가 KST 가정, 절대경로):
```
0 10 * * * /path/to/oliveyoung/run_local.sh
```

`run_local.*` 은 수집 → 데이터 커밋 → push 까지 하고, 데드라인으로 중단되면 완료까지
이어서 실행한다. 로그는 `cron.log`. **PC 가 켜져 있어야** 실행된다.

## 수집 데이터

### `data/YYYY-MM-DD/ranking.csv`
수집일자, 카테고리, 순위, 브랜드, 상품명, 상품페이지링크, 정가, 혜택가, 할인율,
**리뷰수, 리뷰별점**, 별점5~1비율, 세일/쿠폰/증정/오늘드림, 상품번호, 카테고리ID

### `data/YYYY-MM-DD/reviews.csv` — 그날 새로 수집된 리뷰(증분)
수집일자, 상품번호, 리뷰ID, 작성일, 별점, **체험단여부**, 리뷰타입, 옵션,
피부타입, 피부톤, 피부고민, 도움수, 유용점수, 포토여부, 재구매, 닉네임, 리뷰본문

- **체험단여부**: 리뷰 `reviewType` 이 `NORMAL` 이 아니면 1 (원문 리뷰타입도 함께 저장)
- 랭킹에 오른 모든 상품(중복 제거, ~1,500개)이 대상

### `data/backfill/top100_reviews.csv` — 전체 랭킹 TOP100 과거 리뷰 백필(1회성)
```bash
python -m scraper.backfill        # 재개 가능, 중단해도 이어서 실행
```

### `data/YYYY-MM-DD/errors.csv` — 해당 일자 수집 실패 기록

CSV 는 `utf-8-sig` (엑셀에서 바로 열림, pandas: `pd.read_csv(path)`).

## 수집 API (참고)
- 랭킹: `GET store/main/getBestList.do` (서버 렌더링 HTML 파싱)
- 리뷰수·별점: `GET m.oliveyoung.co.kr/review/api/v2/reviews/{goodsNo}/stats`
- 리뷰 목록: `POST m.oliveyoung.co.kr/review/api/v2/reviews/cursor` (커서 페이지네이션)

## 장기 실행 내구성
- 상품 단위 체크포인트(`state/run_progress.json`) — 중단 후 재실행 시 이어서 진행
- 리뷰 커서(`state/review_cursor.json`) — reviewId 로 이미 수집한 리뷰 재수집 안 함
- 수집 즉시 CSV append + atomic 저장 — 중단돼도 데이터·파일 무결성 보존
- 데드라인(기본 320분) 도달 시 체크포인트 저장 후 종료 → `run_local` 이 이어서 실행
- 요청 간격 제한(~3req/s)·지수 백오프·연속 실패 시 쿨다운

## 코드 구조
```
scraper/
  config.py        카테고리 ID, 엔드포인트, 속도/재시도 상수
  http_client.py   세션·재시도·쿨다운 (GET/POST)
  ranking.py       랭킹 21개 리스트 수집·파싱
  reviews.py       리뷰수/별점(stats) + 리뷰 목록(cursor) 증분 수집
  backfill.py      TOP100 과거 리뷰 백필 (재개 가능)
  main.py          일일 수집 오케스트레이터
  probe_json.py    API 동작 진단(선택)
run_local.sh / run_local.ps1   cron/작업스케줄러용 실행 스크립트
```

## 주의
- 과도한 요청은 차단·법적 위험이 있으므로 하루 1회, 정중한 속도(~3req/s)를 유지한다.
- 사이트 구조가 바뀌면 파서 조정이 필요할 수 있다.
