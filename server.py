# 运行的命令:
# 无ssl
#  python3 server.py --control-port 8000 --http-port 80 --no-ssl
# 有ssl
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
import requests  # 新增导入
import select
import signal
import sys
from logging.handlers import RotatingFileHandler

# 配置日志轮转
def setup_logging():
    """设置日志配置，包含轮转功能"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 清除现有的处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 文件处理器 - 轮转日志
    file_handler = RotatingFileHandler(
        "tunnel_server.log", 
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,          # 保留5个备份
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# 初始化日志
setup_logging()

# 设置标准输出编码为UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
elif hasattr(sys.stdout, 'buffer'):
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

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
        self.heartbeat_timeout = 180  # 心跳超时时间（秒）增加到3分钟
        self.current_connections = 0  # 改为实例变量
        self.timeout = 300  # 增加超时时间到5分钟
        self.shutdown_event = threading.Event()  # 优雅关闭事件
        self.http_server_instance = None
        self.control_server_socket = None
        
        # 注册信号处理器
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """处理信号，优雅关闭"""
        logging.info(f"收到信号 {signum}，开始优雅关闭服务器...")
        self.stop()
        
    def check_port_available(self, port):
        """检查端口是否可用"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((self.bind_host, port))
            s.close()
            return True
        except socket.error:
            return False
        finally:
            try:
                s.close()
            except:
                pass

    def start(self):
        self.running = True
        self.shutdown_event.clear()
        
        # 检查端口可用性
        if not self.check_port_available(self.http_port):
            logging.error(f"HTTP端口 {self.http_port} 已被占用，尝试释放...")
            try:
                os.system(f"fuser -k {self.http_port}/tcp 2>/dev/null")
                time.sleep(5)
            except:
                pass
            
            if not self.check_port_available(self.http_port):
                logging.error("无法释放端口，服务器启动失败")
                return False
        
        # 启动各种监控服务
        self._start_connection_monitor()
        self._start_http_server_monitor() 
        
        # 启动控制服务器（接受客户端连接）
        control_thread = threading.Thread(target=self.run_control_server, name="ControlServer")
        control_thread.daemon = True
        control_thread.start()
        
        # 启动HTTP服务器（接受外部请求）
        http_thread = threading.Thread(target=self.run_http_server, name="HttpServer")
        http_thread.daemon = True
        http_thread.start()
        
        logging.info("服务器启动完成")
        
        # 主线程保持运行
        try:
            while self.running and not self.shutdown_event.is_set():
                self.shutdown_event.wait(1)
        except KeyboardInterrupt:
            self.stop()
        
        logging.info("服务器主循环结束")
    
    def check_http_server_status(self):
        """检查HTTP服务器状态"""
        try:
            # 构建检查URL - 使用一个简单的根路径请求
            protocol = "https" if self.use_ssl else "http"
            check_url = f"{protocol}://{self.bind_host}:{self.http_port}/"
            
            # 如果bind_host是0.0.0.0，使用localhost进行检查
            if self.bind_host == "0.0.0.0":
                check_url = f"{protocol}://localhost:{self.http_port}/"
            
            # 发送健康检查请求
            response = requests.get(check_url, timeout=10, verify=False)
            
            # 只要能收到响应（无论状态码是什么），都表明HTTP服务器正在运行
            return {
                "status": "运行中",
                "response_code": response.status_code,
                "response_time": response.elapsed.total_seconds(),
                "error": None
            }
                
        except requests.exceptions.ConnectionError:
            return {
                "status": "连接失败",
                "response_code": None,
                "response_time": None,
                "error": "无法连接到HTTP服务器"
            }
        except requests.exceptions.Timeout:
            return {
                "status": "超时",
                "response_code": None,
                "response_time": None,
                "error": "HTTP服务器响应超时"
            }
        except Exception as e:
            return {
                "status": "错误",
                "response_code": None,
                "response_time": None,
                "error": str(e)
            }
    
    def _start_http_server_monitor(self):
        """启动HTTP服务器状态监控"""
        def monitor_http_server():
            logging.info("HTTP服务器状态监控已启动，每2分钟检查一次")
            consecutive_failures = 0
            
            while self.running and not self.shutdown_event.is_set():
                try:
                    # 检查HTTP服务器状态
                    status_info = self.check_http_server_status()
                    
                    # 构建状态消息
                    status_msg = f"HTTP服务器状态检查 - 状态: {status_info['status']}"
                    
                    if status_info['response_code'] is not None:
                        status_msg += f", 响应码: {status_info['response_code']}"
                    
                    if status_info['response_time'] is not None:
                        status_msg += f", 响应时间: {status_info['response_time']:.3f}秒"
                    
                    if status_info['error']:
                        status_msg += f", 错误: {status_info['error']}"
                    
                    # 记录日志和处理失败
                    if status_info['status'] == "运行中":
                        logging.debug(status_msg)
                        consecutive_failures = 0  # 重置失败计数
                    else:
                        logging.warning(status_msg)
                        consecutive_failures += 1
                        
                        # 如果连续失败3次，尝试重启HTTP服务器
                        if consecutive_failures >= 3:
                            logging.error("HTTP服务器连续失败3次，尝试重启...")
                            self.restart_http_server()
                            consecutive_failures = 0  # 重置计数
                    
                    # 等待120秒（2分钟）或关闭事件
                    if self.shutdown_event.wait(120):
                        break
                    
                except Exception as e:
                    error_msg = f"HTTP服务器状态监控出错: {e}"
                    logging.error(error_msg)
                    if self.shutdown_event.wait(60):
                        break
        
        # 启动监控线程
        monitor_thread = threading.Thread(target=monitor_http_server, name="HttpMonitor")
        monitor_thread.daemon = True
        monitor_thread.start()
    
    def restart_http_server(self):
        """重启HTTP服务器"""
        try:
            logging.info("正在重启HTTP服务器...")
            
            # 如果有现有的HTTP服务器实例，尝试关闭它
            if hasattr(self, 'http_server_instance') and self.http_server_instance:
                try:
                    self.http_server_instance.shutdown()
                    self.http_server_instance.server_close()
                    logging.info("已关闭旧的HTTP服务器实例")
                except Exception as e:
                    logging.warning(f"关闭旧HTTP服务器时出错: {e}")
                finally:
                    self.http_server_instance = None
            
            # 强制释放端口（Windows版本）
            try:
                import subprocess
                # 在Windows上查找并杀死占用端口的进程
                result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
                for line in result.stdout.split('\n'):
                    if f':{self.http_port}' in line and 'LISTENING' in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            try:
                                subprocess.run(['taskkill', '/F', '/PID', pid], check=True)
                                logging.info(f"已终止占用端口{self.http_port}的进程 PID: {pid}")
                            except subprocess.CalledProcessError:
                                logging.warning(f"无法终止进程 PID: {pid}")
            except Exception as e:
                logging.warning(f"端口释放操作失败: {e}")
            
            # 等待更长时间确保端口完全释放
            time.sleep(5)
            
            # 检查端口是否可用
            max_retries = 10
            for i in range(max_retries):
                if self.check_port_available(self.http_port):
                    logging.info(f"端口 {self.http_port} 已可用")
                    break
                else:
                    logging.warning(f"端口 {self.http_port} 仍被占用，等待中... ({i+1}/{max_retries})")
                    time.sleep(2)
            else:
                logging.error(f"端口 {self.http_port} 在 {max_retries} 次尝试后仍无法使用")
                return
            
            # 启动新的HTTP服务器线程
            http_thread = threading.Thread(target=self.run_http_server, name="HttpServer-Restart")
            http_thread.daemon = True
            http_thread.start()
            
            logging.info("HTTP服务器重启完成")
            
        except Exception as e:
            logging.error(f"重启HTTP服务器失败: {e}")
    
    def run_control_server(self):
        """运行控制服务器，接受客户端连接"""
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, 'TCP_KEEPIDLE'):
            server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
            server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 6)
        
        server_socket.settimeout(1.0)  # 设置超时以便可以检查关闭事件
        self.control_server_socket = server_socket
        
        try:
            server_socket.bind((self.bind_host, self.bind_port))
            server_socket.listen(10)  # 增加监听队列
            
            logging.info(f"控制服务器运行在 {self.bind_host}:{self.bind_port}")
            
            if self.use_ssl:
                context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                context.load_cert_chain(certfile=self.cert_file, keyfile=self.key_file)
            
            # 添加连接计数和限制
            max_connections = 100  # 最大同时处理的连接数
            
            while self.running and not self.shutdown_event.is_set():
                try:
                    # 如果当前连接数达到上限，等待一段时间再接受新连接
                    if self.current_connections >= max_connections:
                        if self.shutdown_event.wait(1):
                            break
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
                            self.current_connections -= 1
                            continue
                    
                    # 设置客户端套接字的保活选项
                    client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    if hasattr(socket, 'TCP_KEEPIDLE'):
                        client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
                        client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
                        client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 6)
                    
                    # 创建新线程处理客户端连接
                    client_thread = threading.Thread(
                        target=self._handle_client_connection_wrapper,
                        args=(client_socket, client_address),
                        name=f"Client-{client_address[0]}:{client_address[1]}"
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                except socket.timeout:
                    continue  # 超时继续循环检查关闭事件
                except Exception as e:
                    if self.running and not self.shutdown_event.is_set():
                        logging.error(f"接受连接错误: {e}")
                        time.sleep(1)
        except Exception as e:
            logging.error(f"控制服务器启动失败: {e}")
        finally:
            try:
                server_socket.close()
            except:
                pass
            self.control_server_socket = None
            logging.info("控制服务器已关闭")
            
    def _handle_client_connection_wrapper(self, client_socket, client_address):
        """包装器函数，用于处理异常"""
        try:
            self.handle_client_connection(client_socket, client_address)
        except Exception as e:
            logging.error(f"处理客户端连接异常 {client_address}: {e}")
        finally:
            self.current_connections -= 1
            logging.info(f"连接 {client_address} 已断开，当前连接数: {self.current_connections}")
            try:
                client_socket.close()
            except:
                pass
    
    def handle_client_connection(self, client_socket, client_address):
        tunnel_id = None
        buffer = b''
        last_activity = time.time()
        
        try:
            # 设置更合理的超时时间
            client_socket.settimeout(30.0)
            
            # 添加连接活跃度跟踪
            def update_activity():
                nonlocal last_activity
                last_activity = time.time()
                if tunnel_id:
                    self.client_last_seen[tunnel_id] = last_activity
            
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
            while self.running and tunnel_id in self.tunnels:
                try:
                    data = client_socket.recv(4096)
                    if not data:
                        break
                    
                    update_activity()  # 更新活跃时间
                    
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
                except socket.timeout:
                    # 检查是否长时间无活动
                    if time.time() - last_activity > 120:  # 2分钟无活动
                        logging.warning(f"客户端 {tunnel_id} 长时间无活动，断开连接")
                        break
                    continue
                except Exception as e:
                    logging.error(f"接收数据错误: {e}")
                    break
        
        except Exception as e:
            logging.error(f"处理客户端连接错误: {e}")
        
        finally:
            # 清理连接
            if tunnel_id:
                self.cleanup_tunnel(tunnel_id)
    
    def process_client_message(self, client_socket, message_str, client_address):
        try:
            message = json.loads(message_str)
            message_type = message.get("type")
            
            if message_type == "register":
                tunnel_id = message["tunnel_id"]
                
                # 如果隧道已存在，先清理旧连接
                if tunnel_id in self.tunnels:
                    logging.warning(f"隧道 {tunnel_id} 已存在，清理旧连接")
                    self.cleanup_tunnel(tunnel_id)
                
                # 注册新连接
                self.tunnels[tunnel_id] = client_socket
                self.client_last_seen[tunnel_id] = time.time()
                logging.info(f"客户端 {client_address} 注册为隧道 {tunnel_id}")
                
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
                
            elif message_type == "heartbeat":
                # 增加详细的心跳处理日志
                tunnel_id = None
                for tid, socket in self.tunnels.items():
                    if socket == client_socket:
                        tunnel_id = tid
                        break
                
                if tunnel_id:
                    logging.info(f"收到隧道 {tunnel_id} 的心跳消息，时间戳: {message.get('timestamp', 'N/A')}")
                    # 更新最后活跃时间
                    self.client_last_seen[tunnel_id] = time.time()
                    
                    # 发送心跳响应
                    heartbeat_response = {
                        "type": "heartbeat_response", 
                        "timestamp": time.time(),
                        "server_time": time.strftime('%Y-%m-%d %H:%M:%S')
                    }
                    response_json = json.dumps(heartbeat_response) + '\n'
                    client_socket.sendall(response_json.encode('utf-8'))
                    logging.info(f"向隧道 {tunnel_id} 发送心跳响应")
                else:
                    logging.warning(f"收到未知连接的心跳消息: {client_address}")
                
            elif message_type == "ping":
                # 增加详细的ping处理日志
                tunnel_id = None
                for tid, socket in self.tunnels.items():
                    if socket == client_socket:
                        tunnel_id = tid
                        break
                
                if tunnel_id:
                    logging.info(f"收到隧道 {tunnel_id} 的ping消息，时间戳: {message.get('timestamp', 'N/A')}")
                    # 更新最后活跃时间
                    self.client_last_seen[tunnel_id] = time.time()
                    
                    # 发送pong响应
                    pong_response = {
                        "type": "pong", 
                        "timestamp": time.time(),
                        "original_timestamp": message.get('timestamp')
                    }
                    response_json = json.dumps(pong_response) + '\n'
                    client_socket.sendall(response_json.encode('utf-8'))
                    logging.info(f"向隧道 {tunnel_id} 发送pong响应")
                else:
                    logging.warning(f"收到未知连接的ping消息: {client_address}")
                
            elif message_type == "pong":
                # 处理客户端的pong响应
                tunnel_id = None
                for tid, socket in self.tunnels.items():
                    if socket == client_socket:
                        tunnel_id = tid
                        break
                
                if tunnel_id:
                    original_timestamp = message.get('original_timestamp')
                    current_time = time.time()
                    
                    if original_timestamp:
                        rtt = current_time - original_timestamp
                        logging.info(f"收到隧道 {tunnel_id} 的pong响应，往返时间: {rtt:.3f}秒，原始时间戳: {original_timestamp}")
                    else:
                        logging.info(f"收到隧道 {tunnel_id} 的pong响应，时间戳: {message.get('timestamp', 'N/A')}")
                    
                    # 更新最后活跃时间
                    self.client_last_seen[tunnel_id] = current_time
                    
                    # 如果有等待ping响应的记录，可以在这里处理
                    # 例如更新连接状态等
                    
                else:
                    logging.warning(f"收到未知连接的pong响应: {client_address}")
            
            elif message_type == "response" or message_type == "error":
                request_id = message["request_id"]
                if request_id in self.pending_requests:
                    event, _ = self.pending_requests[request_id]
                    self.pending_requests[request_id] = (event, message)
                    event.set()
                    if message_type == "error":
                        logging.warning(f"收到客户端错误响应 (请求ID: {request_id}): {message.get('error', '未知错误')}")
                    else:
                        logging.info(f"收到客户端成功响应 (请求ID: {request_id})")
                else:
                    logging.warning(f"收到未知请求ID的响应: {request_id}")
            
            elif message_type == "progress":
                # 新增：处理进度更新
                request_id = message.get("request_id")
                progress_message = message.get("message", "")
                timestamp = message.get("timestamp", time.time())
                
                logging.info(f"爬虫进度更新 (请求ID: {request_id}): {progress_message}")
                
                # 更新请求的最后活动时间，防止超时
                if request_id in self.pending_requests:
                    event, _ = self.pending_requests[request_id]
                    # 这里可以记录进度，但不触发事件完成
                    logging.debug(f"请求 {request_id} 仍在处理中，已更新活动时间")
            
            else:
                logging.warning(f"收到未知类型的消息: {message_type}")
        
        except json.JSONDecodeError as e:
            logging.error(f"解析客户端消息失败: {e}")
        except Exception as e:
            logging.error(f"处理客户端消息错误: {e}")
    
    def run_http_server(self):
        """运行HTTP服务器，支持自动重启"""
        consecutive_failures = 0
        max_consecutive_failures = 3  # 改为3次，更快重启
        
        while self.running:
            try:
                # 创建HTTP服务器
                server = self.create_http_server()
                logging.info(f"HTTP服务器运行在 {self.bind_host}:{self.http_port}")
                
                # 保存服务器实例
                self.http_server_instance = server
                
                # 重置失败计数
                consecutive_failures = 0
                
                # 启动服务器
                server.serve_forever()
                
                # 如果到达这里，说明serve_forever()退出了
                if self.running:
                    logging.warning("HTTP服务器意外退出，准备重启...")
                else:
                    logging.info("HTTP服务器正常关闭")
                    break
                
            except OSError as e:
                consecutive_failures += 1
                if e.errno == 98 or e.errno == 10048:  # 端口被占用 (Linux/Windows)
                    logging.error(f"HTTP端口被占用，尝试释放...")
                    # Windows版本的端口释放
                    try:
                        import subprocess
                        result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
                        for line in result.stdout.split('\n'):
                            if f':{self.http_port}' in line and 'LISTENING' in line:
                                parts = line.split()
                                if len(parts) >= 5:
                                    pid = parts[-1]
                                    try:
                                        subprocess.run(['taskkill', '/F', '/PID', pid], check=True)
                                        logging.info(f"已终止占用端口的进程 PID: {pid}")
                                    except subprocess.CalledProcessError:
                                        pass
                    except Exception:
                        pass
                    time.sleep(5)
                else:
                    logging.error(f"HTTP服务器OSError: {e}")
                    time.sleep(10)  # 增加等待时间
                
            except Exception as e:
                consecutive_failures += 1
                logging.error(f"HTTP服务器异常: {e}")
                time.sleep(10)  # 增加等待时间
            
            # 检查连续失败次数
            if consecutive_failures >= max_consecutive_failures:
                logging.error(f"HTTP服务器连续失败{consecutive_failures}次，暂停重启60秒")
                time.sleep(60)  # 等待60秒后重置计数
                consecutive_failures = 0
            
            # 如果不是正常关闭，等待一段时间后重启
            if self.running:
                wait_time = min(5 + consecutive_failures * 2, 30)  # 递增等待时间
                logging.info(f"等待{wait_time}秒后重启HTTP服务器...")
                time.sleep(wait_time)
        
        logging.info("HTTP服务器线程退出")
    
    def create_http_server(self):
        tunnel_server = self
        
        class TunnelHttpHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.handle_request()
                
            def do_POST(self):
                self.handle_request()
                
            def handle_request(self):
                # 特殊处理：如果是根路径请求且没有隧道，返回服务器状态信息
                if self.path == "/" and not tunnel_server.tunnels:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    status_info = f"隧道服务器运行中\n当前活跃隧道数: {len(tunnel_server.tunnels)}\n"
                    self.wfile.write(status_info.encode('utf-8'))
                    return
                
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
                
                # 在发送请求前记录开始时间
                start_time = time.time()
                logging.info(f"开始爬虫任务 (请求ID: {tunnel_id})")
                
                # 发送请求到客户端并等待响应
                response = tunnel_server.forward_request_to_client(tunnel_id, request_data)
                
                if response:
                    elapsed = time.time() - start_time
                    logging.info(f"爬虫任务完成 (请求ID: {tunnel_id})，耗时: {elapsed:.1f}秒")
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
                        is_binary = resp_data.get("is_binary", False)
                        
                        # 对于文本内容，确保Content-Type指定了字符集
                        if not is_binary and "Content-Type" in headers and "charset" not in headers["Content-Type"]:
                            if "text/html" in headers["Content-Type"]:
                                headers["Content-Type"] = "text/html; charset=utf-8"
                            elif "text/plain" in headers["Content-Type"]:
                                headers["Content-Type"] = "text/plain; charset=utf-8"
                        
                        # 发送响应
                        logging.info(f"发送响应: 状态码 {status_code}, 二进制: {is_binary}")
                        self.send_response(status_code)
                        for name, value in headers.items():
                            self.send_header(name, value)
                        self.end_headers()
                        
                        if body:
                            if is_binary:
                                # 对于二进制数据，从base64解码后发送
                                import base64
                                binary_data = base64.b64decode(body)
                                self.wfile.write(binary_data)
                                logging.info(f"二进制响应体已发送，长度: {len(binary_data)}")
                            else:
                                # 对于文本数据，以UTF-8编码发送
                                self.wfile.write(body.encode('utf-8', errors='replace'))
                                logging.info(f"文本响应体已发送，长度: {len(body)}")
                        
                    except Exception as e:
                        logging.error(f"解析响应数据失败: {e}")
                        # 如果无法解析JSON，则直接返回原始响应
                        self.send_response(200)
                        self.send_header("Content-Type", "text/plain; charset=utf-8")
                        self.end_headers()
                        self.wfile.write(("解析响应失败: " + str(e)).encode('utf-8'))
                else:
                    elapsed = time.time() - start_time
                    logging.warning(f"爬虫任务失败 (请求ID: {tunnel_id})，耗时: {elapsed:.1f}秒")
                    self.send_error(502, "无法从内网服务获取响应")
            
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
            message_json = json.dumps(request_msg) + '\n'
            client_socket.sendall(message_json.encode('utf-8'))
            
            # 等待响应，针对爬虫程序延长超时时间
            logging.info(f"等待客户端爬虫响应 (请求ID: {request_id})，最长等待5分钟")
            if response_event.wait(300):  # 5分钟超时
                logging.info(f"收到爬虫响应事件通知 (请求ID: {request_id})")
                _, response = self.pending_requests.pop(request_id, (None, None))
                if response:
                    logging.info(f"收到客户端响应 (请求ID: {request_id}, 类型: {response.get('type')})")
                    return response
                else:
                    logging.warning(f"响应数据为空 (请求ID: {request_id})")
                    return None
            else:
                # 超时
                logging.warning(f"等待客户端爬虫响应超时 (请求ID: {request_id}, 5分钟)")
                self.pending_requests.pop(request_id, None)
                return None
                
        except Exception as e:
            logging.error(f"转发请求错误: {e}")
            self.pending_requests.pop(request_id, None)
            # 连接出错时清理隧道
            self.cleanup_tunnel(tunnel_id)
            return None
    
    def stop(self):
        """优雅关闭服务器"""
        logging.info("正在停止服务器...")
        self.running = False
        self.shutdown_event.set()
        
        # 关闭HTTP服务器
        if hasattr(self, 'http_server_instance') and self.http_server_instance:
            try:
                self.http_server_instance.shutdown()
                self.http_server_instance.server_close()
                logging.info("HTTP服务器已关闭")
            except Exception as e:
                logging.warning(f"关闭HTTP服务器时出错: {e}")
        
        # 关闭控制服务器
        if self.control_server_socket:
            try:
                self.control_server_socket.close()
                logging.info("控制服务器socket已关闭")
            except Exception as e:
                logging.warning(f"关闭控制服务器时出错: {e}")
        
        # 关闭所有客户端连接
        for tunnel_id, client_socket in list(self.tunnels.items()):
            try:
                client_socket.close()
                logging.debug(f"已关闭隧道 {tunnel_id}")
            except Exception as e:
                logging.warning(f"关闭隧道 {tunnel_id} 时出错: {e}")
        
        # 清理数据结构
        self.tunnels.clear()
        self.domain_tunnels.clear()
        self.pending_requests.clear()
        self.client_last_seen.clear()
        
        logging.info("服务器停止完成")


    # 添加一个新方法用于注册子域名
    def register_subdomain(self, subdomain, tunnel_id):
        self.domain_tunnels[subdomain] = tunnel_id
        logging.info(f"子域名 {subdomain} 已映射到隧道 {tunnel_id}")
        # 打印当前所有子域名映射，用于调试
        logging.info(f"当前子域名映射: {self.domain_tunnels}")



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

    def _start_connection_monitor(self):
        """启动连接监控"""
        def monitor_connections():
            while self.running and not self.shutdown_event.is_set():
                try:
                    current_time = time.time()
                    
                    # 清理僵尸连接
                    dead_tunnels = []
                    for tunnel_id, client_socket in list(self.tunnels.items()):
                        last_seen = self.client_last_seen.get(tunnel_id, current_time)
                        idle_time = current_time - last_seen
                        
                        # 检查是否有正在处理的请求
                        has_pending_requests = any(
                            req_id for req_id in self.pending_requests.keys()
                            if req_id.startswith(tunnel_id)  # 简化检查
                        )
                        
                        # 如果有正在处理的请求，延长检测时间
                        timeout_threshold = 600 if has_pending_requests else self.heartbeat_timeout
                        
                        if idle_time > timeout_threshold:
                            try:
                                # 尝试发送一个ping消息来检测连接
                                ping_timestamp = current_time
                                ping_msg = {"type": "ping", "timestamp": ping_timestamp}
                                ping_json = json.dumps(ping_msg) + '\n'
                                client_socket.sendall(ping_json.encode('utf-8'))
                                logging.debug(f"向隧道 {tunnel_id} 发送ping检测消息")
                                
                                # 等待一小段时间让客户端响应
                                time.sleep(2)
                                
                                # 检查是否有响应（通过检查最后活跃时间是否更新）
                                new_last_seen = self.client_last_seen.get(tunnel_id, last_seen)
                                if new_last_seen <= last_seen:
                                    # 没有收到响应，可能是僵尸连接
                                    logging.warning(f"检测到僵尸隧道: {tunnel_id} (ping无响应)")
                                    dead_tunnels.append(tunnel_id)
                                else:
                                    logging.debug(f"隧道 {tunnel_id} ping检测正常")
                                    
                            except Exception as e:
                                # 发送失败，标记为死连接
                                logging.warning(f"检测到僵尸隧道: {tunnel_id} (ping发送失败: {e})")
                                dead_tunnels.append(tunnel_id)
                    
                    # 清理僵尸连接
                    for tunnel_id in dead_tunnels:
                        self.cleanup_tunnel(tunnel_id)
                    
                    # 统计当前连接数
                    connection_count = len(self.tunnels)
                    if connection_count > 0:
                        logging.info(f"当前活跃隧道数: {connection_count}")
                        
                        # 列出所有活跃隧道（只在调试模式下显示详细信息）
                        tunnel_info = []
                        for tunnel_id in self.tunnels:
                            last_seen = self.client_last_seen.get(tunnel_id, current_time)
                            idle_time = current_time - last_seen
                            if idle_time < 0 or idle_time > 365 * 24 * 3600:
                                formatted_time = "未知"
                                self.client_last_seen[tunnel_id] = current_time
                            else:
                                formatted_time = self.format_time_duration(idle_time)
                            tunnel_info.append(f"{tunnel_id}(空闲{formatted_time})")
                        logging.debug(f"活跃隧道: {', '.join(tunnel_info)}")
                    
                    # 检查系统资源
                    try:
                        import psutil
                        process = psutil.Process(os.getpid())
                        mem_info = process.memory_info()
                        logging.debug(f"内存使用: {mem_info.rss / 1024 / 1024:.1f} MB")
                    except ImportError:
                        pass  # psutil不可用时跳过内存检查
                    
                    # 等待60秒或关闭事件
                    if self.shutdown_event.wait(60):
                        break
                except Exception as e:
                    logging.error(f"监控错误: {e}")
                    if self.shutdown_event.wait(60):
                        break
        
        monitor_thread = threading.Thread(target=monitor_connections, name="ConnectionMonitor")
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
