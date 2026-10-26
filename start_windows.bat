@echo off
cd /d "%~dp0"
py -3 TRAADuoDuo_V0.8.1.pyw
if errorlevel 1 pause
