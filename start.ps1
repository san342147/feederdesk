param([int]$Port = 8000)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv\Scripts\python.exe)) {
  py -3.12 -m venv .venv
  & .\.venv\Scripts\python.exe -m pip install -r requirements.lock
}
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port $Port
