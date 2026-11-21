@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo  Lottery Helper - update draw data
echo ================================================
python tools\fetch_data.py --keep 200 --retry 2
if errorlevel 1 (
  echo [warn] some games may be stale, check the log above
)
git add data
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "chore(data): manual update draw data"
  git push
  echo [ok] data updated and pushed
) else (
  echo [ok] no change
)
pause
