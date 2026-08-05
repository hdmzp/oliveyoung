#!/usr/bin/env bash
# 올리브영 일일 수집 — 로컬 실행 (macOS / Linux)
# cron 에서 매일 KST 10:00 에 호출한다. PC 가 KST 라면 crontab: 0 10 * * *
set -uo pipefail

cd "$(dirname "$0")" || exit 1
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
LOG="cron.log"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') collect start (branch=$BRANCH) =====" >>"$LOG"

# 가상환경이 있으면 사용
if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# 수집 (데드라인 320분)
python -m scraper.main --review-text-overall-only --deadline-minutes 320 >>"$LOG" 2>&1
STATUS=$?
echo "collect exit status: $STATUS" >>"$LOG"

# 데이터 커밋 & 푸시 (실패해도 다음 실행에서 재시도)
git add data state 2>>"$LOG"
if git diff --cached --quiet; then
  echo "no data changes to commit" >>"$LOG"
else
  git commit -m "data: $(date '+%Y-%m-%d %H:%M') collect" >>"$LOG" 2>&1
  for i in 1 2 3 4 5; do
    if git push origin "$BRANCH" >>"$LOG" 2>&1; then break; fi
    echo "push failed — rebase & retry ($i/5)" >>"$LOG"
    git pull --rebase origin "$BRANCH" >>"$LOG" 2>&1 || true
    sleep $((i * 3))
  done
fi

# 뷰어(index.html)용 JSON 생성
python -m scraper.build_site >>"$LOG" 2>&1

# 데드라인으로 중단됐으면 남은 분량을 이어서 실행 (완료까지 반복)
while [ -f .continuation_needed ]; do
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') continuation run =====" >>"$LOG"
  python -m scraper.main --review-text-overall-only --deadline-minutes 320 >>"$LOG" 2>&1
  git add data state 2>>"$LOG"
  git diff --cached --quiet || {
    git commit -m "data: $(date '+%Y-%m-%d %H:%M') collect (cont)" >>"$LOG" 2>&1
    git push origin "$BRANCH" >>"$LOG" 2>&1 || true
  }
done

echo "===== $(date '+%Y-%m-%d %H:%M:%S') collect done =====" >>"$LOG"
