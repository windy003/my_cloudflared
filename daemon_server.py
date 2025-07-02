#!/usr/bin/env python3
"""
守护进程版本的隧道服务器
提供更强的错误恢复和自动重启机制
"""

import os
import sys
import time
import signal
import logging
import threading
import traceback
import subprocess
from datetime import datetime
from server import TunnelServer
from logger import setup_logger, ErrorHandler

class DaemonTunnelServer:
    def __init__(self, host="0.0.0.0", control_port=8000, http_port=80, 
                 use_ssl=False, cert_file=None, key_file=None):
        self.host = host
        self.control_port = control_port
        self.http_port = http_port
        self.use_ssl = use_ssl
        self.cert_file = cert_file
        self.key_file = key_file
        
        # 守护进程状态
        self.daemon_running = True
        self.server_instance = None
        self.restart_count = 0
        self.max_restart_count = 50  # 最大重启次数
        self.restart_delay = 5  # 重启延迟
        self.max_restart_delay = 300  # 最大重启延迟（5分钟）
        
        # 错误处理
        self.logger = setup_logger('daemon', 'logs/daemon.log')
        self.error_handler = ErrorHandler(self.logger)
        
        # 健康检查
        self.last_health_check = time.time()
        self.health_check_interval = 60  # 1分钟检查一次
        self.unhealthy_threshold = 3  # 连续3次检查失败则重启
        self.unhealthy_count = 0
        
        # 资源监控
        self.memory_threshold = 1024 * 1024 * 1024  # 1GB内存阈值
        self.cpu_threshold = 80  # CPU使用率阈值（%）
        
        # 设置信号处理
        self.setup_signal_handlers()
        
        # 启动监控线程
        self.start_monitoring_threads()
    
    def setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            self.logger.info(f"收到信号 {signum}, 正在优雅关闭...")
            self.daemon_running = False
            if self.server_instance:
                self.server_instance.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGHUP, self.reload_handler)
    
    def reload_handler(self, signum, frame):
        """重载配置处理器"""
        self.logger.info("收到重载信号，重启服务器...")
        if self.server_instance:
            self.server_instance.stop()
            time.sleep(2)
        self.start_server()
    
    def start_monitoring_threads(self):
        """启动监控线程"""
        # 健康检查线程
        health_thread = threading.Thread(target=self.health_check_loop)
        health_thread.daemon = True
        health_thread.start()
        
        # 资源监控线程
        resource_thread = threading.Thread(target=self.resource_monitor_loop)
        resource_thread.daemon = True
        resource_thread.start()
        
        # 日志清理线程
        cleanup_thread = threading.Thread(target=self.log_cleanup_loop)
        cleanup_thread.daemon = True
        cleanup_thread.start()
    
    def start_server(self):
        """启动服务器实例"""
        try:
            self.logger.info(f"启动服务器实例 (第 {self.restart_count + 1} 次)")
            
            self.server_instance = TunnelServer(
                self.host, self.control_port, self.http_port,
                self.use_ssl, self.cert_file, self.key_file
            )
            
            # 在新线程中启动服务器
            server_thread = threading.Thread(target=self.run_server)
            server_thread.daemon = True
            server_thread.start()
            
            # 等待服务器启动
            time.sleep(3)
            
            # 检查服务器是否成功启动
            if self.is_server_healthy():
                self.logger.info("服务器启动成功")
                self.restart_count = 0  # 重置重启计数
                self.unhealthy_count = 0  # 重置不健康计数
                return True
            else:
                self.logger.error("服务器启动失败，端口可能被占用")
                return False
                
        except Exception as e:
            self.error_handler.handle_exception(e, "启动服务器")
            return False
    
    def run_server(self):
        """运行服务器实例"""
        try:
            self.server_instance.start()
        except Exception as e:
            self.error_handler.handle_exception(e, "运行服务器")
            self.server_instance = None
    
    def is_server_healthy(self):
        """检查服务器健康状态"""
        try:
            if not self.server_instance:
                return False
            
            # 检查控制端口
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((self.host, self.control_port))
            sock.close()
            
            if result != 0:
                self.logger.warning(f"控制端口 {self.control_port} 不可达")
                return False
            
            # 检查HTTP端口
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((self.host, self.http_port))
            sock.close()
            
            if result != 0:
                self.logger.warning(f"HTTP端口 {self.http_port} 不可达")
                return False
            
            return True
            
        except Exception as e:
            self.error_handler.handle_exception(e, "健康检查")
            return False
    
    def health_check_loop(self):
        """健康检查循环"""
        while self.daemon_running:
            try:
                current_time = time.time()
                
                if current_time - self.last_health_check >= self.health_check_interval:
                    if self.server_instance and not self.is_server_healthy():
                        self.unhealthy_count += 1
                        self.logger.warning(f"健康检查失败 ({self.unhealthy_count}/{self.unhealthy_threshold})")
                        
                        if self.unhealthy_count >= self.unhealthy_threshold:
                            self.logger.error("服务器不健康，准备重启")
                            self.restart_server("健康检查失败")
                    else:
                        self.unhealthy_count = 0
                    
                    self.last_health_check = current_time
                
                time.sleep(10)  # 每10秒检查一次
                
            except Exception as e:
                self.error_handler.handle_exception(e, "健康检查循环")
                time.sleep(10)
    
    def resource_monitor_loop(self):
        """资源监控循环"""
        while self.daemon_running:
            try:
                import psutil
                process = psutil.Process(os.getpid())
                
                # 检查内存使用
                memory_info = process.memory_info()
                memory_mb = memory_info.rss / 1024 / 1024
                
                if memory_info.rss > self.memory_threshold:
                    self.logger.warning(f"内存使用过高: {memory_mb:.1f}MB")
                    self.restart_server("内存使用过高")
                
                # 检查CPU使用率
                cpu_percent = process.cpu_percent(interval=1)
                if cpu_percent > self.cpu_threshold:
                    self.logger.warning(f"CPU使用率过高: {cpu_percent:.1f}%")
                
                # 记录资源使用情况
                if int(time.time()) % 300 == 0:  # 每5分钟记录一次
                    self.logger.info(f"资源使用: 内存 {memory_mb:.1f}MB, CPU {cpu_percent:.1f}%")
                
                time.sleep(60)  # 每分钟检查一次
                
            except ImportError:
                # psutil未安装，跳过资源监控
                time.sleep(300)
            except Exception as e:
                self.error_handler.handle_exception(e, "资源监控")
                time.sleep(60)
    
    def log_cleanup_loop(self):
        """日志清理循环"""
        while self.daemon_running:
            try:
                # 每天清理一次日志
                log_dir = "logs"
                if os.path.exists(log_dir):
                    for filename in os.listdir(log_dir):
                        filepath = os.path.join(log_dir, filename)
                        if os.path.isfile(filepath):
                            # 删除7天前的日志文件
                            if os.path.getmtime(filepath) < time.time() - 7 * 24 * 3600:
                                try:
                                    os.remove(filepath)
                                    self.logger.info(f"清理旧日志文件: {filename}")
                                except:
                                    pass
                
                time.sleep(24 * 3600)  # 每天运行一次
                
            except Exception as e:
                self.error_handler.handle_exception(e, "日志清理")
                time.sleep(3600)  # 出错后1小时再试
    
    def restart_server(self, reason="未知原因"):
        """重启服务器"""
        self.restart_count += 1
        
        if self.restart_count > self.max_restart_count:
            self.logger.error(f"重启次数超过限制 ({self.max_restart_count})，停止守护进程")
            self.daemon_running = False
            return
        
        self.logger.info(f"重启服务器: {reason} (第 {self.restart_count} 次)")
        
        # 停止当前服务器
        if self.server_instance:
            try:
                self.server_instance.stop()
                time.sleep(2)
            except:
                pass
            self.server_instance = None
        
        # 计算重启延迟（指数退避）
        delay = min(self.restart_delay * (2 ** min(self.restart_count - 1, 6)), self.max_restart_delay)
        self.logger.info(f"等待 {delay} 秒后重启...")
        time.sleep(delay)
        
        # 启动新的服务器实例
        if not self.start_server():
            self.logger.error("服务器重启失败，将在下次循环中重试")
    
    def run(self):
        """主运行循环"""
        self.logger.info("守护进程启动")
        
        # 创建PID文件
        self.create_pid_file()
        
        try:
            # 首次启动服务器
            if not self.start_server():
                self.logger.error("初始启动失败")
                return 1
            
            # 主守护循环
            while self.daemon_running:
                try:
                    if not self.server_instance:
                        self.logger.warning("服务器实例丢失，尝试重启")
                        self.restart_server("服务器实例丢失")
                    
                    time.sleep(5)
                    
                except KeyboardInterrupt:
                    self.logger.info("收到中断信号，正在停止...")
                    break
                except Exception as e:
                    self.error_handler.handle_exception(e, "主循环")
                    time.sleep(5)
            
        finally:
            self.cleanup()
        
        self.logger.info("守护进程退出")
        return 0
    
    def create_pid_file(self):
        """创建PID文件"""
        try:
            with open("/tmp/tunnel_daemon.pid", "w") as f:
                f.write(str(os.getpid()))
            self.logger.info(f"PID文件已创建: {os.getpid()}")
        except:
            pass
    
    def cleanup(self):
        """清理资源"""
        try:
            if self.server_instance:
                self.server_instance.stop()
            
            # 删除PID文件
            try:
                os.remove("/tmp/tunnel_daemon.pid")
            except:
                pass
            
            self.logger.info("资源清理完成")
        except Exception as e:
            self.error_handler.handle_exception(e, "清理资源")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="守护进程版隧道服务器")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址")
    parser.add_argument("--control-port", type=int, default=8000, help="控制服务器端口")
    parser.add_argument("--http-port", type=int, default=80, help="HTTP服务器端口")
    parser.add_argument("--no-ssl", action="store_true", help="禁用SSL")
    parser.add_argument("--cert", help="SSL证书文件")
    parser.add_argument("--key", help="SSL密钥文件")
    parser.add_argument("--daemon", action="store_true", help="后台运行")
    
    args = parser.parse_args()
    
    # 检查SSL配置
    if not args.no_ssl and (not args.cert or not args.key):
        print("错误：启用SSL时需要提供--cert和--key参数")
        return 1
    
    # 创建守护进程
    daemon = DaemonTunnelServer(
        args.host, args.control_port, args.http_port,
        not args.no_ssl, args.cert, args.key
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