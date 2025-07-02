#!/usr/bin/env python3
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import logging
from urllib.parse import urlparse, parse_qs
from stats import tunnel_stats

class AdminHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path == '/':
            self.serve_dashboard()
        elif path == '/api/stats':
            self.serve_stats()
        elif path == '/api/tunnels':
            self.serve_tunnels()
        elif path.startswith('/static/'):
            self.serve_static(path)
        else:
            self.send_error(404)
    
    def serve_dashboard(self):
        """提供管理界面首页"""
        html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>隧道管理控制台</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { background: #2c3e50; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 20px; }
        .stat-card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .stat-value { font-size: 2em; font-weight: bold; color: #3498db; }
        .stat-label { color: #7f8c8d; font-size: 0.9em; }
        .tunnel-list { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .tunnel-item { padding: 15px; border-bottom: 1px solid #ecf0f1; display: flex; justify-content: space-between; align-items: center; }
        .tunnel-id { font-weight: bold; color: #2c3e50; }
        .tunnel-stats { color: #7f8c8d; font-size: 0.9em; }
        .status-online { color: #27ae60; }
        .status-offline { color: #e74c3c; }
        .refresh-btn { background: #3498db; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; }
        .refresh-btn:hover { background: #2980b9; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚇 隧道管理控制台</h1>
            <p>实时监控您的内网穿透服务状态</p>
        </div>
        
        <div class="stats-grid" id="stats-grid">
            <!-- 统计数据将在这里动态加载 -->
        </div>
        
        <div class="tunnel-list">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <h3>活跃隧道</h3>
                <button class="refresh-btn" onclick="refreshData()">刷新</button>
            </div>
            <div id="tunnel-list">
                <!-- 隧道列表将在这里动态加载 -->
            </div>
        </div>
    </div>

    <script>
        let refreshInterval;
        
        function formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
        
        function formatDuration(seconds) {
            if (seconds < 60) return Math.floor(seconds) + '秒';
            if (seconds < 3600) return Math.floor(seconds / 60) + '分钟';
            if (seconds < 86400) return Math.floor(seconds / 3600) + '小时';
            return Math.floor(seconds / 86400) + '天';
        }
        
        async function fetchStats() {
            try {
                const response = await fetch('/api/stats');
                return await response.json();
            } catch (error) {
                console.error('获取统计数据失败:', error);
                return null;
            }
        }
        
        function renderStats(stats) {
            if (!stats) return;
            
            const statsGrid = document.getElementById('stats-grid');
            statsGrid.innerHTML = `
                <div class="stat-card">
                    <div class="stat-value">${stats.active_connections}</div>
                    <div class="stat-label">活跃连接</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${stats.total_requests}</div>
                    <div class="stat-label">总请求数</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${formatBytes(stats.total_bytes_sent)}</div>
                    <div class="stat-label">总传输量</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${stats.tunnel_count}</div>
                    <div class="stat-label">隧道数量</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${stats.error_count}</div>
                    <div class="stat-label">错误次数</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${formatDuration(Date.now()/1000 - stats.uptime)}</div>
                    <div class="stat-label">运行时间</div>
                </div>
            `;
        }
        
        function renderTunnels(stats) {
            if (!stats || !stats.tunnels) return;
            
            const tunnelList = document.getElementById('tunnel-list');
            const tunnels = Object.entries(stats.tunnels);
            
            if (tunnels.length === 0) {
                tunnelList.innerHTML = '<p style="text-align: center; color: #7f8c8d;">暂无活跃隧道</p>';
                return;
            }
            
            tunnelList.innerHTML = tunnels.map(([tunnelId, tunnelStats]) => {
                const lastSeen = tunnelStats.last_seen ? 
                    formatDuration(Date.now()/1000 - tunnelStats.last_seen) + '前' : '未知';
                    
                return `
                    <div class="tunnel-item">
                        <div>
                            <div class="tunnel-id">${tunnelId}</div>
                            <div class="tunnel-stats">
                                请求: ${tunnelStats.requests} | 
                                传输: ${formatBytes(tunnelStats.bytes_sent)} | 
                                错误: ${tunnelStats.errors} | 
                                最后活跃: ${lastSeen}
                            </div>
                        </div>
                        <div class="status-online">● 在线</div>
                    </div>
                `;
            }).join('');
        }
        
        async function refreshData() {
            const stats = await fetchStats();
            if (stats) {
                renderStats(stats);
                renderTunnels(stats);
            }
        }
        
        // 初始加载和定时刷新
        refreshData();
        refreshInterval = setInterval(refreshData, 5000); // 每5秒刷新一次
        
        // 页面隐藏时停止刷新，显示时恢复
        document.addEventListener('visibilitychange', function() {
            if (document.hidden) {
                clearInterval(refreshInterval);
            } else {
                refreshData();
                refreshInterval = setInterval(refreshData, 5000);
            }
        });
    </script>
</body>
</html>
        """
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def serve_stats(self):
        """提供统计数据API"""
        try:
            stats = tunnel_stats.get_stats()
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            json_data = json.dumps(stats, ensure_ascii=False, default=str)
            self.wfile.write(json_data.encode('utf-8'))
            
        except Exception as e:
            logging.error(f"获取统计数据失败: {e}")
            self.send_error(500, f"Internal Server Error: {str(e)}")
    
    def serve_tunnels(self):
        """提供隧道列表API"""
        try:
            # 这里需要从主服务器获取隧道信息
            # 暂时返回空数据
            tunnels = {}
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            json_data = json.dumps(tunnels, ensure_ascii=False)
            self.wfile.write(json_data.encode('utf-8'))
            
        except Exception as e:
            logging.error(f"获取隧道列表失败: {e}")
            self.send_error(500, f"Internal Server Error: {str(e)}")
    
    def log_message(self, format, *args):
        """覆盖日志方法，避免控制台输出"""
        logging.debug(f"Admin请求: {args[0]} {args[1]}")

class WebAdmin:
    def __init__(self, host='127.0.0.1', port=8001):
        self.host = host
        self.port = port
        self.server = None
        self.running = False
    
    def start(self):
        """启动Web管理界面"""
        if self.running:
            return
        
        self.running = True
        
        def run_server():
            try:
                self.server = HTTPServer((self.host, self.port), AdminHandler)
                logging.info(f"Web管理界面启动: http://{self.host}:{self.port}")
                self.server.serve_forever()
            except Exception as e:
                logging.error(f"Web管理界面启动失败: {e}")
        
        server_thread = threading.Thread(target=run_server)
        server_thread.daemon = True
        server_thread.start()
    
    def stop(self):
        """停止Web管理界面"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        self.running = False
        logging.info("Web管理界面已停止")

if __name__ == "__main__":
    # 测试Web管理界面
    admin = WebAdmin()
    admin.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        admin.stop()