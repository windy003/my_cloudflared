#!/usr/bin/env python3
"""
隧道管理和监控脚本
用于启动、停止、监控隧道进程
"""

import os
import sys
import time
import signal
import psutil
import argparse
import subprocess
from datetime import datetime

class TunnelManager:
    """隧道管理器"""
    
    def __init__(self):
        self.server_pid_file = "/tmp/tunnel_daemon.pid"
        self.client_pid_file = "/tmp/tunnel_client_daemon.pid"
    
    def get_pid_from_file(self, pid_file):
        """从PID文件获取进程ID"""
        try:
            if os.path.exists(pid_file):
                with open(pid_file, 'r') as f:
                    pid = int(f.read().strip())
                
                # 检查进程是否存在
                if psutil.pid_exists(pid):
                    return pid
                else:
                    # PID文件过期，删除
                    os.remove(pid_file)
                    return None
        except:
            return None
        return None
    
    def is_service_running(self, service_type):
        """检查服务是否运行"""
        if service_type == "server":
            pid_file = self.server_pid_file
        elif service_type == "client":
            pid_file = self.client_pid_file
        else:
            return False
        
        pid = self.get_pid_from_file(pid_file)
        return pid is not None
    
    def get_service_status(self, service_type):
        """获取服务状态"""
        if service_type == "server":
            pid_file = self.server_pid_file
        elif service_type == "client":
            pid_file = self.client_pid_file
        else:
            return None
        
        pid = self.get_pid_from_file(pid_file)
        if pid is None:
            return {"status": "stopped", "pid": None}
        
        try:
            process = psutil.Process(pid)
            return {
                "status": "running",
                "pid": pid,
                "name": process.name(),
                "memory_mb": process.memory_info().rss / 1024 / 1024,
                "cpu_percent": process.cpu_percent(),
                "create_time": datetime.fromtimestamp(process.create_time()),
                "connections": len(process.connections())
            }
        except psutil.NoSuchProcess:
            return {"status": "stopped", "pid": None}
    
    def start_server(self, **kwargs):
        """启动服务器"""
        if self.is_service_running("server"):
            print("❌ 服务器已经在运行")
            return False
        
        # 构建启动命令
        cmd = [sys.executable, "daemon_server.py"]
        
        if kwargs.get('host'):
            cmd.extend(["--host", kwargs['host']])
        if kwargs.get('control_port'):
            cmd.extend(["--control-port", str(kwargs['control_port'])])
        if kwargs.get('http_port'):
            cmd.extend(["--http-port", str(kwargs['http_port'])])
        if kwargs.get('no_ssl'):
            cmd.append("--no-ssl")
        if kwargs.get('cert'):
            cmd.extend(["--cert", kwargs['cert']])
        if kwargs.get('key'):
            cmd.extend(["--key", kwargs['key']])
        if kwargs.get('daemon', True):
            cmd.append("--daemon")
        
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)  # 等待启动
            
            if self.is_service_running("server"):
                print("✅ 服务器启动成功")
                return True
            else:
                print("❌ 服务器启动失败")
                return False
        except Exception as e:
            print(f"❌ 启动服务器失败: {e}")
            return False
    
    def start_client(self, **kwargs):
        """启动客户端"""
        if self.is_service_running("client"):
            print("❌ 客户端已经在运行")
            return False
        
        # 构建启动命令
        cmd = [sys.executable, "daemon_client.py"]
        
        if kwargs.get('server'):
            cmd.extend(["--server", kwargs['server']])
        if kwargs.get('server_port'):
            cmd.extend(["--server-port", str(kwargs['server_port'])])
        if kwargs.get('local'):
            cmd.extend(["--local", kwargs['local']])
        if kwargs.get('local_port'):
            cmd.extend(["--local-port", str(kwargs['local_port'])])
        if kwargs.get('tunnel_id'):
            cmd.extend(["--tunnel-id", kwargs['tunnel_id']])
        if kwargs.get('subdomain'):
            cmd.extend(["--subdomain", kwargs['subdomain']])
        if kwargs.get('no_ssl'):
            cmd.append("--no-ssl")
        if kwargs.get('daemon', True):
            cmd.append("--daemon")
        
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)  # 等待启动
            
            if self.is_service_running("client"):
                print("✅ 客户端启动成功")
                return True
            else:
                print("❌ 客户端启动失败")
                return False
        except Exception as e:
            print(f"❌ 启动客户端失败: {e}")
            return False
    
    def stop_service(self, service_type):
        """停止服务"""
        pid = self.get_pid_from_file(
            self.server_pid_file if service_type == "server" else self.client_pid_file
        )
        
        if pid is None:
            print(f"❌ {service_type} 没有在运行")
            return False
        
        try:
            os.kill(pid, signal.SIGTERM)
            
            # 等待进程停止
            for _ in range(10):
                if not psutil.pid_exists(pid):
                    print(f"✅ {service_type} 已停止")
                    return True
                time.sleep(1)
            
            # 强制终止
            os.kill(pid, signal.SIGKILL)
            print(f"⚠️  {service_type} 已强制终止")
            return True
            
        except ProcessLookupError:
            print(f"✅ {service_type} 已停止")
            return True
        except Exception as e:
            print(f"❌ 停止 {service_type} 失败: {e}")
            return False
    
    def restart_service(self, service_type, **kwargs):
        """重启服务"""
        print(f"🔄 重启 {service_type}...")
        self.stop_service(service_type)
        time.sleep(2)
        
        if service_type == "server":
            return self.start_server(**kwargs)
        elif service_type == "client":
            return self.start_client(**kwargs)
        return False
    
    def show_status(self):
        """显示状态"""
        print("🌐 隧道服务状态")
        print("=" * 50)
        
        # 服务器状态
        server_status = self.get_service_status("server")
        if server_status["status"] == "running":
            print(f"🖥️  服务器: ✅ 运行中 (PID: {server_status['pid']})")
            print(f"   内存: {server_status['memory_mb']:.1f}MB")
            print(f"   CPU: {server_status['cpu_percent']:.1f}%")
            print(f"   启动时间: {server_status['create_time']}")
            print(f"   连接数: {server_status['connections']}")
        else:
            print("🖥️  服务器: ❌ 停止")
        
        print()
        
        # 客户端状态
        client_status = self.get_service_status("client")
        if client_status["status"] == "running":
            print(f"💻 客户端: ✅ 运行中 (PID: {client_status['pid']})")
            print(f"   内存: {client_status['memory_mb']:.1f}MB")
            print(f"   CPU: {client_status['cpu_percent']:.1f}%")
            print(f"   启动时间: {client_status['create_time']}")
            print(f"   连接数: {client_status['connections']}")
        else:
            print("💻 客户端: ❌ 停止")
        
        print()
        
        # 日志文件状态
        self.show_log_status()
    
    def show_log_status(self):
        """显示日志状态"""
        print("📝 日志文件状态")
        print("-" * 30)
        
        log_files = [
            "logs/daemon.log",
            "logs/daemon_client.log", 
            "tunnel_server.log",
            "tunnel_client.log"
        ]
        
        for log_file in log_files:
            if os.path.exists(log_file):
                stat = os.stat(log_file)
                size_mb = stat.st_size / 1024 / 1024
                mtime = datetime.fromtimestamp(stat.st_mtime)
                print(f"   {log_file}: {size_mb:.1f}MB (更新: {mtime.strftime('%Y-%m-%d %H:%M:%S')})")
            else:
                print(f"   {log_file}: 不存在")
    
    def monitor(self, interval=30):
        """监控模式"""
        print("🔍 开始监控模式 (Ctrl+C 退出)")
        print(f"   监控间隔: {interval} 秒")
        print()
        
        try:
            while True:
                os.system('clear')  # 清屏
                self.show_status()
                print(f"\n⏰ 下次更新: {interval} 秒后 (按 Ctrl+C 退出)")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n👋 监控退出")
    
    def show_logs(self, service_type, lines=50):
        """显示日志"""
        if service_type == "server":
            log_files = ["logs/daemon.log", "tunnel_server.log"]
        elif service_type == "client":
            log_files = ["logs/daemon_client.log", "tunnel_client.log"]
        else:
            print("❌ 无效的服务类型")
            return
        
        for log_file in log_files:
            if os.path.exists(log_file):
                print(f"\n📖 {log_file} (最后 {lines} 行):")
                print("-" * 60)
                try:
                    subprocess.run(["tail", "-n", str(lines), log_file])
                except:
                    # Windows环境备用方案
                    with open(log_file, 'r') as f:
                        lines_list = f.readlines()
                        for line in lines_list[-lines:]:
                            print(line.rstrip())
                print("-" * 60)

def main():
    parser = argparse.ArgumentParser(description="隧道管理工具")
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # 启动服务器
    server_parser = subparsers.add_parser('start-server', help='启动服务器')
    server_parser.add_argument('--host', default='0.0.0.0', help='绑定地址')
    server_parser.add_argument('--control-port', type=int, default=8000, help='控制端口')
    server_parser.add_argument('--http-port', type=int, default=80, help='HTTP端口')
    server_parser.add_argument('--no-ssl', action='store_true', help='禁用SSL')
    server_parser.add_argument('--cert', help='SSL证书文件')
    server_parser.add_argument('--key', help='SSL密钥文件')
    
    # 启动客户端
    client_parser = subparsers.add_parser('start-client', help='启动客户端')
    client_parser.add_argument('--server', required=True, help='服务器地址')
    client_parser.add_argument('--server-port', type=int, default=8000, help='服务器端口')
    client_parser.add_argument('--local', default='127.0.0.1', help='本地地址')
    client_parser.add_argument('--local-port', type=int, required=True, help='本地端口')
    client_parser.add_argument('--tunnel-id', help='隧道ID')
    client_parser.add_argument('--subdomain', help='子域名')
    client_parser.add_argument('--no-ssl', action='store_true', help='禁用SSL')
    
    # 停止服务
    subparsers.add_parser('stop-server', help='停止服务器')
    subparsers.add_parser('stop-client', help='停止客户端')
    subparsers.add_parser('stop-all', help='停止所有服务')
    
    # 重启服务
    restart_server_parser = subparsers.add_parser('restart-server', help='重启服务器')
    restart_server_parser.add_argument('--host', default='0.0.0.0')
    restart_server_parser.add_argument('--control-port', type=int, default=8000)
    restart_server_parser.add_argument('--http-port', type=int, default=80)
    restart_server_parser.add_argument('--no-ssl', action='store_true')
    restart_server_parser.add_argument('--cert')
    restart_server_parser.add_argument('--key')
    
    restart_client_parser = subparsers.add_parser('restart-client', help='重启客户端')
    restart_client_parser.add_argument('--server', required=True)
    restart_client_parser.add_argument('--server-port', type=int, default=8000)
    restart_client_parser.add_argument('--local', default='127.0.0.1')
    restart_client_parser.add_argument('--local-port', type=int, required=True)
    restart_client_parser.add_argument('--tunnel-id')
    restart_client_parser.add_argument('--subdomain')
    restart_client_parser.add_argument('--no-ssl', action='store_true')
    
    # 状态和监控
    subparsers.add_parser('status', help='显示状态')
    monitor_parser = subparsers.add_parser('monitor', help='监控模式')
    monitor_parser.add_argument('--interval', type=int, default=30, help='监控间隔(秒)')
    
    # 日志
    log_parser = subparsers.add_parser('logs', help='显示日志')
    log_parser.add_argument('service', choices=['server', 'client'], help='服务类型')
    log_parser.add_argument('--lines', type=int, default=50, help='显示行数')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    manager = TunnelManager()
    
    if args.command == 'start-server':
        manager.start_server(**vars(args))
    elif args.command == 'start-client':
        manager.start_client(**vars(args))
    elif args.command == 'stop-server':
        manager.stop_service('server')
    elif args.command == 'stop-client':
        manager.stop_service('client')
    elif args.command == 'stop-all':
        manager.stop_service('server')
        manager.stop_service('client')
    elif args.command == 'restart-server':
        manager.restart_service('server', **vars(args))
    elif args.command == 'restart-client':
        manager.restart_service('client', **vars(args))
    elif args.command == 'status':
        manager.show_status()
    elif args.command == 'monitor':
        manager.monitor(args.interval)
    elif args.command == 'logs':
        manager.show_logs(args.service, args.lines)

if __name__ == "__main__":
    main()