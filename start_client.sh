#!/bin/bash
echo "Starting client in background..."
nohup python3 client.py --server 144.202.26.208 --server-port 8000 --local 127.0.0.1 --local-port 5008 --subdomain p --no-ssl > tunnel_client.log 2>&1 &
echo "Client started in background with PID: $!"
echo "Log file: tunnel_client.log"