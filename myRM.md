sudo python3 server.py --control-port 8000 --http-port 443 --cert /etc/letsencrypt/archive/windy.run/cert2.pem  --key /etc/letsencrypt/archive/windy.run/privkey2.pem



python client.py --server 144.202.26.208 --server-port 8000 --local 127.0.0.1 --local-port 5008 --subdomain p
