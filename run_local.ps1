# 올리브영 일일 수집 - 로컬 실행 (Windows PowerShell)
# 작업 스케줄러에서 매일 오전 10시에 호출한다.
$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot
$log = "cron.log"
$isGit = Test-Path ".git"
$branch = if ($isGit) { (git rev-parse --abbrev-ref HEAD).Trim() } else { "" }

"===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') collect start =====" | Out-File -Append $log

# 가상환경이 있으면 사용
if (Test-Path ".venv\Scripts\Activate.ps1") { . .\.venv\Scripts\Activate.ps1 }

# 수집: 전 카테고리 랭킹+리뷰수/별점, 리뷰 본문은 전체 TOP100만. 데드라인 320분.
python -m scraper.main --review-text-overall-only --deadline-minutes 320 *>> $log
"collect exit status: $LASTEXITCODE" | Out-File -Append $log

# 데드라인으로 중단됐으면 완료까지 이어서 실행
while (Test-Path ".continuation_needed") {
    "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') continuation run =====" | Out-File -Append $log
    python -m scraper.main --review-text-overall-only --deadline-minutes 320 *>> $log
}

# 뷰어(index.html)용 JSON 생성
python -m scraper.build_site *>> $log

# (선택) git 저장소면 데이터 커밋 & 푸시 — 아니면 로컬에만 저장
if ($isGit) {
    git add data state
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        git commit -m "data: $(Get-Date -Format 'yyyy-MM-dd HH:mm') collect" *>> $log
        for ($i = 1; $i -le 5; $i++) {
            git push origin $branch *>> $log
            if ($LASTEXITCODE -eq 0) { break }
            git pull --rebase origin $branch *>> $log
            Start-Sleep -Seconds ($i * 3)
        }
    }
}

"===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') collect done =====" | Out-File -Append $log
