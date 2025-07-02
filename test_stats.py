#!/usr/bin/env python3

"""
测试统计功能的脚本
"""

import time
from stats import tunnel_stats

def test_stats():
    print("🧪 开始测试统计功能...")
    
    # 模拟连接事件
    print("📡 模拟隧道连接...")
    tunnel_stats.record_connection("test_tunnel_1", "192.168.1.100", "connect")
    tunnel_stats.record_connection("test_tunnel_2", "192.168.1.101", "connect") 
    
    time.sleep(1)
    
    # 模拟请求事件
    print("🌐 模拟HTTP请求...")
    tunnel_stats.record_request("test_tunnel_1", "GET", "/api/test", 1024, False)
    tunnel_stats.record_request("test_tunnel_1", "POST", "/api/data", 2048, False)
    tunnel_stats.record_request("test_tunnel_2", "GET", "/", 512, False)
    tunnel_stats.record_request("test_tunnel_1", "GET", "/error", 0, True)  # 错误请求
    
    # 获取统计数据
    stats = tunnel_stats.get_stats()
    
    print("\n📊 统计数据:")
    print(f"- 活跃连接数: {stats['active_connections']}")
    print(f"- 总连接数: {stats['total_connections']}")
    print(f"- 总请求数: {stats['total_requests']}")
    print(f"- 传输字节: {stats['total_bytes_sent']}")
    print(f"- 错误次数: {stats['error_count']}")
    print(f"- 隧道数量: {stats['tunnel_count']}")
    
    print("\n🚇 隧道详情:")
    for tunnel_id, tunnel_data in stats['tunnels'].items():
        print(f"  {tunnel_id}:")
        print(f"    - 请求数: {tunnel_data['requests']}")
        print(f"    - 传输量: {tunnel_data['bytes_sent']} bytes")
        print(f"    - 错误数: {tunnel_data['errors']}")
        print(f"    - 状态: {tunnel_data['status']}")
    
    print("\n✅ 测试完成！现在可以在 http://localhost:8001 查看Web界面")

if __name__ == "__main__":
    test_stats()