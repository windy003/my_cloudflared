客户端cmd运行:

start pyw client.py --server 144.202.26.208 --server-port 8000   --local 127.0.0.1 --local-port 5008 --subdomain p 



服务器:


nohup python3 server.py --control-port 8000 --http-port 443 --cert /etc/letsencrypt/live/windy.run/fullchain.pem --key /etc/letsencrypt/live/windy.run/privkey.pem &> /dev/null &