@echo off
setlocal

where uv >nul 2>nul
if errorlevel 1 (
  echo uv is required.
  echo Install it with:
  echo   winget install --id=astral-sh.uv -e
  exit /b 1
)

pushd "%~dp0"
uv run python -m rental_agent.cli %*
set "exit_code=%errorlevel%"
popd
exit /b %exit_code%
