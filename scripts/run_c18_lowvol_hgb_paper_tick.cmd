@echo off
setlocal
cd /d C:\Projetos\laya-trader-binance
set "PYTHONPATH=C:\Projetos\laya-trader-binance\src"
"C:\Projetos\laya-trader-binance\.venv\Scripts\python.exe" -m jev_trader.lowvol_hgb_paper tick >> "C:\Projetos\laya-trader-binance\research\results\cycle18_lowvol_hgb_forward\paper\scheduled_runner.log" 2>&1
exit /b %ERRORLEVEL%
