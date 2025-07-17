#!/bin/bash
echo "Starting server in background..."
nohup python3 server.py --control-port 8000 --http-port 80 --no-ssl > tunnel_server.log 2>&1 &
echo "Server started in background with PID: $!"
echo "Log file: tunnel_server.log"