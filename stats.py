import time
import json
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta

class TunnelStats:
    def __init__(self):
        self.lock = threading.Lock()
        
        # 访问统计
        self.total_requests = 0
        self.total_bytes_sent = 0
        self.total_bytes_received = 0
        
        # 错误统计
        self.error_count = 0
        self.timeout_count = 0
        
        # 连接统计
        self.active_connections = 0
        self.total_connections = 0
        self.connection_history = deque(maxlen=1000)  # 保留最近1000次连接记录
        
        # 隧道统计
        self.tunnel_stats = defaultdict(lambda: {
            'requests': 0,
            'bytes_sent': 0,
            'bytes_received': 0,
            'errors': 0,
            'first_seen': None,
            'last_seen': None
        })
        
        # 时间窗口统计 (每分钟)
        self.minute_stats = deque(maxlen=60)  # 保留60分钟
        self.current_minute = {
            'timestamp': int(time.time() // 60) * 60,
            'requests': 0,
            'bytes': 0,
            'errors': 0
        }
        
        # 启动统计更新线程
        self.start_stats_updater()
    
    def record_request(self, tunnel_id, method, path, response_size=0, error=False):
        """记录请求统计"""
        with self.lock:
            current_time = time.time()
            
            # 更新总体统计
            self.total_requests += 1
            if response_size > 0:
                self.total_bytes_sent += response_size
            
            if error:
                self.error_count += 1
            
            # 更新隧道统计
            tunnel_stat = self.tunnel_stats[tunnel_id]
            tunnel_stat['requests'] += 1
            tunnel_stat['bytes_sent'] += response_size
            tunnel_stat['last_seen'] = current_time
            if tunnel_stat['first_seen'] is None:
                tunnel_stat['first_seen'] = current_time
            if error:
                tunnel_stat['errors'] += 1
            
            # 更新当前分钟统计
            current_minute_timestamp = int(current_time // 60) * 60
            if current_minute_timestamp != self.current_minute['timestamp']:
                # 保存上一分钟的统计
                self.minute_stats.append(self.current_minute.copy())
                # 开始新的一分钟
                self.current_minute = {
                    'timestamp': current_minute_timestamp,
                    'requests': 0,
                    'bytes': 0,
                    'errors': 0
                }
            
            # 更新当前分钟统计
            self.current_minute['requests'] += 1
            self.current_minute['bytes'] += response_size
            if error:
                self.current_minute['errors'] += 1
    
    def record_connection(self, tunnel_id, client_address, event_type):
        """记录连接事件"""
        with self.lock:
            current_time = time.time()
            
            if event_type == 'connect':
                self.active_connections += 1
                self.total_connections += 1
            elif event_type == 'disconnect':
                self.active_connections = max(0, self.active_connections - 1)
            
            # 记录连接历史
            self.connection_history.append({
                'timestamp': current_time,
                'tunnel_id': tunnel_id,
                'client_address': str(client_address),
                'event': event_type
            })
    
    def get_stats(self):
        """获取统计信息"""
        with self.lock:
            stats = {
                'uptime': int(time.time()),
                'total_requests': self.total_requests,
                'total_bytes_sent': self.total_bytes_sent,
                'total_bytes_received': self.total_bytes_received,
                'error_count': self.error_count,
                'timeout_count': self.timeout_count,
                'active_connections': self.active_connections,
                'total_connections': self.total_connections,
                'tunnel_count': len(self.tunnel_stats),
                'tunnels': dict(self.tunnel_stats),
                'recent_connections': list(self.connection_history)[-10:],  # 最近10次连接
                'minute_stats': list(self.minute_stats)[-30:]  # 最近30分钟
            }
            return stats
    
    def get_tunnel_stats(self, tunnel_id):
        """获取特定隧道的统计信息"""
        with self.lock:
            return self.tunnel_stats.get(tunnel_id, {})
    
    def start_stats_updater(self):
        """启动统计更新线程"""
        def update_stats():
            while True:
                try:
                    time.sleep(60)  # 每分钟更新一次
                    current_time = time.time()
                    current_minute_timestamp = int(current_time // 60) * 60
                    
                    with self.lock:
                        # 如果当前分钟已过，保存统计
                        if current_minute_timestamp != self.current_minute['timestamp']:
                            self.minute_stats.append(self.current_minute.copy())
                            self.current_minute = {
                                'timestamp': current_minute_timestamp,
                                'requests': 0,
                                'bytes': 0,
                                'errors': 0
                            }
                except Exception as e:
                    print(f"统计更新错误: {e}")
        
        updater_thread = threading.Thread(target=update_stats)
        updater_thread.daemon = True
        updater_thread.start()
    
    def save_stats(self, filename="tunnel_stats.json"):
        """保存统计信息到文件"""
        try:
            stats = self.get_stats()
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(stats, f, indent=2, ensure_ascii=False, default=str)
            return True
        except Exception as e:
            print(f"保存统计信息失败: {e}")
            return False

# 全局统计实例
tunnel_stats = TunnelStats()