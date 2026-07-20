# 올리브영 데이터 수집

올리브영 랭킹(전체 + 20개 카테고리)과 상품별 리뷰 데이터를 **매일 KST 오전 10시**에
로컬 PC 에서 자동 수집해 CSV 로 저장하고, GitHub 리포에 push 하는 파이프라인.

> ⚠️ **왜 로컬 실행인가**: 올리브영은 Cloudflare 봇 차단을 사용해 GitHub Actions 등
> 데이터센터 IP 를 "잠시만 기다려 주세요" 챌린지(403)로 막는다. 가정용 IP 를 쓰는
> 로컬 PC + 브라우저 쿠키 부트스트랩으로 이 문제를 피한다.

## 빠른 시작 (로컬 PC)

```bash
git clone <repo-url> && cd oliveyoung
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium                 # Cloudflare 쿠키 부트스트랩용

# 접속/파싱이 되는지 먼저 진단 (권장)
python -m scraper.probe --cf-bootstrap

# 소규모 실측 테스트 (상위 10개 상품만)
python -m scraper.main --max-products 10 --cf-bootstrap

# 전체 수집 1회
python -m scraper.main --deadline-minutes 320 --cf-bootstrap
```

`--cf-bootstrap` 은 시작 시 Chromium 으로 사이트를 한 번 방문해 Cloudflare 검증 쿠키를
확보하고 이후 빠른 HTTP 요청에 재사용한다. 수집 중 403 이 나면 자동으로 다시 확보한다.

## 매일 자동 실행 등록

### macOS / Linux (cron)
`crontab -e` 에 추가 (PC 시간대가 KST 라고 가정, 절대경로 사용):
```
0 10 * * * /Users/you/oliveyoung/run_local.sh
```
`run_local.sh` 는 수집 → 데이터 커밋 → push 까지 하고, 데드라인으로 중단되면 완료까지
이어서 실행한다. 로그는 `cron.log` 에 쌓인다. PC 가 켜져 있어야 실행된다(절전/종료 시
미실행 — macOS 는 `launchd` 로 절전 중에도 깨우도록 설정 가능).

### Windows (작업 스케줄러)
1. 작업 스케줄러 → 작업 만들기
2. 트리거: 매일 오전 10:00
3. 동작: 프로그램 시작
   - 프로그램: `powershell.exe`
   - 인수: `-ExecutionPolicy Bypass -File C:\path\to\oliveyoung\run_local.ps1`

## 수집 데이터

### `data/YYYY-MM-DD/ranking.csv`
| 컬럼 | 설명 |
|---|---|
| 수집일자 | KST 기준 수집 날짜 |
| 카테고리 / 카테고리ID | 전체(ALL) 또는 스킨케어~취미/팬시 |
| 순위 | 카테고리 내 랭킹 (1~100) |
| 브랜드 / 상품명 / 상품번호 / 상품페이지링크 | 상품 식별 정보 |
| 정가 / 혜택가 / 할인율 | 가격 (할인 없으면 정가=혜택가) |
| 리뷰수 / 리뷰별점 | 상품 상세 기준 총 리뷰수·평균 별점 |
| 세일 / 쿠폰 / 증정 / 오늘드림 | 프로모션 뱃지 (0/1) |

### `data/YYYY-MM-DD/reviews.csv` — 그날 새로 달린 리뷰(증분)
수집일자, 상품번호, 리뷰ID, 작성일, 별점, **체험단여부**(0/1), 뱃지, 피부타입, 옵션, 리뷰본문, 도움수

- 체험단여부: 리뷰 뱃지/문구에 "체험단·무상·제공받아·협찬" 포함 시 1
- 같은 날 랭킹에 오른 모든 상품(중복 제거, ~1,500개)이 대상

### `data/backfill/top100_reviews.csv` — 전체 랭킹 TOP100 과거 리뷰 백필(1회성)
```bash
python -m scraper.backfill --cf-bootstrap        # 재개 가능, 중단해도 이어서 실행
```

### `data/YYYY-MM-DD/errors.csv` — 해당 일자 수집 실패 기록

CSV 는 `utf-8-sig` 인코딩 (엑셀에서 바로 열림, pandas: `pd.read_csv(path)`).

## 장기 실행 내구성
- 상품 단위 체크포인트(`state/run_progress.json`) — 중단 후 재실행 시 이어서 진행
- 리뷰 커서(`state/review_cursor.json`) — 이미 수집한 리뷰는 다시 수집하지 않음
- 수집 즉시 CSV append + atomic 저장 — 중단돼도 데이터·파일 무결성 보존
- 데드라인(기본 320분) 도달 시 체크포인트 저장 후 종료 → `run_local` 이 이어서 실행
- 요청 간격 제한(~3req/s)·지수 백오프·연속 실패 시 쿨다운·Cloudflare 쿠키 자동 갱신

## 코드 구조
```
scraper/
  config.py        카테고리 ID 맵, 엔드포인트, 속도/재시도 상수
  http_client.py   세션·재시도·쿨다운·Cloudflare 쿠키 부트스트랩
  cf_bootstrap.py  브라우저로 Cloudflare 검증 쿠키 확보
  ranking.py       랭킹 21개 리스트 수집·파싱
  reviews.py       상품별 리뷰수/별점 + 신규 리뷰 증분 수집
  backfill.py      TOP100 과거 리뷰 백필 (재개 가능)
  main.py          일일 수집 오케스트레이터
  probe.py         엔드포인트 진단
run_local.sh / run_local.ps1   cron/작업스케줄러용 실행 스크립트
```

## 문제 해결
- **`CERTIFICATE_VERIFY_FAILED` / self-signed certificate**: 백신·프록시의 HTTPS 검사
  때문. `truststore`(requirements 에 포함)가 자동으로 Windows 인증서 저장소를 사용해
  해결한다. `pip install -r requirements.txt` 를 다시 실행하면 적용된다.
- **`Executable doesn't exist ... chrome.exe`**: 브라우저 미설치.
  가상환경을 켠 상태에서 `python -m playwright install chromium` 실행.

## 주의
- 과도한 요청은 차단·법적 위험이 있으므로 하루 1회, 정중한 속도(~3req/s)를 유지한다.
- 사이트 마크업이 바뀌면 파서 조정이 필요할 수 있다(파싱 0건이면 오류로 종료됨).
