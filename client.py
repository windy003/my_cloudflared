# 运行的命令
#  python client.py --server 144.202.26.208 --server-port 8000 --local 127.0.0.1 --local-port 5008 --subdomain p



import socket
import threading
import json
import ssl
import time
import argparse
import logging
from urllib.parse import urlparse
import uuid

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tunnel_client.log", mode='w'),
        logging.StreamHandler()
    ]
)

class TunnelClient:
    def __init__(self, server_host, server_port, local_host, local_port, tunnel_id=None, subdomain=None, use_ssl=True):
        self.server_host = server_host
        self.server_port = server_port
        self.local_host = local_host
        self.local_port = local_port
        # 如果提供了子域名但没有隧道ID，则使用子域名作为隧道ID
        if subdomain and not tunnel_id:
            self.tunnel_id = subdomain
        else:
            self.tunnel_id = tunnel_id or str(uuid.uuid4())[:8]  # 如果两者都没有，生成一个短UUID
        self.subdomain = subdomain
        self.use_ssl = use_ssl
        self.running = False
        self.control_socket = None
        self.reconnect_delay = 5  # 初始重连延迟改为5秒
        self.max_reconnect_delay = 300  # 最大重连延迟5分钟
        self.reconnect_attempts = 0  # 重连尝试次数
        self.max_reconnect_attempts = 10  # 最大连续重连尝试次数
        
    def start(self):
        self.running = True
        self.connect_to_server()
        
    def connect_to_server(self):
        while self.running:
            try:
                # 重连时生成新的隧道ID（保留子域名）
                if self.reconnect_attempts > 0:
                    base_id = self.subdomain if self.subdomain else "tunnel"
                    self.tunnel_id = f"{base_id}_{int(time.time())}"
                    logging.info(f"重连使用新隧道ID: {self.tunnel_id}")
                
                # 创建到服务器的控制连接
                logging.info(f"正在连接到服务器 {self.server_host}:{self.server_port}...")
                
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                
                # 设置socket选项提高稳定性
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                
                # Windows特定的keepalive设置
                if hasattr(socket, 'TCP_KEEPIDLE'):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
                
                sock.settimeout(15)  # 增加连接超时时间到15秒
                
                try:
                    # 创建SSL上下文
                    context = ssl.create_default_context()
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                    context.minimum_version = ssl.TLSVersion.TLSv1_2  # 设置最低支持的TLS版本
                    context.maximum_version = ssl.TLSVersion.TLSv1_3  # 设置最高支持的TLS版本
                    # 包装为SSL连接
                    sock = context.wrap_socket(sock, server_hostname=self.server_host)
                    
                    # 尝试连接
                    sock.connect((self.server_host, self.server_port))
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 6)
                    
                    logging.info(f"成功连接到服务器")
                    
                    # 连接成功后重置超时设置
                    sock.settimeout(None)
                    self.control_socket = sock
                    
                    # 发送注册信息
                    registration = {
                        "type": "register",
                        "tunnel_id": self.tunnel_id
                    }
                    
                    # 如果设置了子域名，添加到注册信息中
                    if self.subdomain:
                        registration["subdomain"] = self.subdomain
                    
                    # 直接发送，不使用send_message方法
                    registration_json = json.dumps(registration) 
                    logging.info(f"发送注册消息: {registration_json}")
                    
                    # 确保消息以换行符结束
                    if not registration_json.endswith('\n'):
                        registration_json += '\n'
                        
                    # 发送消息
                    self.control_socket.sendall(registration_json.encode('utf-8'))
                    logging.info(f"注册消息已发送，等待服务器响应...")
                    
                    # 发送一个心跳消息，确保服务器处理了注册消息
                    time.sleep(0.5)  # 等待500毫秒
                    heartbeat = {"type": "heartbeat"}
                    heartbeat_json = json.dumps(heartbeat) + '\n'
                    self.control_socket.sendall(heartbeat_json.encode('utf-8'))
                    logging.info("发送心跳消息")
                    
                    # 主循环 - 处理服务器发来的请求
                    self.handle_server_messages()
                    
                    # 在 connect_to_server 方法中，连接成功后启动心跳线程
                    self.start_heartbeat()
                    
                    # 连接成功，重置重连参数
                    self.reconnect_delay = 5
                    self.reconnect_attempts = 0
                    
                except socket.error as e:
                    logging.error(f"连接错误: {e}")
                    if self.control_socket:
                        self.control_socket.close()
                        self.control_socket = None
                    sock.close()
                    
            except Exception as e:
                logging.error(f"连接过程错误: {e}")
                self.reconnect_attempts += 1
                
                # 指数退避算法
                if self.reconnect_attempts <= self.max_reconnect_attempts:
                    current_delay = min(self.reconnect_delay * (2 ** (self.reconnect_attempts - 1)), self.max_reconnect_delay)
                    logging.info(f"第 {self.reconnect_attempts} 次重连失败，将在 {current_delay} 秒后重试")
                    time.sleep(current_delay)
                else:
                    logging.error(f"连续重连失败 {self.max_reconnect_attempts} 次，等待 {self.max_reconnect_delay} 秒后重置")
                    time.sleep(self.max_reconnect_delay)
                    self.reconnect_attempts = 0
            
            finally:
                if self.control_socket:
                    try:
                        self.control_socket.close()
                    except:
                        pass
                    self.control_socket = None
    
    def send_message(self, message):
        """安全地发送消息到服务器"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if not self.control_socket:
                    logging.error("控制连接不存在")
                    return False
                
                message_json = json.dumps(message)
                if not message_json.endswith('\n'):
                    message_json += '\n'
                
                self.control_socket.sendall(message_json.encode('utf-8'))
                return True
            except Exception as e:
                logging.error(f"发送消息错误 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(0.5)  # 短暂等待后重试
                else:
                    # 最后一次尝试失败，标记连接需要重建
                    self.running = False
                    return False
    
    def handle_server_messages(self):
        buffer = b''
        
        while self.running:
            try:
                # 设置接收超时为30秒
                self.control_socket.settimeout(30)
                data = self.control_socket.recv(4096)
                
                if not data:
                    logging.warning("服务器连接已关闭")
                    break
                
                buffer += data
                
                # 处理可能的多条消息
                while b'\n' in buffer:
                    message, buffer = buffer.split(b'\n', 1)
                    if message:
                        try:
                            self.process_message(message.decode('utf-8'))
                        except Exception as e:
                            logging.error(f"处理单条消息错误: {e}")
                            # 不要因为单条消息处理错误就断开连接
                            continue
                        
            except socket.timeout:
                # 超时不一定是错误，继续循环
                logging.debug("接收数据超时，继续等待")
                continue
            except Exception as e:
                logging.error(f"接收消息错误: {e}")
                break
    
    def process_message(self, message_str):
        try:
            logging.debug(f"处理消息: {message_str.strip()}")
            message = json.loads(message_str)
            message_type = message.get("type")
            
            if message_type == "request":
                # 启动新线程处理请求
                logging.info(f"收到请求: {message['request_id']}")
                threading.Thread(
                    target=self.handle_request, 
                    args=(message["request_id"], message["data"])
                ).start()
            elif message_type == "heartbeat":
                # 处理服务器发送的心跳消息
                logging.info(f"收到服务器心跳消息，时间戳: {message.get('timestamp', 'N/A')}")
                # 发送心跳响应
                heartbeat_response = {
                    "type": "heartbeat_response",
                    "timestamp": time.time(),
                    "original_timestamp": message.get('timestamp')
                }
                self.send_message(heartbeat_response)
                logging.info("发送心跳响应到服务器")
            elif message_type == "heartbeat_response":
                # 处理服务器的心跳响应
                server_time = message.get('server_time', 'N/A')
                server_timestamp = message.get('timestamp', 'N/A')
                logging.info(f"收到服务器心跳响应，服务器时间: {server_time}，时间戳: {server_timestamp}")
            elif message_type == "ping":
                # 处理服务器的ping消息
                ping_timestamp = message.get('timestamp', 'N/A')
                logging.info(f"收到服务器ping消息，时间戳: {ping_timestamp}")
                # 发送pong响应
                pong_response = {
                    "type": "pong",
                    "timestamp": time.time(),
                    "original_timestamp": ping_timestamp
                }
                self.send_message(pong_response)
                logging.info(f"发送pong响应到服务器，原始时间戳: {ping_timestamp}")
            elif message_type == "pong":
                # 处理服务器的pong响应
                original_timestamp = message.get('original_timestamp', 'N/A')
                response_timestamp = message.get('timestamp', 'N/A')
                if original_timestamp != 'N/A' and response_timestamp != 'N/A':
                    try:
                        rtt = float(response_timestamp) - float(original_timestamp)
                        logging.info(f"收到服务器pong响应，往返时间: {rtt:.3f}秒")
                    except:
                        logging.info(f"收到服务器pong响应，原始时间戳: {original_timestamp}")
                else:
                    logging.info("收到服务器pong响应")
            else:
                logging.warning(f"收到未知类型的消息: {message_type}")
        except json.JSONDecodeError as e:
            logging.error(f"JSON解析错误: {e}, 消息内容: {message_str}")
        except Exception as e:
            logging.error(f"处理消息错误: {e}")
    
    def handle_request(self, request_id, data):
        local_socket = None
        try:
            # 确保data是字典类型
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    data = {
                        "method": "GET",
                        "path": "/",
                        "headers": {},
                        "body": ""
                    }
            
            method = data.get('method', 'GET')
            path = data.get('path', '/')
            headers = data.get('headers', {})
            body = data.get('body', '')
            
            # 连接到本地服务
            logging.info(f"连接本地服务 {self.local_host}:{self.local_port}")
            local_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            local_socket.settimeout(240)  # 减少超时时间到30秒
            local_socket.connect((self.local_host, self.local_port))
            
            # 构建HTTP请求
            request_str = f"{method} {path} HTTP/1.1\r\n"
            request_str += f"Host: {self.local_host}:{self.local_port}\r\n"
            
            # 添加原始请求的头部
            for name, value in headers.items():
                if name.lower() not in ['host', 'connection', 'content-length']:
                    request_str += f"{name}: {value}\r\n"
            
            request_str += "Connection: close\r\n"
            
            # 正确设置Content-Length
            if body:
                body_bytes = body.encode('utf-8') if isinstance(body, str) else body
                request_str += f"Content-Length: {len(body_bytes)}\r\n"
            
            request_str += "\r\n"
            
            if body:
                if isinstance(body, str):
                    request_str += body
                else:
                    local_socket.sendall(request_str.encode('utf-8'))
                    local_socket.sendall(body)
                    request_str = ""
            
            # 发送请求到本地服务
            if request_str:
                local_socket.sendall(request_str.encode('utf-8'))
            
            # 接收响应
            logging.info(f"等待本地服务响应")
            response = b""
            while True:
                try:
                    chunk = local_socket.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                except socket.timeout:
                    logging.warning("读取本地服务响应超时")
                    break
            
            if not response:
                logging.warning("本地服务没有返回响应")
                self.send_error_response(request_id, "本地服务没有返回响应")
                return
            
            # 解析HTTP响应
            try:
                http_response = self.parse_http_response(response)
                self.send_success_response(request_id, http_response)
            except Exception as e:
                logging.error(f"解析HTTP响应错误: {e}")
                response_data = {
                    "status": 200,
                    "headers": {"Content-Type": "text/plain"},
                    "body": response.decode('utf-8', errors='replace')
                }
                self.send_success_response(request_id, response_data)
            
        except socket.error as e:
            logging.error(f"连接本地服务错误: {e}")
            self.send_error_response(request_id, f"连接本地服务错误: {str(e)}")
        except Exception as e:
            logging.error(f"处理请求 {request_id} 错误: {e}", exc_info=True)
            self.send_error_response(request_id, str(e))
        finally:
            # 确保本地socket被正确关闭
            if local_socket:
                try:
                    local_socket.close()
                except:
                    pass
    
    def send_test_response(self, request_id):
        """发送测试响应"""
        try:
            logging.info(f"发送测试响应: {request_id}")
            response_data = {
                "status": 200,
                "headers": {"Content-Type": "text/html"},
                "body": f"""
                <!DOCTYPE html>
                <html>
                <head>
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
            
            response_msg = {
                "type": "response",
                "request_id": request_id,
                "data": json.dumps(response_data)
            }
            
            self.send_message(response_msg)
            logging.info(f"测试响应已发送: {request_id}")
        except Exception as e:
            logging.error(f"发送测试响应错误: {e}")
            self.send_error_response(request_id, f"发送测试响应错误: {str(e)}")
    
    def send_success_response(self, request_id, response_data):
        """发送成功响应"""
        try:
            response_msg = {
                "type": "response",
                "request_id": request_id,
                "data": json.dumps(response_data)
            }
            
            success = self.send_message(response_msg)
            if success:
                logging.info(f"响应已发送: {request_id}")
            else:
                logging.error(f"发送响应失败: {request_id}")
        except Exception as e:
            logging.error(f"构建响应消息错误: {e}")
    
    def send_error_response(self, request_id, error_message):
        """发送错误响应"""
        try:
            error_msg = {
                "type": "error",
                "request_id": request_id,
                "error": error_message
            }
            
            success = self.send_message(error_msg)
            if success:
                logging.info(f"错误响应已发送: {request_id}")
            else:
                logging.error(f"发送错误响应失败: {request_id}")
        except Exception as e:
            logging.error(f"构建错误响应消息错误: {e}")
    
    def parse_http_response(self, response_bytes):
        """解析HTTP响应"""
        try:
            # 分离头部和主体
            if b'\r\n\r\n' in response_bytes:
                headers_bytes, body = response_bytes.split(b'\r\n\r\n', 1)
            else:
                headers_bytes, body = response_bytes, b''
                
            headers_str = headers_bytes.decode('utf-8', errors='replace')
            
            # 解析状态行
            status_line, *header_lines = headers_str.split('\r\n')
            parts = status_line.split(' ', 2)
            if len(parts) >= 2:
                status_code = int(parts[1])
            else:
                status_code = 200
            
            # 解析头部
            headers = {}
            for line in header_lines:
                if ':' in line:
                    name, value = line.split(':', 1)
                    headers[name.strip()] = value.strip()
                    
            # 构建响应对象
            response_obj = {
                "status": status_code,
                "headers": headers,
                "body": body.decode('utf-8', errors='replace')
            }
            
            return response_obj
        except Exception as e:
            logging.error(f"解析HTTP响应失败: {e}")
            # 返回简单响应格式
            return {
                "status": 200,
                "headers": {"Content-Type": "text/plain"},
                "body": response_bytes.decode('utf-8', errors='replace')
            }
    
    def stop(self):
        self.running = False
        if self.control_socket:
            try:
                self.control_socket.close()
            except:
                pass

    def start_heartbeat(self):
        def send_heartbeat():
            heartbeat_interval = 20  # 20秒发送一次心跳
            last_heartbeat_time = time.time()
            heartbeat_count = 0
            
            logging.info(f"心跳线程启动，间隔: {heartbeat_interval}秒")
            
            while self.running and self.control_socket:
                try:
                    current_time = time.time()
                    if current_time - last_heartbeat_time >= heartbeat_interval:
                        heartbeat_count += 1
                        heartbeat_timestamp = current_time
                        heartbeat = {
                            "type": "heartbeat", 
                            "timestamp": heartbeat_timestamp,
                            "count": heartbeat_count
                        }
                        heartbeat_json = json.dumps(heartbeat) + '\n'
                        self.control_socket.sendall(heartbeat_json.encode('utf-8'))
                        logging.info(f"发送心跳消息 #{heartbeat_count}，时间戳: {heartbeat_timestamp}")
                        last_heartbeat_time = current_time
                    
                    time.sleep(5)  # 每5秒检查一次
                except Exception as e:
                    logging.error(f"发送心跳失败: {e}")
                    break
            
            logging.info("心跳线程结束")
        
        heartbeat_thread = threading.Thread(target=send_heartbeat)
        heartbeat_thread.daemon = True
        heartbeat_thread.start()

    def check_connection_health(self):
        """检查连接健康状态"""
        if not self.control_socket:
            logging.warning("连接健康检查失败: 控制socket不存在")
            return False
        
        try:
            # 发送一个简单的ping消息
            ping_timestamp = time.time()
            ping_msg = {"type": "ping", "timestamp": ping_timestamp}
            ping_json = json.dumps(ping_msg) + '\n'
            self.control_socket.sendall(ping_json.encode('utf-8'))
            logging.info(f"发送连接健康检查ping，时间戳: {ping_timestamp}")
            return True
        except Exception as e:
            logging.error(f"连接健康检查失败: {e}")
            return False

    def reconnect(self):
        try:
            self.control_socket.close()
        except:
            pass
        self.connect_to_server()
        logging.info("已重新连接到服务器")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="内网穿透客户端")
    parser.add_argument("--server", required=True, help="服务器地址")
    parser.add_argument("--server-port", type=int, default=8000, help="服务器控制端口")
    parser.add_argument("--local", default="127.0.0.1", help="本地服务地址")
    parser.add_argument("--local-port", type=int, required=True, help="本地服务端口")
    parser.add_argument("--tunnel-id", help="隧道ID (当使用子域名时可选)")
    parser.add_argument("--subdomain", help="要使用的子域名，如果提供将用于访问，例如：p.windy.run")
    parser.add_argument("--no-ssl", action="store_true", help="禁用SSL")
    
    args = parser.parse_args()
    
    # 检查是否至少提供了tunnel-id或subdomain中的一个
    if not args.tunnel_id and not args.subdomain:
        print("错误：必须提供 --tunnel-id 或 --subdomain 参数中的至少一个")
        parser.print_help()
        exit(1)
    
    client = TunnelClient(
        args.server,
        args.server_port,
        args.local,
        args.local_port,
        args.tunnel_id,
        args.subdomain,
        not args.no_ssl
    )
    
    try:
        logging.info(f"启动客户端，{'使用子域名 ' + args.subdomain if args.subdomain else ''}，隧道ID: {client.tunnel_id}")
        client.start()
    except KeyboardInterrupt:
        logging.info("正在停止客户端...")
        client.stop()
