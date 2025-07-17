@echo off
echo Starting client in background...
start /b pythonw client.py --server 144.202.26.208 --server-port 8000 --local 127.0.0.1 --local-port 5008 --subdomain p --no-ssl
echo Client started in background
pause