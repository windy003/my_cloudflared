@echo off
echo Starting server in background...
start /b pythonw server.py --control-port 8000 --http-port 80 --no-ssl
echo Server started in background
pause