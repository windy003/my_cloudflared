#!/usr/bin/env python3

"""
启动带监控的隧道服务器
"""

import sys
import argparse
import logging
from server import TunnelServer

def main():
    print("🚀 启动隧道服务器 (带Web监控)")
    
    parser = argparse.ArgumentParser(description="内网穿透服务器 (带Web监控)")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址")
    parser.add_argument("--control-port", type=int, default=8000, help="控制服务器端口")
    parser.add_argument("--http-port", type=int, default=80, help="HTTP服务器端口")
    parser.add_argument("--no-ssl", action="store_true", help="禁用SSL")
    parser.add_argument("--cert", help="SSL证书文件")
    parser.add_argument("--key", help="SSL密钥文件")
    parser.add_argument("--admin-port", type=int, default=8001, help="Web管理界面端口")
    
    args = parser.parse_args()
    
    # 如果启用SSL，则需要提供证书和密钥文件
    if not args.no_ssl and (not args.cert or not args.key):
        print("❌ 启用SSL时需要提供--cert和--key参数")
        parser.print_help()
        sys.exit(1)
    
    print(f"📊 Web监控界面将启动在: http://{args.host}:{args.admin_port}")
    print(f"🌐 HTTP服务器将启动在: {'https' if not args.no_ssl else 'http'}://{args.host}:{args.http_port}")
    print(f"🔧 控制服务器将启动在: {args.host}:{args.control_port}")
    
    server = TunnelServer(
        args.host,
        args.control_port,
        args.http_port,
        not args.no_ssl,
        args.cert,
        args.key
    )
    
    try:
        print("\n✅ 服务器启动中...")
        server.start()
    except KeyboardInterrupt:
        print("\n⏹️  正在停止服务器...")
        server.stop()
        print("👋 服务器已停止")

if __name__ == "__main__":
    main()