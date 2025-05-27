# 运行的命令:
# 有ssl
#  python3 server.py --control-port 8000 --http-port 80 --no-ssl
# 无ssl
# sudo python3 server.py --control-port 8000 --http-port 443 --cert /etc/letsencrypt/live/windy.run/fullchain.pem --key  /etc/letsencrypt/live/windy.run/privkey.pem



import socket
import threading
import json
import ssl
import uuid
import argparse
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
import time
import os

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tunnel_server.log", mode='w'),
        logging.StreamHandler()
    ]
)

class TunnelServer:
    def __init__(self, bind_host, bind_port, http_port, use_ssl=True, cert_file=None, key_file=None):
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.http_port = http_port
        self.use_ssl = use_ssl
        self.cert_file = cert_file
        self.key_file = key_file
        self.tunnels = {}  # tunnel_id -> client_socket
        self.domain_tunnels = {}  # subdomain -> tunnel_id
        self.pending_requests = {}  # request_id -> response_event, response_data
        self.running = False
        self.client_last_seen = {}  # 记录客户端最后活跃时间
        self.heartbeat_timeout = 90  # 心跳超时时间（秒）
        self.current_connections = 0  # 改为实例变量
        
    def check_port_available(self, port):
        """检查端口是否可用"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((self.bind_host, port))
            s.close()
            return True
        except:
            return False

    def start(self):
        self.running = True
        
        # 检查端口可用性
        if not self.check_port_available(self.http_port):
            logging.error(f"HTTP端口 {self.http_port} 已被占用，无法启动服务器")
            os.system(f"fuser -k {self.http_port}/tcp")
            time.sleep(5)
            if not self.check_port_available(self.http_port):
                logging.error("无法释放端口，服务器启动失败")
                return False
        
        # 添加这一行 - 启动连接监控
        self.start_connection_monitor()
        
        # 启动控制服务器（接受客户端连接）
        control_thread = threading.Thread(target=self.run_control_server)
        control_thread.daemon = True
        control_thread.start()
        
        # 启动HTTP服务器（接受外部请求）
        http_thread = threading.Thread(target=self.run_http_server)
        http_thread.daemon = True
        http_thread.start()
        
        # 主线程保持运行
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def run_control_server(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
        server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
        server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 6)
        server_socket.bind((self.bind_host, self.bind_port))
        server_socket.listen(5)
        
        logging.info(f"控制服务器运行在 {self.bind_host}:{self.bind_port}")
        
        if self.use_ssl:
            context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            context.load_cert_chain(certfile=self.cert_file, keyfile=self.key_file)
        
        # 添加连接计数和限制
        max_connections = 100  # 最大同时处理的连接数
        
        def _handle_client_connection_wrapper(client_socket, client_address):
            try:
                self.handle_client_connection(client_socket, client_address)
            finally:
                self.current_connections -= 1
        
        while self.running:
            try:
                # 如果当前连接数达到上限，等待一段时间再接受新连接
                if self.current_connections >= max_connections:
                    time.sleep(1)
                    continue
                
                client_socket, client_address = server_socket.accept()
                logging.info(f"接受来自 {client_address} 的连接 (当前连接数: {self.current_connections+1}/{max_connections})")
                
                # 增加当前连接计数
                self.current_connections += 1
                
                if self.use_ssl:
                    try:
                        client_socket = context.wrap_socket(client_socket, server_side=True)
                    except ssl.SSLError as e:
                        logging.error(f"SSL握手失败: {e}")
                        client_socket.close()
                        continue
                
                # 设置客户端套接字的保活选项
                client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
                client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
                client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 6)
                
                # 创建新线程处理客户端连接，并传入连接计数的引用
                client_thread = threading.Thread(
                    target=_handle_client_connection_wrapper, 
                    args=(client_socket, client_address)
                )
                client_thread.daemon = True
                client_thread.start()
                
            except Exception as e:
                logging.error(f"接受连接错误: {e}")
    
    def handle_client_connection(self, client_socket, client_address):
        tunnel_id = None
        buffer = b''
        
        try:
            client_socket.settimeout(15.0)
            
            logging.info(f"等待客户端 {client_address} 的初始数据...")
            
            initial_data = client_socket.recv(4096)
            if not initial_data:
                logging.warning(f"客户端 {client_address} 连接后立即关闭")
                return
            
            # 快速识别HTTP请求并关闭连接
            if initial_data.startswith(b'GET ') or initial_data.startswith(b'POST ') or initial_data.startswith(b'HEAD '):
                logging.warning(f"检测到HTTP请求，不是合法的控制连接: {client_address}")
                client_socket.close()
                return
            
            logging.info(f"收到客户端 {client_address} 的初始数据: {len(initial_data)} 字节")
            logging.debug(f"初始数据: {initial_data[:100].hex()}")
            
            # 尝试以UTF-8解码
            try:
                decoded_data = initial_data.decode('utf-8')
                logging.info(f"解码后的初始数据: {decoded_data.strip()}")
                
                # 查找消息边界
                if '\n' in decoded_data:
                    message, remaining = decoded_data.split('\n', 1)
                    buffer = remaining.encode('utf-8')
                    
                    # 尝试解析JSON
                    try:
                        json_data = json.loads(message)
                        logging.info(f"解析初始JSON成功: {json_data}")
                        
                        # 处理注册消息
                        if json_data.get('type') == 'register':
                            tunnel_id = json_data.get('tunnel_id')
                            self.tunnels[tunnel_id] = client_socket
                            logging.info(f"客户端 {client_address} 成功注册为隧道 {tunnel_id}")
                            
                            # 处理子域名
                            if 'subdomain' in json_data:
                                subdomain = json_data.get('subdomain')
                                self.register_subdomain(subdomain, tunnel_id)
                                logging.info(f"注册子域名 {subdomain} 到隧道 {tunnel_id}")
                        else:
                            logging.warning(f"初始消息不是注册消息: {json_data.get('type')}")
                    except json.JSONDecodeError as e:
                        logging.error(f"初始JSON解析错误: {e}, 消息内容: {message}")
                        buffer = initial_data  # 保留原始数据
                else:
                    logging.warning(f"初始数据中没有换行符，无法解析")
                    buffer = initial_data  # 保留原始数据
            except UnicodeDecodeError:
                logging.error(f"无法解码初始数据为UTF-8，可能不是文本数据")
                if initial_data.startswith(b'\x16\x03'):
                    logging.error(f"检测到SSL/TLS握手，但服务器运行在非SSL模式")
                buffer = initial_data  # 保留原始数据
            
            # 恢复正常超时设置
            client_socket.settimeout(None)
            
            logging.info(f"进入消息处理主循环，当前buffer大小: {len(buffer)} 字节")
            
            # 主循环
            while self.running:
                try:
                    data = client_socket.recv(4096)
                    if not data:
                        logging.info(f"客户端 {client_address} 连接关闭")
                        break
                    
                    logging.debug(f"收到数据: {len(data)} 字节")
                    buffer += data
                    
                    # 处理可能的多条消息
                    while b'\n' in buffer:
                        message, buffer = buffer.split(b'\n', 1)
                        if message:
                            try:
                                # 尝试以UTF-8解码
                                decoded_message = message.decode('utf-8')
                                logging.debug(f"处理消息: {decoded_message[:100]}")
                                self.process_client_message(client_socket, decoded_message, client_address)
                            except UnicodeDecodeError:
                                logging.error(f"无法解码消息")
                                logging.debug(f"消息前20字节: {message[:20].hex()}")
                except Exception as e:
                    logging.error(f"接收数据错误: {e}")
                    break
        
        except Exception as e:
            logging.error(f"处理客户端 {client_address} 错误: {e}", exc_info=True)
        
        finally:
            # 清理
            if tunnel_id and tunnel_id in self.tunnels:
                del self.tunnels[tunnel_id]
                logging.info(f"隧道 {tunnel_id} 已移除")
            
            try:
                client_socket.close()
            except:
                pass
    
    def process_client_message(self, client_socket, message_str, client_address):
        try:
            logging.info(f"处理客户端消息: {message_str}")
            message = json.loads(message_str)
            
            # 更新客户端最后活跃时间
            if "tunnel_id" in message:
                tunnel_id = message["tunnel_id"]
                self.client_last_seen[tunnel_id] = time.time()
            
            if message["type"] == "register":
                # 客户端注册
                tunnel_id = message["tunnel_id"]
                self.tunnels[tunnel_id] = client_socket
                self.client_last_seen[tunnel_id] = time.time()  # 记录注册时间
                logging.info(f"客户端 {client_address} 注册为隧道 {tunnel_id}")
                
                # 处理子域名注册
                if "subdomain" in message:
                    subdomain = message["subdomain"]
                    self.register_subdomain(subdomain, tunnel_id)
                    logging.info(f"为隧道 {tunnel_id} 注册子域名 {subdomain}")
                
                # 发送确认消息
                try:
                    confirmation = {
                        "type": "register_confirm",
                        "tunnel_id": tunnel_id,
                        "status": "success"
                    }
                    client_socket.sendall((json.dumps(confirmation) + '\n').encode('utf-8'))
                    logging.info(f"已发送注册确认消息给隧道 {tunnel_id}")
                except Exception as e:
                    logging.error(f"发送注册确认消息失败: {e}")
                
                # 启动心跳线程
                self.start_heartbeat(client_socket, tunnel_id)
                
            elif message["type"] == "heartbeat":
                # 心跳消息 - 更新活跃时间
                tunnel_id = message.get("tunnel_id", "unknown")
                self.client_last_seen[tunnel_id] = time.time()
                logging.debug(f"收到隧道 {tunnel_id} 的心跳消息")
                
                # 发送心跳响应
                try:
                    response = {"type": "heartbeat_response", "timestamp": time.time()}
                    client_socket.sendall((json.dumps(response) + '\n').encode('utf-8'))
                except Exception as e:
                    logging.error(f"发送心跳响应失败: {e}")
                
            elif message["type"] == "response" or message["type"] == "error":
                # 处理客户端的响应
                request_id = message["request_id"]
                if request_id in self.pending_requests:
                    event, _ = self.pending_requests[request_id]
                    self.pending_requests[request_id] = (event, message)
                    event.set()  # 通知等待线程
                else:
                    logging.warning(f"收到未知请求ID的响应: {request_id}")
            
            else:
                logging.warning(f"收到未知类型的消息: {message['type']}")
        
        except json.JSONDecodeError:
            logging.error(f"JSON解析错误: {message_str[:100]}...")
        except Exception as e:
            logging.error(f"处理客户端消息错误: {e}")
    
    def run_http_server(self):
        try:
            # 创建HTTP服务器来接收外部请求
            server = self.create_http_server()
            logging.info(f"HTTP服务器运行在 {self.bind_host}:{self.http_port}")
            server.serve_forever()
        except OSError as e:
            if e.errno == 98:  # 地址已被使用
                logging.error(f"HTTP端口 {self.http_port} 已被占用，尝试释放...")
                # 尝试终止占用端口的进程
                os.system(f"fuser -k {self.http_port}/tcp")
                time.sleep(10)  # 等待端口释放
            logging.error(f"HTTP服务器发生错误: {e}", exc_info=True)
            if self.running:
                # 尝试重启HTTP服务器
                logging.info("尝试重启HTTP服务器...")
                time.sleep(5)
                self.run_http_server()
    
    def create_http_server(self):
        tunnel_server = self
        
        class TunnelHttpHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.handle_request()
                
            def do_POST(self):
                self.handle_request()
                
            def handle_request(self):
                # 首先检查Host头部,处理子域名
                host = self.headers.get('Host', '')
                logging.info(f"收到请求: Host={host}, Path={self.path}")
                
                # 解析子域名
                subdomain = None
                if '.' in host:
                    parts = host.split('.')
                    if len(parts) >= 2:  # 支持 p.windy.run 格式
                        subdomain = parts[0]
                        logging.info(f"解析到子域名: {subdomain}")
                
                # 在日志中输出当前所有子域名映射，用于调试
                logging.info(f"当前子域名映射: {tunnel_server.domain_tunnels}")
                
                # 如果存在子域名映射,直接使用对应的隧道ID
                if subdomain and subdomain in tunnel_server.domain_tunnels:
                    tunnel_id = tunnel_server.domain_tunnels[subdomain]
                    logging.info(f"通过子域名 {subdomain} 找到隧道 {tunnel_id}")
                    # 子域名方式访问，路径保持不变
                    remaining_path = self.path
                else:
                    if subdomain:
                        logging.warning(f"子域名 {subdomain} 没有对应的隧道映射")
                    
                    # 传统方式：从路径中提取隧道ID
                    path_parts = self.path.split('/')
                    if len(path_parts) < 2 or not path_parts[1]:  # 检查是否为空
                        logging.warning(f"请求没有指定隧道ID: {self.path}")
                        self.send_error(404, "隧道ID未指定")
                        return
                    
                    tunnel_id = path_parts[1]
                    remaining_path = '/' + '/'.join(path_parts[2:])
                
                # 检查隧道是否存在
                if tunnel_id not in tunnel_server.tunnels:
                    logging.warning(f"请求的隧道不存在: {tunnel_id}")
                    self.send_error(404, f"隧道 {tunnel_id} 不存在或未连接")
                    return
                
                logging.info(f"处理到隧道 {tunnel_id} 的请求, 路径: {remaining_path}")
                
                # 读取请求体
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length) if content_length > 0 else b''
                
                # 构建要发送给客户端的请求
                headers = dict(self.headers)
                
                # 修正Content-Length，确保与实际body长度匹配
                if body:
                    headers['Content-Length'] = str(len(body))
                elif 'Content-Length' in headers:
                    # 如果没有body但有Content-Length，删除这个头部
                    del headers['Content-Length']
                
                request_data = {
                    "method": self.command,
                    "path": remaining_path,
                    "headers": headers,  # 使用修正后的headers
                    "body": body.decode('utf-8', errors='replace') if body else ""
                }
                
                # 发送请求到客户端并等待响应
                response = tunnel_server.forward_request_to_client(tunnel_id, request_data)
                if not response:
                    logging.error(f"无法从内网服务获取响应")
                    self.send_error(502, "无法从内网服务获取响应")
                    return
                
                # 处理响应
                if response["type"] == "error":
                    error_msg = response.get("error", "内网服务错误")
                    logging.error(f"收到错误响应: {error_msg}")
                    self.send_error(502, error_msg)
                    return
                
                # 解析响应内容
                try:
                    logging.info(f"收到响应数据，正在解析...")
                    resp_data = json.loads(response["data"])
                    status_code = resp_data.get("status", 200)
                    headers = resp_data.get("headers", {})
                    body = resp_data.get("body", "")
                    
                    # 确保Content-Type指定了字符集
                    if "Content-Type" in headers and "charset" not in headers["Content-Type"]:
                        if "text/html" in headers["Content-Type"]:
                            headers["Content-Type"] = "text/html; charset=utf-8"
                        elif "text/plain" in headers["Content-Type"]:
                            headers["Content-Type"] = "text/plain; charset=utf-8"
                    
                    # 发送响应
                    logging.info(f"发送响应: 状态码 {status_code}")
                    self.send_response(status_code)
                    for name, value in headers.items():
                        self.send_header(name, value)
                    self.end_headers()
                    
                    if body:
                        # 确保以UTF-8编码发送
                        self.wfile.write(body.encode('utf-8', errors='replace'))
                        logging.info(f"响应体已发送，长度: {len(body)}")
                    
                except Exception as e:
                    logging.error(f"解析响应数据失败: {e}")
                    # 如果无法解析JSON，则直接返回原始响应
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(("解析响应失败: " + str(e)).encode('utf-8'))
            
            def send_error(self, code, message=None, explain=None):
                """自定义send_error方法以支持中文"""
                # 记录错误消息
                logging.error(f"错误: {message}")
                
                # 将非ASCII消息替换为ASCII消息（如果需要）
                if message and not all(ord(c) < 128 for c in message):
                    ascii_message = "Error occurred"
                else:
                    ascii_message = message
                
                # 发送响应头
                self.send_response(code, ascii_message)
                self.send_header("Content-Type", "text/html;charset=utf-8")
                self.send_header("Connection", "close")
                self.end_headers()
                
                # 发送HTML内容
                content = f"""
                <!DOCTYPE HTML>
                <html>
                    <head>
                        <meta charset="utf-8">
                        <title>错误 {code}</title>
                    </head>
                    <body>
                        <h1>错误 {code}</h1>
                        <p>{message}</p>
                        <p>{explain if explain else ""}</p>
                    </body>
                </html>
                """
                
                self.wfile.write(content.encode('utf-8'))
            
            def log_message(self, format, *args):
                """覆盖日志记录方法，防止IndexError"""
                try:
                    if len(args) >= 3:
                        logging.info(f"HTTP请求: {args[0]} {args[1]} {args[2]}")
                    else:
                        logging.info(f"HTTP日志: {format % args if args else format}")
                except Exception as e:
                    logging.error(f"日志记录出错: {e}")
        
        httpd = HTTPServer((self.bind_host, self.http_port), TunnelHttpHandler)
        httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # 添加HTTPS支持
        if self.use_ssl and self.cert_file and self.key_file:
            context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            context.load_cert_chain(certfile=self.cert_file, keyfile=self.key_file)
            httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
            logging.info(f"HTTPS服务器运行在 {self.bind_host}:{self.http_port}")
        
        return httpd
    
    def forward_request_to_client(self, tunnel_id, request_data):
        client_socket = self.tunnels.get(tunnel_id)
        if not client_socket:
            logging.error(f"找不到隧道 {tunnel_id} 的连接")
            return None
        
        # 添加这个连接检查
        try:
            # 发送一个小的测试包
            client_socket.sendall(b'')  # 空数据包测试连接
        except:
            logging.error(f"隧道 {tunnel_id} 连接已断开，清理中...")
            self.cleanup_tunnel(tunnel_id)
            return None
        
        # 生成唯一请求ID
        request_id = str(uuid.uuid4())
        
        # 创建事件对象来等待响应
        response_event = threading.Event()
        self.pending_requests[request_id] = (response_event, None)
        
        try:
            # 发送请求到客户端
            request_msg = {
                "type": "request",
                "request_id": request_id,
                "data": json.dumps(request_data)
            }
            
            logging.info(f"发送请求到客户端 (隧道ID: {tunnel_id}, 请求ID: {request_id})")
            client_socket.sendall(json.dumps(request_msg).encode() + b'\n')
            
            # 等待响应，超时60秒
            if response_event.wait(90):
                logging.info(f"收到响应事件通知 (请求ID: {request_id})")
                _, response = self.pending_requests.pop(request_id)
                logging.info(f"收到客户端响应 (请求ID: {request_id}, 类型: {response.get('type')})")
                return response
            else:
                # 超时
                logging.warning(f"等待客户端响应超时 (请求ID: {request_id})")
                self.pending_requests.pop(request_id, None)
                return None
                
        except Exception as e:
            logging.error(f"转发请求错误: {e}")
            self.pending_requests.pop(request_id, None)
            return None
    
    def stop(self):
        self.running = False
        logging.info("正在停止服务器...")

    def send_test_response(self, request_id):
        """发送测试响应"""
        try:
            logging.info(f"发送测试响应: {request_id}")
            response_data = {
                "status": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},  # 明确指定UTF-8编码
                "body": f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="utf-8">  <!-- 添加此行确保HTML正确解析UTF-8 -->
                    <title>隧道测试</title>
                    <style>
                        body {{
                            font-family: Arial, sans-serif;
                            margin: 40px;
                            line-height: 1.6;
                        }}
                        .container {{
                            max-width: 800px;
                            margin: 0 auto;
                            padding: 20px;
                            border: 1px solid #ddd;
                            border-radius: 5px;
                        }}
                        h1 {{
                            color: #2c3e50;
                        }}
                        .success {{
                            color: #27ae60;
                            font-weight: bold;
                        }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>内网穿透测试</h1>
                        <p class="success">✅ 隧道工作正常!</p>
                        <p>请求ID: {request_id}</p>
                        <p>隧道ID: {self.tunnel_id}</p>
                        <p>时间: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
                        <hr>
                        <p>服务器: {self.server_host}:{self.server_port}</p>
                        <p>本地服务: {self.local_host}:{self.local_port}</p>
                    </div>
                </body>
                </html>
                """
            }
            

        except Exception as e:
            logging.error(f"发送测试响应错误: {e}")

    # 添加一个新方法用于注册子域名
    def register_subdomain(self, subdomain, tunnel_id):
        self.domain_tunnels[subdomain] = tunnel_id
        logging.info(f"子域名 {subdomain} 已映射到隧道 {tunnel_id}")
        # 打印当前所有子域名映射，用于调试
        logging.info(f"当前子域名映射: {self.domain_tunnels}")

    # 添加一个定期发送心跳的方法
    def start_heartbeat(self, client_socket, tunnel_id):
        def send_heartbeat():
            while tunnel_id in self.tunnels and self.running:
                try:
                    heartbeat_msg = {"type": "heartbeat"}
                    client_socket.sendall((json.dumps(heartbeat_msg) + '\n').encode('utf-8'))
                    logging.debug(f"向隧道 {tunnel_id} 发送心跳")
                    time.sleep(30)  # 每30秒发送一次心跳
                except Exception as e:
                    logging.error(f"发送心跳失败: {e}")
                    break
        
        heartbeat_thread = threading.Thread(target=send_heartbeat)
        heartbeat_thread.daemon = True
        heartbeat_thread.start()

    def format_time_duration(self, seconds):
        """将秒数转换为天、小时、分钟、秒的格式"""
        if seconds < 0:
            return "0秒"
        
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        parts = []
        if days > 0:
            parts.append(f"{days}天")
        if hours > 0:
            parts.append(f"{hours}小时")
        if minutes > 0:
            parts.append(f"{minutes}分钟")
        if secs > 0 or not parts:  # 如果没有其他部分，至少显示秒
            parts.append(f"{secs}秒")
        
        return "".join(parts)

    def start_connection_monitor(self):
        def monitor_connections():
            while self.running:
                try:
                    # 统计当前连接数
                    connection_count = len(self.tunnels)
                    logging.info(f"当前活跃隧道数: {connection_count}")
                    
                    # 列出所有活跃隧道
                    if connection_count > 0:
                        tunnel_info = []
                        current_time = time.time()
                        for tunnel_id in self.tunnels:
                            last_seen = self.client_last_seen.get(tunnel_id, current_time)
                            idle_time = current_time - last_seen
                            # 如果空闲时间为负数或过大（超过1年），说明数据有问题
                            if idle_time < 0 or idle_time > 365 * 24 * 3600:
                                formatted_time = "未知"
                                # 重新设置为当前时间
                                self.client_last_seen[tunnel_id] = current_time
                            else:
                                formatted_time = self.format_time_duration(idle_time)
                            tunnel_info.append(f"{tunnel_id}(空闲{formatted_time})")
                        logging.info(f"活跃隧道: {', '.join(tunnel_info)}")
                    
                    # 检查系统资源
                    import os, psutil
                    process = psutil.Process(os.getpid())
                    mem_info = process.memory_info()
                    logging.info(f"内存使用: {mem_info.rss / 1024 / 1024:.1f} MB")
                    
                    # 其余代码...
                    time.sleep(60)  # 每分钟记录一次
                except Exception as e:
                    logging.error(f"监控错误: {e}")
                    time.sleep(60)
        
        monitor_thread = threading.Thread(target=monitor_connections)
        monitor_thread.daemon = True
        monitor_thread.start()

    def cleanup_tunnel(self, tunnel_id):
        """清理指定的隧道连接"""
        if tunnel_id in self.tunnels:
            try:
                self.tunnels[tunnel_id].close()
            except:
                pass
            del self.tunnels[tunnel_id]
            logging.info(f"已清理僵尸隧道: {tunnel_id}")
        
        if tunnel_id in self.client_last_seen:
            del self.client_last_seen[tunnel_id]
        
        # 清理子域名映射
        for subdomain, tid in list(self.domain_tunnels.items()):
            if tid == tunnel_id:
                del self.domain_tunnels[subdomain]
                logging.info(f"已清理子域名映射: {subdomain} -> {tunnel_id}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="内网穿透服务器")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址")
    parser.add_argument("--control-port", type=int, default=8000, help="控制服务器端口")
    parser.add_argument("--http-port", type=int, default=80, help="HTTP服务器端口")
    parser.add_argument("--no-ssl", action="store_true", help="禁用SSL")
    parser.add_argument("--cert", help="SSL证书文件")
    parser.add_argument("--key", help="SSL密钥文件")
    
    args = parser.parse_args()
    
    # 如果启用SSL，则需要提供证书和密钥文件
    if not args.no_ssl and (not args.cert or not args.key):
        parser.error("启用SSL时需要提供--cert和--key参数")
    
    server = TunnelServer(
        args.host,
        args.control_port,
        args.http_port,
        not args.no_ssl,
        args.cert,
        args.key
    )
    
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()
