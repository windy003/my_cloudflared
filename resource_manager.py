#!/usr/bin/env python3
"""
资源管理和内存优化模块
"""

import gc
import time
import threading
import logging
import weakref
from collections import defaultdict

class ResourceManager:
    """资源管理器，用于监控和清理资源"""
    
    def __init__(self):
        self.logger = logging.getLogger('resource_manager')
        self.connections = weakref.WeakSet()
        self.cleanup_interval = 300  # 5分钟清理一次
        self.memory_check_interval = 60  # 1分钟检查一次内存
        self.running = True
        
        # 资源统计
        self.resource_stats = defaultdict(int)
        
        # 启动清理线程
        self.start_cleanup_threads()
    
    def start_cleanup_threads(self):
        """启动资源清理线程"""
        # 内存清理线程
        memory_thread = threading.Thread(target=self.memory_cleanup_loop)
        memory_thread.daemon = True
        memory_thread.start()
        
        # 连接清理线程
        connection_thread = threading.Thread(target=self.connection_cleanup_loop)
        connection_thread.daemon = True
        connection_thread.start()
    
    def register_connection(self, connection):
        """注册连接对象"""
        self.connections.add(connection)
        self.resource_stats['total_connections'] += 1
    
    def memory_cleanup_loop(self):
        """内存清理循环"""
        while self.running:
            try:
                # 强制垃圾回收
                collected = gc.collect()
                if collected > 0:
                    self.logger.debug(f"垃圾回收释放了 {collected} 个对象")
                
                # 检查内存使用
                try:
                    import psutil
                    process = psutil.Process()
                    memory_info = process.memory_info()
                    memory_mb = memory_info.rss / 1024 / 1024
                    
                    self.resource_stats['memory_usage_mb'] = memory_mb
                    
                    # 如果内存使用过高，执行更激进的清理
                    if memory_mb > 500:  # 500MB
                        self.logger.warning(f"内存使用较高: {memory_mb:.1f}MB，执行清理")
                        self.aggressive_cleanup()
                        
                except ImportError:
                    pass  # psutil未安装
                
                time.sleep(self.memory_check_interval)
                
            except Exception as e:
                self.logger.error(f"内存清理错误: {e}")
                time.sleep(self.memory_check_interval)
    
    def connection_cleanup_loop(self):
        """连接清理循环"""
        while self.running:
            try:
                # 清理死连接
                dead_connections = []
                for conn in list(self.connections):
                    if hasattr(conn, '_closed') and conn._closed:
                        dead_connections.append(conn)
                
                for conn in dead_connections:
                    try:
                        self.connections.discard(conn)
                    except:
                        pass
                
                if dead_connections:
                    self.logger.debug(f"清理了 {len(dead_connections)} 个死连接")
                
                self.resource_stats['active_connections'] = len(self.connections)
                
                time.sleep(self.cleanup_interval)
                
            except Exception as e:
                self.logger.error(f"连接清理错误: {e}")
                time.sleep(self.cleanup_interval)
    
    def aggressive_cleanup(self):
        """激进的内存清理"""
        try:
            # 清理所有缓存
            import sys
            
            # 清理模块缓存
            modules_to_clean = []
            for module_name, module in sys.modules.items():
                if hasattr(module, '__dict__'):
                    # 清理一些可能的缓存
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name, None)
                        if isinstance(attr, (list, dict, set)) and attr_name.startswith('_'):
                            try:
                                if hasattr(attr, 'clear'):
                                    attr.clear()
                            except:
                                pass
            
            # 强制垃圾回收
            for _ in range(3):
                gc.collect()
            
            self.logger.info("执行了激进的内存清理")
            
        except Exception as e:
            self.logger.error(f"激进内存清理失败: {e}")
    
    def get_stats(self):
        """获取资源统计"""
        return dict(self.resource_stats)
    
    def stop(self):
        """停止资源管理器"""
        self.running = False

# 全局资源管理器实例
resource_manager = ResourceManager()

class ConnectionPool:
    """连接池管理"""
    
    def __init__(self, max_size=50):
        self.max_size = max_size
        self.pools = defaultdict(list)
        self.lock = threading.Lock()
        self.logger = logging.getLogger('connection_pool')
    
    def get_connection(self, key, factory_func):
        """获取连接"""
        with self.lock:
            pool = self.pools[key]
            
            # 清理无效连接
            valid_connections = []
            for conn in pool:
                if self.is_connection_valid(conn):
                    valid_connections.append(conn)
                else:
                    self.close_connection(conn)
            
            self.pools[key] = valid_connections
            pool = valid_connections
            
            # 如果有可用连接，返回
            if pool:
                conn = pool.pop()
                self.logger.debug(f"从连接池获取连接: {key}")
                return conn
            
            # 创建新连接
            try:
                conn = factory_func()
                self.logger.debug(f"创建新连接: {key}")
                resource_manager.register_connection(conn)
                return conn
            except Exception as e:
                self.logger.error(f"创建连接失败 {key}: {e}")
                return None
    
    def return_connection(self, key, connection):
        """归还连接"""
        if not self.is_connection_valid(connection):
            self.close_connection(connection)
            return
        
        with self.lock:
            pool = self.pools[key]
            if len(pool) < self.max_size:
                pool.append(connection)
                self.logger.debug(f"连接已归还到连接池: {key}")
            else:
                self.close_connection(connection)
                self.logger.debug(f"连接池已满，关闭连接: {key}")
    
    def is_connection_valid(self, connection):
        """检查连接是否有效"""
        try:
            if hasattr(connection, '_closed'):
                return not connection._closed
            if hasattr(connection, 'closed'):
                return not connection.closed
            return True
        except:
            return False
    
    def close_connection(self, connection):
        """关闭连接"""
        try:
            if hasattr(connection, 'close'):
                connection.close()
        except:
            pass
    
    def cleanup(self):
        """清理连接池"""
        with self.lock:
            for key, pool in self.pools.items():
                for conn in pool:
                    self.close_connection(conn)
                pool.clear()
            self.pools.clear()
            self.logger.info("连接池已清理")

# 全局连接池实例
connection_pool = ConnectionPool()

class MemoryMonitor:
    """内存监控器"""
    
    def __init__(self):
        self.logger = logging.getLogger('memory_monitor')
        self.snapshots = []
        self.max_snapshots = 10
    
    def take_snapshot(self, label=""):
        """拍摄内存快照"""
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()
            
            snapshot = {
                'timestamp': time.time(),
                'label': label,
                'rss': memory_info.rss,
                'vms': memory_info.vms,
                'rss_mb': memory_info.rss / 1024 / 1024,
                'vms_mb': memory_info.vms / 1024 / 1024
            }
            
            self.snapshots.append(snapshot)
            
            # 保持快照数量
            if len(self.snapshots) > self.max_snapshots:
                self.snapshots.pop(0)
            
            self.logger.debug(f"内存快照 [{label}]: RSS={snapshot['rss_mb']:.1f}MB, VMS={snapshot['vms_mb']:.1f}MB")
            
            return snapshot
            
        except ImportError:
            self.logger.warning("psutil未安装，无法监控内存")
            return None
        except Exception as e:
            self.logger.error(f"内存快照失败: {e}")
            return None
    
    def get_memory_trend(self):
        """获取内存使用趋势"""
        if len(self.snapshots) < 2:
            return None
        
        first = self.snapshots[0]
        last = self.snapshots[-1]
        
        time_diff = last['timestamp'] - first['timestamp']
        memory_diff = last['rss'] - first['rss']
        
        if time_diff > 0:
            memory_rate = memory_diff / time_diff  # bytes per second
            return {
                'time_span': time_diff,
                'memory_change': memory_diff,
                'memory_rate': memory_rate,
                'memory_rate_mb_per_hour': memory_rate * 3600 / 1024 / 1024
            }
        
        return None
    
    def check_memory_leak(self):
        """检查是否有内存泄漏"""
        trend = self.get_memory_trend()
        if trend and trend['memory_rate_mb_per_hour'] > 50:  # 每小时增长超过50MB
            self.logger.warning(f"检测到可能的内存泄漏: {trend['memory_rate_mb_per_hour']:.1f}MB/小时")
            return True
        return False

# 全局内存监控器实例
memory_monitor = MemoryMonitor()