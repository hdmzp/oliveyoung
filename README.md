# 올리브영 데이터 수집

올리브영 랭킹(전체 + 20개 카테고리)과 상품별 리뷰 데이터를 **매일 KST 오전 10시**에
GitHub Actions 로 자동 수집해 CSV 로 저장하는 파이프라인.

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

### `data/YYYY-MM-DD/errors.csv` — 해당 일자 수집 실패 기록

CSV 는 `utf-8-sig` 인코딩 (엑셀에서 바로 열림, pandas: `pd.read_csv(path)`).

## 워크플로우

| 워크플로우 | 트리거 | 역할 |
|---|---|---|
| `collect.yml` | 매일 01:00 UTC(10:00 KST) + 수동 | 일일 랭킹·리뷰 수집 → 커밋 |
| `backfill.yml` | 수동 | TOP100 과거 리뷰 전량 백필 (재개 가능) |
| `probe.yml` | 수동 | 엔드포인트 상태 점검 + Playwright 리뷰 API 캡처 |

⚠️ cron 스케줄은 **기본 브랜치(main)** 에 워크플로우가 있어야 동작한다.

## 장기 실행 내구성
- 상품 단위 체크포인트(`state/run_progress.json`) — 중단 후 재실행 시 이어서 진행
- 리뷰 커서(`state/review_cursor.json`) — 이미 수집한 리뷰는 다시 수집하지 않음
- 수집 즉시 CSV append + atomic 저장 — 중단돼도 데이터·파일 무결성 보존
- 데드라인(기본 320분) 도달 시 체크포인트 저장 후 정상 종료 → 워크플로우가 자신을 재실행
- 요청 간격 제한(~3req/s)·지수 백오프·연속 실패 시 쿨다운

## 로컬 실행
```bash
pip install -r requirements.txt
python -m scraper.main --max-products 10          # 스모크 테스트
python -m scraper.main --deadline-minutes 320     # 전체 수집
python -m scraper.backfill                        # TOP100 백필
python -m scraper.probe --goods-no A000000247086  # 엔드포인트 점검
```
