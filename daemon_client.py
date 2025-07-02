#!/usr/bin/env python3
"""
守护进程版本的隧道客户端
提供更强的错误恢复和自动重连机制
"""

import os
import sys
import time
import signal
import logging
import threading
import traceback
from datetime import datetime
from client import TunnelClient
from logger import setup_logger, ErrorHandler

class DaemonTunnelClient:
    def __init__(self, server_host, server_port, local_host, local_port, 
                 tunnel_id=None, subdomain=None, use_ssl=True):
        self.server_host = server_host
        self.server_port = server_port
        self.local_host = local_host
        self.local_port = local_port
        self.tunnel_id = tunnel_id
        self.subdomain = subdomain
        self.use_ssl = use_ssl
        
        # 守护进程状态
        self.daemon_running = True
        self.client_instance = None
        self.restart_count = 0
        self.max_restart_count = 100  # 客户端可以重启更多次
        self.restart_delay = 5
        self.max_restart_delay = 180  # 最大重启延迟（3分钟）
        
        # 错误处理
        self.logger = setup_logger('daemon_client', 'logs/daemon_client.log')
        self.error_handler = ErrorHandler(self.logger)
        
        # 连接状态监控
        self.last_successful_connection = time.time()
        self.connection_timeout = 300  # 5分钟连接超时
        self.check_interval = 30  # 30秒检查一次
        
        # 本地服务检查
        self.local_service_check_interval = 60  # 1分钟检查一次本地服务
        
        # 设置信号处理
        self.setup_signal_handlers()
        
        # 启动监控线程
        self.start_monitoring_threads()
    
    def setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            self.logger.info(f"收到信号 {signum}, 正在优雅关闭...")
            self.daemon_running = False
            if self.client_instance:
                self.client_instance.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGHUP, self.reload_handler)
    
    def reload_handler(self, signum, frame):
        """重载配置处理器"""
        self.logger.info("收到重载信号，重启客户端...")
        if self.client_instance:
            self.client_instance.stop()
            time.sleep(2)
        self.start_client()
    
    def start_monitoring_threads(self):
        """启动监控线程"""
        # 连接状态监控线程
        connection_thread = threading.Thread(target=self.connection_monitor_loop)
        connection_thread.daemon = True
        connection_thread.start()
        
        # 本地服务检查线程
        local_service_thread = threading.Thread(target=self.local_service_monitor_loop)
        local_service_thread.daemon = True
        local_service_thread.start()
        
        # 网络连通性检查线程
        network_thread = threading.Thread(target=self.network_monitor_loop)
        network_thread.daemon = True
        network_thread.start()
    
    def start_client(self):
        """启动客户端实例"""
        try:
            self.logger.info(f"启动客户端实例 (第 {self.restart_count + 1} 次)")
            
            self.client_instance = TunnelClient(
                self.server_host, self.server_port, self.local_host, self.local_port,
                self.tunnel_id, self.subdomain, self.use_ssl
            )
            
            # 在新线程中启动客户端
            client_thread = threading.Thread(target=self.run_client)
            client_thread.daemon = True
            client_thread.start()
            
            # 等待客户端启动
            time.sleep(3)
            
            self.restart_count = 0  # 重置重启计数
            self.last_successful_connection = time.time()
            self.logger.info("客户端启动成功")
            return True
                
        except Exception as e:
            self.error_handler.handle_exception(e, "启动客户端")
            return False
    
    def run_client(self):
        """运行客户端实例"""
        try:
            self.client_instance.start()
        except Exception as e:
            self.error_handler.handle_exception(e, "运行客户端")
            self.client_instance = None
    
    def is_local_service_available(self):
        """检查本地服务是否可用"""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((self.local_host, self.local_port))
            sock.close()
            return result == 0
        except Exception as e:
            self.logger.warning(f"本地服务检查失败: {e}")
            return False
    
    def is_server_reachable(self):
        """检查服务器是否可达"""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            result = sock.connect_ex((self.server_host, self.server_port))
            sock.close()
            return result == 0
        except Exception as e:
            self.logger.warning(f"服务器连通性检查失败: {e}")
            return False
    
    def connection_monitor_loop(self):
        """连接状态监控循环"""
        while self.daemon_running:
            try:
                current_time = time.time()
                
                # 检查客户端实例是否存在
                if not self.client_instance:
                    self.logger.warning("客户端实例丢失，尝试重启")
                    self.restart_client("客户端实例丢失")
                
                # 检查连接超时
                elif current_time - self.last_successful_connection > self.connection_timeout:
                    self.logger.warning("连接超时，尝试重启客户端")
                    self.restart_client("连接超时")
                
                # 检查客户端是否还在运行
                elif hasattr(self.client_instance, 'running') and not self.client_instance.running:
                    self.logger.warning("客户端已停止运行，尝试重启")
                    self.restart_client("客户端停止运行")
                
                time.sleep(self.check_interval)
                
            except Exception as e:
                self.error_handler.handle_exception(e, "连接监控循环")
                time.sleep(self.check_interval)
    
    def local_service_monitor_loop(self):
        """本地服务监控循环"""
        while self.daemon_running:
            try:
                if not self.is_local_service_available():
                    self.logger.warning(f"本地服务 {self.local_host}:{self.local_port} 不可用")
                else:
                    # 本地服务可用，更新成功连接时间
                    self.last_successful_connection = time.time()
                
                time.sleep(self.local_service_check_interval)
                
            except Exception as e:
                self.error_handler.handle_exception(e, "本地服务监控")
                time.sleep(self.local_service_check_interval)
    
    def network_monitor_loop(self):
        """网络连通性监控循环"""
        while self.daemon_running:
            try:
                if not self.is_server_reachable():
                    self.logger.warning(f"服务器 {self.server_host}:{self.server_port} 不可达")
                else:
                    # 服务器可达，更新成功连接时间
                    self.last_successful_connection = time.time()
                
                time.sleep(60)  # 每分钟检查一次网络连通性
                
            except Exception as e:
                self.error_handler.handle_exception(e, "网络监控")
                time.sleep(60)
    
    def restart_client(self, reason="未知原因"):
        """重启客户端"""
        self.restart_count += 1
        
        if self.restart_count > self.max_restart_count:
            self.logger.error(f"重启次数超过限制 ({self.max_restart_count})，停止守护进程")
            self.daemon_running = False
            return
        
        self.logger.info(f"重启客户端: {reason} (第 {self.restart_count} 次)")
        
        # 停止当前客户端
        if self.client_instance:
            try:
                self.client_instance.stop()
                time.sleep(2)
            except:
                pass
            self.client_instance = None
        
        # 计算重启延迟（指数退避）
        delay = min(self.restart_delay * (2 ** min(self.restart_count - 1, 5)), self.max_restart_delay)
        self.logger.info(f"等待 {delay} 秒后重启...")
        time.sleep(delay)
        
        # 检查本地服务是否可用
        if not self.is_local_service_available():
            self.logger.error(f"本地服务 {self.local_host}:{self.local_port} 不可用，延迟重启")
            time.sleep(30)  # 额外等待30秒
        
        # 启动新的客户端实例
        if not self.start_client():
            self.logger.error("客户端重启失败，将在下次循环中重试")
    
    def run(self):
        """主运行循环"""
        self.logger.info("客户端守护进程启动")
        
        # 创建PID文件
        self.create_pid_file()
        
        try:
            # 首次启动客户端
            if not self.start_client():
                self.logger.error("初始启动失败")
                return 1
            
            # 主守护循环
            while self.daemon_running:
                try:
                    time.sleep(10)
                    
                except KeyboardInterrupt:
                    self.logger.info("收到中断信号，正在停止...")
                    break
                except Exception as e:
                    self.error_handler.handle_exception(e, "主循环")
                    time.sleep(10)
            
        finally:
            self.cleanup()
        
        self.logger.info("客户端守护进程退出")
        return 0
    
    def create_pid_file(self):
        """创建PID文件"""
        try:
            with open("/tmp/tunnel_client_daemon.pid", "w") as f:
                f.write(str(os.getpid()))
            self.logger.info(f"PID文件已创建: {os.getpid()}")
        except:
            pass
    
    def cleanup(self):
        """清理资源"""
        try:
            if self.client_instance:
                self.client_instance.stop()
            
            # 删除PID文件
            try:
                os.remove("/tmp/tunnel_client_daemon.pid")
            except:
                pass
            
            self.logger.info("资源清理完成")
        except Exception as e:
            self.error_handler.handle_exception(e, "清理资源")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="守护进程版隧道客户端")
    parser.add_argument("--server", required=True, help="服务器地址")
    parser.add_argument("--server-port", type=int, default=8000, help="服务器控制端口")
    parser.add_argument("--local", default="127.0.0.1", help="本地服务地址")
    parser.add_argument("--local-port", type=int, required=True, help="本地服务端口")
    parser.add_argument("--tunnel-id", help="隧道ID")
    parser.add_argument("--subdomain", help="子域名")
    parser.add_argument("--no-ssl", action="store_true", help="禁用SSL")
    parser.add_argument("--daemon", action="store_true", help="后台运行")
    
    args = parser.parse_args()
    
    # 检查参数
    if not args.tunnel_id and not args.subdomain:
        print("错误：必须提供 --tunnel-id 或 --subdomain 参数中的至少一个")
        return 1
    
    # 创建守护进程
    daemon = DaemonTunnelClient(
        args.server, args.server_port, args.local, args.local_port,
        args.tunnel_id, args.subdomain, not args.no_ssl
    )
    
    # 后台运行选项
    if args.daemon:
        if os.fork() > 0:
            sys.exit(0)  # 父进程退出
        
        os.setsid()  # 创建新会话
        
        if os.fork() > 0:
            sys.exit(0)  # 第二个父进程退出
        
        # 重定向标准输入输出
        sys.stdin.close()
        sys.stdout.close()
        sys.stderr.close()
    
    return daemon.run()

if __name__ == "__main__":
    sys.exit(main())