@echo off
title Switch Studio // Super Mario Odyssey Editor
cd /d "%~dp0"
echo Starting Switch Studio Server on http://127.0.0.1:8765 ...
start "" "http://127.0.0.1:8765"
python -X utf8 server.py
pause
