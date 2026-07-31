# 올리브영 데이터 수집

올리브영 랭킹(전체 TOP100)과 상품별 리뷰 데이터를 **매일 로컬 PC에서 자동 수집**해
CSV로 저장하는 파이프라인. 리뷰수·평균별점은 물론 리뷰 본문·**체험단 여부**까지 모읍니다.

> ⚠️ **왜 로컬 PC인가**: 올리브영은 Cloudflare 봇 차단을 사용해 GitHub Actions 등
> 데이터센터 IP를 막습니다. 가정용 IP를 쓰는 로컬 PC에서 `curl_cffi`(크롬 TLS 위장)로
> 접속합니다. **GitHub Actions로는 동작하지 않습니다.**

---

## 1. 설치 (처음 한 번)

```powershell
# 폴더는 OneDrive 밖에 두세요 (예: C:\oliveyoung) — OneDrive는 파일 잠금·동기화 충돌 유발
cd C:\oliveyoung
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

`requirements.txt` 핵심 패키지:
- `curl_cffi` — 크롬 TLS 지문 위장 (Cloudflare 우회, **필수**)
- `truststore` — 백신/프록시 HTTPS 검사 환경에서 인증서 문제 해결
- `playwright` — 403 시 Edge로 검증 쿠키 확보(폴백). 브라우저 다운로드 불필요(설치된 Edge 사용)

---

## 2. 실행 방법 (명령어 3가지)

| 명령 | 하는 일 | 언제 |
|---|---|---|
| `python -m scraper.main --overall-only` | **매일 수집**: 전체 TOP100 랭킹 + 리뷰수·별점 + 신규 리뷰 | 매일 (자동) |
| `python -m scraper.backfill` | **백필**: TOP100 상품의 과거 리뷰 전체 | 1회 (수동, 밤에) |
| `python -m scraper.probe_json` | **진단**: 접속·API 정상 여부 확인 | 문제 있을 때 |

먼저 소규모로 테스트해보길 권장:
```powershell
python -m scraper.main --overall-only --max-products 5
```

---

## 3. 매일 자동 실행 (Windows 작업 스케줄러)

1. 시작 메뉴 → **작업 스케줄러** → **작업 만들기**
2. **일반**: 이름 `올리브영수집`
3. **트리거**: 매일 오전 10:00
4. **동작**: 프로그램 시작
   - 프로그램: `powershell.exe`
   - 인수: `-ExecutionPolicy Bypass -File "C:\oliveyoung\run_local.ps1"`
   - 시작 위치: `C:\oliveyoung`
5. **조건**: (노트북) "AC 전원일 때만" 체크 해제

`run_local.ps1`이 수집 → (git 저장소면) 커밋·푸시까지 하고, 데드라인으로 중단되면
완료까지 이어서 실행합니다. 로그는 `cron.log`. **PC가 켜져 있어야** 실행됩니다.

> macOS/Linux는 `run_local.sh` + crontab: `0 10 * * * /path/oliveyoung/run_local.sh`

---

## 4. 코드 구조 — 어떤 파일이 언제 도는가

```
C:\oliveyoung\
├── run_local.ps1            PowerShell 실행 스크립트 (작업 스케줄러가 이걸 실행)
├── run_local.sh             (macOS/Linux용)
├── requirements.txt
├── scraper\                 ← 파이썬 코드 (핵심)
│   ├── main.py              매일 수집 지휘자 (시작점)
│   ├── backfill.py          과거 리뷰 백필 (별도 실행)
│   ├── config.py            설정값 (카테고리·엔드포인트·속도)
│   ├── http_client.py       요청 전송 (curl_cffi TLS 위장·재시도·속도제한)
│   ├── ranking.py           랭킹 페이지 수집·파싱
│   ├── reviews.py           리뷰수/별점(stats) + 리뷰목록(cursor) 수집
│   ├── cf_bootstrap.py      403 시 Edge로 검증 쿠키 확보(폴백)
│   ├── util.py              CSV 저장·시간·데드라인·파일잠금 재시도
│   ├── probe_json.py        진단용
│   └── __init__.py          임포트 시 truststore 자동 적용
└── data\                    수집 결과 CSV
```

**핵심: `scraper` 폴더가 한 세트로 함께 작동합니다.** 시작 파일 하나만 실행하면
나머지 필요한 파일을 자동으로 불러옵니다.

- **매일 수집(`scraper.main`)** 이 실제로 사용하는 파일:
  `main → config, http_client, ranking, reviews, util (+ 403 시 cf_bootstrap)`
- **백필(`scraper.backfill`)** 이 사용하는 파일:
  `backfill → config, http_client, reviews, util`
- `backfill.py`·`probe_json.py`는 매일 수집(#1)에선 **실행되지 않습니다** (각자 따로 실행).

즉 작업 스케줄러에는 `scraper.main`(= run_local.ps1) 하나만 걸면 되고,
그게 나머지를 다 불러와 돌립니다.

---

## 5. 수집 데이터 (CSV, `utf-8-sig` → 엑셀에서 바로 열림)

### `data/YYYY-MM-DD_ranking.csv` — 매일 랭킹 스냅샷
수집일자, 카테고리, 순위, 브랜드, 상품명, 상품페이지링크, **대표이미지URL**,
정가, 혜택가, 할인율, **리뷰수, 리뷰별점**, 별점5~1비율, 세일/쿠폰/증정/오늘드림,
상품번호, 카테고리ID

### `data/images/` — 대표이미지 원본(중복 제거 아카이브)
- 랭킹 각 상품의 대표이미지를 **URL 기준으로 한 번만** 다운로드(파일명 = URL의 md5 앞 16자).
  같은 이미지는 매일 다시 안 받고, 프로모 이미지가 바뀌면(=URL 변경) 새 파일로 보존됨.
- 뷰어(index.html)는 저장 파일이 아니라 **`대표이미지URL`을 직접 표시**하므로, 이 폴더는 순수 분석용 아카이브.
- 특정 CSV 행의 이미지 파일 찾기: `hashlib.md5(url.encode()).hexdigest()[:16]` → `data/images/<그값>.<확장자>`
- 다운로드 생략: `python -m scraper.main --overall-only --no-images` (URL은 그래도 CSV에 남음)

### `data/YYYY-MM-DD_reviews.csv` — 그날 새로 수집된 리뷰
수집일자, 상품번호, 리뷰ID, 작성일, 별점, **체험단여부**, 리뷰타입, 옵션,
피부타입, 피부톤, 피부고민, 도움수, 유용점수, 포토여부, 재구매, 닉네임, 리뷰본문

- **체험단여부(0/1)**: 본문에 "체험단·무상 제공·제공받아·협찬·서포터즈" 등 **법적 공시
  문구**가 있으면 1. (원본 `리뷰타입`(NORMAL/OFFLINE/GIFT 등)도 함께 저장 — 이는 구매채널
  구분이라 체험단과 무관. 추후 재분류 시 사용)
- 이미 수집한 CSV의 체험단여부를 최신 규칙으로 다시 계산: `python -m scraper.fix_trial`

### `data/backfill/top100_reviews.csv` — TOP100 과거 리뷰 전체(백필, 1회성)

### `data/YYYY-MM-DD_errors.csv` — 해당 일자 수집 실패 기록

분석 예시(pandas):
```python
import pandas as pd, glob
rank = pd.concat([pd.read_csv(f) for f in glob.glob("data/*_ranking.csv")])
rev = pd.concat([pd.read_csv("data/backfill/top100_reviews.csv"),
                 *[pd.read_csv(f) for f in glob.glob("data/*_reviews.csv")]]).drop_duplicates("리뷰ID")
```

---

## 6. 수집 API (참고)

- 랭킹: `GET www.oliveyoung.co.kr/store/main/getBestList.do` (서버렌더링 HTML)
- 리뷰수·별점: `GET m.oliveyoung.co.kr/review/api/v2/reviews/{goodsNo}/stats`
- 리뷰 목록: `POST m.oliveyoung.co.kr/review/api/v2/reviews/cursor` (커서 페이지네이션)

---

## 7. 장기 실행 내구성 & 매너

- **체크포인트/재개**: 상품·카테고리·리뷰 단위로 진행상황을 저장 → 중단(Ctrl+C·데드라인)
  후 다시 실행하면 **이어서** 진행 (백필도 동일)
- **즉시 저장**: 수집 즉시 CSV에 기록(fsync) → 중단돼도 데이터 보존
- **속도 제한 준수**: 랭킹(www)은 넉넉히, 리뷰 API(m)는 완화된 간격. 429(Too Many
  Requests) 시 지정된 시간만큼 쉬었다 재시도. 하루 1회, 정중한 속도 유지.
- **파일 잠금 대응**: OneDrive/백신이 파일을 잠깐 잠가도 재시도로 견딤(그래도 OneDrive
  밖 폴더 권장).

---

## 8. 문제 해결

| 증상 | 원인 / 해결 |
|---|---|
| `403 Forbidden` (계속) | `pip install curl_cffi` 확인. 그래도면 Edge 쿠키 폴백이 시도됨 |
| `429 rate limited` | 정상 — 지정 시간 쉬었다 재시도. 반복되면 잠시 후 재실행 |
| `CERTIFICATE_VERIFY_FAILED` | 백신 HTTPS 검사. `pip install -r requirements.txt`(truststore) 재실행 |
| `PermissionError [WinError 5]` | OneDrive 폴더 잠금 → 폴더를 OneDrive 밖으로 이동 |
| `backfill already completed` | `--fresh` 옵션 + `data/backfill/top100_reviews.csv` 삭제 후 재실행 |
