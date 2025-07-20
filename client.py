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
        "tunnel_client.log", 
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,         # 保留3个备份
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

# 设置Windows环境下的标准输出编码为UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
elif hasattr(sys.stdout, 'buffer'):
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

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
        self.max_reconnect_attempts = 999  # 无限重连
        self.successful_connections = 0  # 成功连接次数
        self.last_successful_time = None  # 最后一次成功连接时间
        self.last_heartbeat_received = time.time()  # 最后收到心跳的时间
        self.heartbeat_timeout = 180  # 心跳超时时间增加到3分钟
        self.heartbeat_thread = None
        self.message_handler_thread = None
        self.connection_lock = threading.Lock()  # 连接锁
        self.shutdown_event = threading.Event()  # 优雅关闭事件
        self.memory_cleanup_counter = 0  # 内存清理计数器
        
        # 注册信号处理器
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """处理信号，优雅关闭"""
        logging.info(f"收到信号 {signum}，开始优雅关闭...")
        self.stop()
        
    def start(self):
        self.running = True
        self.shutdown_event.clear()
        logging.info("客户端启动中...")
        self.connect_to_server()
        
    def connect_to_server(self):
        while self.running and not self.shutdown_event.is_set():
            try:
                with self.connection_lock:
                    # 重连时生成新的隧道ID（保留子域名）
                    if self.reconnect_attempts > 0:
                        base_id = self.subdomain if self.subdomain else "tunnel"
                        self.tunnel_id = f"{base_id}_{int(time.time())}"
                        logging.info(f"重连使用新隧道ID: {self.tunnel_id}")
                    
                    # 清理之前的连接
                    self._cleanup_connection()
                    
                    # 创建到服务器的控制连接
                    logging.info(f"正在连接到服务器 {self.server_host}:{self.server_port}...")
                    
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    
                    # 设置socket选项提高稳定性
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    
                    # 设置keepalive参数（Windows兼容）
                    if hasattr(socket, 'TCP_KEEPIDLE'):
                        try:
                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
                        except OSError:
                            # Windows上可能不支持这些选项
                            pass
                    
                    sock.settimeout(30)  # 连接超时30秒
                    
                    try:
                        if self.use_ssl:
                            # 创建SSL上下文
                            context = ssl.create_default_context()
                            context.check_hostname = False
                            context.verify_mode = ssl.CERT_NONE
                            context.minimum_version = ssl.TLSVersion.TLSv1_2
                            context.maximum_version = ssl.TLSVersion.TLSv1_3
                            # 包装为SSL连接
                            sock = context.wrap_socket(sock, server_hostname=self.server_host)
                        
                        # 尝试连接
                        sock.connect((self.server_host, self.server_port))
                        
                        # 连接成功后设置socket参数（Windows兼容）
                        if hasattr(socket, 'TCP_KEEPIDLE'):
                            try:
                                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
                                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
                                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 6)
                            except OSError:
                                # Windows上可能不支持这些选项
                                pass
                        
                        logging.info("成功连接到服务器")
                        
                        # 连接成功后重置超时设置
                        sock.settimeout(None)
                        self.control_socket = sock
                        
                        # 发送注册信息
                        if not self._register_with_server():
                            logging.error("注册失败，重新连接")
                            continue
                        
                        # 连接成功，重置重连参数并记录成功连接
                        self.successful_connections += 1
                        self.last_successful_time = time.time()
                        self.reconnect_delay = 5
                        self.reconnect_attempts = 0
                        self.last_heartbeat_received = time.time()
                        logging.info(f"连接成功 (第{self.successful_connections}次成功连接)")
                        
                        # 输出当前状态信息
                        logging.info(f"隧道已建立: {self.tunnel_id}")
                        if self.subdomain:
                            logging.info(f"访问地址: https://{self.subdomain}.windy.run")
                        
                        # 启动心跳线程
                        self._start_heartbeat_thread()
                        
                        # 启动消息处理线程
                        self._start_message_handler_thread()
                        
                        # 等待连接断开
                        self._wait_for_disconnection()
                        
                    except (socket.error, ssl.SSLError) as e:
                        logging.error(f"连接失败: {e}")
                        if self.control_socket:
                            try:
                                self.control_socket.close()
                            except:
                                pass
                            self.control_socket = None
                        
            except Exception as e:
                logging.error(f"连接过程错误: {e}")
                
            finally:
                self._cleanup_connection()
                
            # 如果仍在运行，准备重连
            if self.running and not self.shutdown_event.is_set():
                self.reconnect_attempts += 1
                
                # 智能重连算法
                current_delay = self._calculate_reconnect_delay()
                
                logging.info(f"第 {self.reconnect_attempts} 次重连失败，将在 {current_delay} 秒后重试")
                if self.shutdown_event.wait(current_delay):
                    break  # 收到关闭信号
    
    def _register_with_server(self):
        """向服务器注册"""
        try:
            registration = {
                "type": "register",
                "tunnel_id": self.tunnel_id
            }
            
            # 如果设置了子域名，添加到注册信息中
            if self.subdomain:
                registration["subdomain"] = self.subdomain
            
            registration_json = json.dumps(registration) + '\n'
            logging.info(f"发送注册消息: {registration}")
            
            self.control_socket.sendall(registration_json.encode('utf-8'))
            logging.info("注册消息已发送，等待服务器响应...")
            
            # 等待一下确保注册处理完成
            time.sleep(1)
            return True
            
        except Exception as e:
            logging.error(f"注册失败: {e}")
            return False
    
    def _start_heartbeat_thread(self):
        """启动心跳线程"""
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            return
            
        def heartbeat_worker():
            heartbeat_interval = 20  # 20秒发送一次心跳（提高检测频率）
            heartbeat_count = 0
            
            logging.info(f"心跳线程启动，间隔: {heartbeat_interval}秒")
            
            while self.running and not self.shutdown_event.is_set() and self.control_socket:
                try:
                    # 检查心跳超时
                    current_time = time.time()
                    if current_time - self.last_heartbeat_received > 60:  # 60秒心跳超时
                        logging.warning(f"心跳超时，最后心跳时间: {self.last_heartbeat_received}, 当前时间: {current_time}")
                        break
                    
                    # 发送心跳
                    heartbeat_count += 1
                    heartbeat = {
                        "type": "heartbeat", 
                        "timestamp": current_time,
                        "count": heartbeat_count
                    }
                    
                    if self._send_message_safe(heartbeat):
                        logging.debug(f"发送心跳消息 #{heartbeat_count}")
                    else:
                        logging.error("心跳发送失败")
                        break
                    
                    # 内存清理检查
                    self.memory_cleanup_counter += 1
                    if self.memory_cleanup_counter % 10 == 0:  # 每10次心跳清理一次
                        self._perform_memory_cleanup()
                    
                    # 等待下次心跳或关闭事件
                    if self.shutdown_event.wait(heartbeat_interval):
                        break
                        
                except Exception as e:
                    logging.error(f"心跳线程错误: {e}")
                    break
            
            logging.info("心跳线程结束")
        
        self.heartbeat_thread = threading.Thread(target=heartbeat_worker)
        self.heartbeat_thread.daemon = True
        self.heartbeat_thread.start()
    
    def _start_message_handler_thread(self):
        """启动消息处理线程"""
        if self.message_handler_thread and self.message_handler_thread.is_alive():
            return
            
        def message_handler_worker():
            logging.info("消息处理线程启动")
            buffer = b''
            
            while self.running and not self.shutdown_event.is_set() and self.control_socket:
                try:
                    # 使用select检查socket可读性
                    ready, _, error = select.select([self.control_socket], [], [self.control_socket], 1)
                    
                    if error:
                        logging.error("Socket出现错误")
                        break
                    
                    if not ready:
                        continue  # 超时，继续循环
                    
                    # 接收数据
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
                                continue
                            
                except Exception as e:
                    logging.error(f"接收消息错误: {e}")
                    break
            
            logging.info("消息处理线程结束")
        
        self.message_handler_thread = threading.Thread(target=message_handler_worker)
        self.message_handler_thread.daemon = True
        self.message_handler_thread.start()
    
    def _wait_for_disconnection(self):
        """等待连接断开"""
        while self.running and not self.shutdown_event.is_set() and self.control_socket:
            # 检查线程状态
            if self.heartbeat_thread and not self.heartbeat_thread.is_alive():
                logging.warning("心跳线程已停止")
                break
                
            if self.message_handler_thread and not self.message_handler_thread.is_alive():
                logging.warning("消息处理线程已停止")
                break
            
            # 检查心跳超时
            if time.time() - self.last_heartbeat_received > self.heartbeat_timeout:
                logging.warning("心跳超时，准备重连")
                break
            
            time.sleep(1)
    
    def _cleanup_connection(self):
        """清理连接资源"""
        if self.control_socket:
            try:
                self.control_socket.close()
            except:
                pass
            self.control_socket = None
        
        # 等待线程结束
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=2)
            
        if self.message_handler_thread and self.message_handler_thread.is_alive():
            self.message_handler_thread.join(timeout=2)
    
    def _send_message_safe(self, message):
        """安全地发送消息到服务器"""
        try:
            if not self.control_socket:
                return False
            
            message_json = json.dumps(message)
            if not message_json.endswith('\n'):
                message_json += '\n'
            
            self.control_socket.sendall(message_json.encode('utf-8'))
            return True
        except Exception as e:
            logging.error(f"发送消息错误: {e}")
            return False
    
    def send_message(self, message):
        """安全地发送消息到服务器（向后兼容）"""
        return self._send_message_safe(message)
    
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
                logging.debug(f"收到服务器心跳消息，时间戳: {message.get('timestamp', 'N/A')}")
                self.last_heartbeat_received = time.time() # 更新最后收到心跳的时间
                # 发送心跳响应
                heartbeat_response = {
                    "type": "heartbeat_response",
                    "timestamp": time.time(),
                    "original_timestamp": message.get('timestamp')
                }
                self.send_message(heartbeat_response)
                logging.debug("发送心跳响应到服务器")
            elif message_type == "heartbeat_response":
                # 处理服务器的心跳响应
                server_time = message.get('server_time', 'N/A')
                server_timestamp = message.get('timestamp', 'N/A')
                self.last_heartbeat_received = time.time() # 更新最后收到心跳的时间
                logging.debug(f"收到服务器心跳响应，服务器时间: {server_time}，时间戳: {server_timestamp}")
            elif message_type == "ping":
                # 处理服务器的ping消息
                ping_timestamp = message.get('timestamp', 'N/A')
                self.last_heartbeat_received = time.time() # 更新最后收到心跳的时间
                logging.debug(f"收到服务器ping消息，时间戳: {ping_timestamp}")
                # 发送pong响应
                pong_response = {
                    "type": "pong",
                    "timestamp": time.time(),
                    "original_timestamp": ping_timestamp
                }
                self.send_message(pong_response)
                logging.debug(f"发送pong响应到服务器，原始时间戳: {ping_timestamp}")
            elif message_type == "pong":
                # 处理服务器的pong响应
                original_timestamp = message.get('original_timestamp', 'N/A')
                response_timestamp = message.get('timestamp', 'N/A')
                self.last_heartbeat_received = time.time() # 更新最后收到心跳的时间
                if original_timestamp != 'N/A' and response_timestamp != 'N/A':
                    try:
                        rtt = float(response_timestamp) - float(original_timestamp)
                        logging.info(f"收到服务器pong响应，往返时间: {rtt:.3f}秒")
                    except:
                        logging.debug(f"收到服务器pong响应，原始时间戳: {original_timestamp}")
                else:
                    logging.debug("收到服务器pong响应")
            else:
                logging.warning(f"收到未知类型的消息: {message_type}")
        except json.JSONDecodeError as e:
            logging.error(f"JSON解析错误: {e}, 消息内容: {message_str}")
        except Exception as e:
            logging.error(f"处理消息错误: {e}")
    
    def handle_request(self, request_id, data):
        local_socket = None
        start_time = time.time()
        
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
            local_socket.settimeout(30)  # 连接超时30秒
            local_socket.connect((self.local_host, self.local_port))
            
            # 连接成功后设置更长的数据传输超时
            local_socket.settimeout(300)  # 5分钟数据传输超时
            
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
            
            # 发送请求到本地爬虫服务
            if request_str:
                local_socket.sendall(request_str.encode('utf-8'))
            
            # 通知服务器开始爬虫任务
            self.send_progress_update(request_id, "开始爬虫任务")
            
            # 接收响应
            logging.info(f"等待本地服务响应")
            response = b""
            last_progress_time = time.time()
            timeout_count = 0
            max_timeouts = 10  # 最多允许10次超时
            
            while True:
                try:
                    current_time = time.time()
                    elapsed = int(current_time - start_time)
                    
                    # 每30秒发送一次进度更新
                    if current_time - last_progress_time > 30:
                        data_received = len(response)
                        self.send_progress_update(request_id, 
                            f"任务运行中... 已耗时{elapsed}秒，已接收数据{data_received}字节")
                        last_progress_time = current_time
                    
                    # 检查总运行时间
                    if elapsed > 600:  # 10分钟总超时
                        logging.warning(f"任务总超时，已运行{elapsed}秒")
                        self.send_progress_update(request_id, f"任务总超时，已运行{elapsed}秒")
                        break
                    
                    # 设置接收超时
                    local_socket.settimeout(30)
                    chunk = local_socket.recv(8192)  # 增加缓冲区大小
                    
                    if not chunk:
                        logging.info(f"本地服务连接关闭，总共接收{len(response)}字节")
                        break
                    response += chunk
                    timeout_count = 0  # 收到数据后重置超时计数
                    
                except socket.timeout:
                    elapsed = int(time.time() - start_time)
                    timeout_count += 1
                    
                    if timeout_count >= max_timeouts:
                        logging.warning(f"连续超时{max_timeouts}次，放弃等待，已运行{elapsed}秒")
                        self.send_progress_update(request_id, f"连续超时{max_timeouts}次，已运行{elapsed}秒")
                        break
                    else:
                        logging.debug(f"等待数据中... 已运行{elapsed}秒 (超时次数: {timeout_count}/{max_timeouts})")
                        continue
                except Exception as e:
                    logging.error(f"接收数据时出错: {e}")
                    break
            
            # 任务完成
            elapsed = int(time.time() - start_time)
            data_size = len(response)
            self.send_progress_update(request_id, f"任务完成，耗时{elapsed}秒，接收{data_size}字节")
            
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
            
            # 判断是否为二进制内容
            content_type = headers.get('Content-Type', '').lower()
            is_binary = any(binary_type in content_type for binary_type in [
                'image/', 'video/', 'audio/', 'application/octet-stream',
                'application/pdf', 'application/zip', 'font/'
            ])
            
            # 构建响应对象
            if is_binary:
                # 对于二进制数据，使用base64编码
                import base64
                response_obj = {
                    "status": status_code,
                    "headers": headers,
                    "body": base64.b64encode(body).decode('ascii'),
                    "is_binary": True
                }
            else:
                # 对于文本数据，正常解码
                response_obj = {
                    "status": status_code,
                    "headers": headers,
                    "body": body.decode('utf-8', errors='replace'),
                    "is_binary": False
                }
            
            return response_obj
        except Exception as e:
            logging.error(f"解析HTTP响应失败: {e}")
            # 返回简单响应格式
            return {
                "status": 200,
                "headers": {"Content-Type": "text/plain"},
                "body": response_bytes.decode('utf-8', errors='replace'),
                "is_binary": False
            }
    
    def stop(self):
        """优雅关闭客户端"""
        logging.info("正在停止客户端...")
        self.running = False
        self.shutdown_event.set()
        
        # 等待线程结束
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            logging.debug("等待心跳线程结束...")
            self.heartbeat_thread.join(timeout=3)
            
        if self.message_handler_thread and self.message_handler_thread.is_alive():
            logging.debug("等待消息处理线程结束...")
            self.message_handler_thread.join(timeout=3)
        
        # 关闭socket连接
        if self.control_socket:
            try:
                self.control_socket.close()
                logging.debug("控制连接已关闭")
            except:
                pass
            self.control_socket = None
        
        logging.info("客户端停止完成")
    
    def _calculate_reconnect_delay(self):
        """智能计算重连延迟时间"""
        current_time = time.time()
        
        # 优化的重连策略 - 更快的恢复
        if self.reconnect_attempts <= 3:
            base_delay = min(self.reconnect_delay * (self.reconnect_attempts), 15)  # 5, 10, 15秒
        elif self.reconnect_attempts <= 10:
            base_delay = 30  # 4-10次失败后30秒
        elif self.reconnect_attempts <= 30:
            base_delay = 60  # 11-30次失败后1分钟
        else:
            base_delay = 120  # 30次后固定2分钟，而不是5分钟
        
        # 如果有成功连接历史，考虑调整策略
        if self.last_successful_time and self.successful_connections > 0:
            time_since_last_success = current_time - self.last_successful_time
            
            # 如果最近连接过（1小时内），减少延迟
            if time_since_last_success < 3600:  # 1小时
                base_delay = min(base_delay, 30)
                logging.debug(f"最近连接成功过，减少重连延迟至{base_delay}秒")
            
            # 如果长时间没有连接成功（超过6小时），增加延迟
            elif time_since_last_success > 21600:  # 6小时
                base_delay = min(base_delay * 2, self.max_reconnect_delay)
                logging.debug(f"长时间连接失败，增加重连延迟至{base_delay}秒")
        
        # 连接成功率调整
        if self.successful_connections > 0:
            failure_rate = self.reconnect_attempts / (self.successful_connections + self.reconnect_attempts)
            if failure_rate > 0.8:  # 失败率超过80%
                base_delay = min(base_delay * 1.5, self.max_reconnect_delay)
                logging.debug(f"连接失败率较高({failure_rate:.2%})，增加延迟")
        
        return int(base_delay)
    
    def _perform_memory_cleanup(self):
        """执行内存清理操作"""
        try:
            import gc
            
            # 强制垃圾回收
            collected = gc.collect()
            
            # 检查内存使用情况
            try:
                import psutil
                process = psutil.Process()
                memory_info = process.memory_info()
                memory_mb = memory_info.rss / 1024 / 1024
                
                if memory_mb > 100:  # 如果内存使用超过100MB
                    logging.warning(f"内存使用较高: {memory_mb:.1f}MB，已清理{collected}个对象")
                else:
                    logging.debug(f"内存清理完成: {memory_mb:.1f}MB，清理{collected}个对象")
                    
            except ImportError:
                logging.debug(f"内存清理完成，清理{collected}个对象")
                
        except Exception as e:
            logging.error(f"内存清理失败: {e}")




    def send_progress_update(self, request_id, message):
        """发送进度更新到服务器"""
        try:
            progress_msg = {
                "type": "progress",
                "request_id": request_id,
                "message": message,
                "timestamp": time.time()
            }
            
            success = self.send_message(progress_msg)
            if success:
                logging.info(f"进度更新已发送: {message}")
            else:
                logging.warning(f"进度更新发送失败: {message}")
        except Exception as e:
            logging.error(f"发送进度更新错误: {e}")

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
