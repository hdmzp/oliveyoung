# 올리브영 일일 수집 - 로컬 실행 (Windows PowerShell)
# 작업 스케줄러에서 매일 오전 10시에 호출한다.
$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
$log = "cron.log"

"===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') collect start (branch=$branch) =====" | Out-File -Append $log

# 가상환경이 있으면 사용
if (Test-Path ".venv\Scripts\Activate.ps1") { . .\.venv\Scripts\Activate.ps1 }

# 수집 (Cloudflare 쿠키 부트스트랩 포함)
python -m scraper.main --deadline-minutes 320 --cf-bootstrap *>> $log
"collect exit status: $LASTEXITCODE" | Out-File -Append $log

# 데이터 커밋 & 푸시
git add data state
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "data: $(Get-Date -Format 'yyyy-MM-dd HH:mm') collect" *>> $log
    for ($i = 1; $i -le 5; $i++) {
        git push origin $branch *>> $log
        if ($LASTEXITCODE -eq 0) { break }
        "push failed - rebase & retry ($i/5)" | Out-File -Append $log
        git pull --rebase origin $branch *>> $log
        Start-Sleep -Seconds ($i * 3)
    }
}

# 데드라인 중단 시 이어서 실행
while (Test-Path ".continuation_needed") {
    "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') continuation run =====" | Out-File -Append $log
    python -m scraper.main --deadline-minutes 320 --cf-bootstrap *>> $log
    git add data state
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        git commit -m "data: $(Get-Date -Format 'yyyy-MM-dd HH:mm') collect (cont)" *>> $log
        git push origin $branch *>> $log
    }
}

"===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') collect done =====" | Out-File -Append $log
