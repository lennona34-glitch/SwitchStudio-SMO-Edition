@echo off
title Switch Studio // Super Mario Odyssey Editor
cd /d "%~dp0"
echo Starting Switch Studio Server on http://localhost:5050 ...
start "" "http://localhost:5050"
python -X utf8 server.py
pause
