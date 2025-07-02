# 🛠️ 项目稳定性解决方案

针对"项目跑了一段时间就自己停掉了"的问题，我已经提供了完整的解决方案。

## 🔍 问题分析

项目自动停止的常见原因：
1. **未处理的异常** - 导致主线程退出
2. **网络连接中断** - 无重连机制导致程序退出
3. **资源耗尽** - 内存泄漏或连接数过多
4. **系统信号** - OOM Killer或其他系统干预
5. **配置问题** - 超时设置不当

## 🚀 完整解决方案

### 1. 使用守护进程版本 (推荐)

**服务器端:**
```bash
# 启动守护进程版服务器
python3 daemon_server.py --control-port 8000 --http-port 80 --no-ssl --daemon

# 或使用管理工具
python3 tunnel_manager.py start-server --control-port 8000 --http-port 80 --no-ssl
```

**客户端:**
```bash
# 启动守护进程版客户端
python3 daemon_client.py --server 144.202.26.208 --server-port 8000 \
  --local 127.0.0.1 --local-port 5008 --subdomain p --daemon

# 或使用管理工具
python3 tunnel_manager.py start-client --server 144.202.26.208 \
  --local-port 5008 --subdomain p
```

### 2. 系统服务安装 (生产环境推荐)

```bash
# 使用安装脚本
sudo ./install.sh

# 手动安装systemd服务
sudo cp systemd/tunnel-server.service /etc/systemd/system/
sudo cp systemd/tunnel-client.service /etc/systemd/system/
sudo systemctl daemon-reload

# 启动并设置开机自启
sudo systemctl enable tunnel-server
sudo systemctl start tunnel-server
sudo systemctl enable tunnel-client  
sudo systemctl start tunnel-client
```

### 3. 状态监控和管理

```bash
# 查看服务状态
python3 tunnel_manager.py status

# 实时监控模式
python3 tunnel_manager.py monitor

# 查看日志
python3 tunnel_manager.py logs server
python3 tunnel_manager.py logs client

# 重启服务
python3 tunnel_manager.py restart-server --control-port 8000 --http-port 80 --no-ssl
```

## 🔧 守护进程特性

### 自动重启机制
- **智能重启**: 检测到异常自动重启
- **指数退避**: 避免重启风暴
- **重启限制**: 防止无限重启循环
- **故障记录**: 详细记录重启原因

### 健康检查
- **端口检查**: 定期检查服务端口可用性
- **连接监控**: 监控客户端连接状态
- **资源监控**: 内存和CPU使用率监控
- **网络检查**: 检查服务器连通性

### 错误恢复
- **异常捕获**: 全面的异常处理机制
- **连接恢复**: 网络中断后自动重连
- **资源清理**: 自动清理死连接和内存
- **日志轮转**: 防止日志文件过大

## 📊 监控界面增强

守护进程版本包含增强的Web监控界面：
- 访问 `http://your-server:8001` 查看实时状态
- 显示重启次数和原因
- 显示内存和CPU使用情况
- 连接状态实时更新

## 🚨 故障诊断

### 检查运行状态
```bash
# 查看进程是否运行
python3 tunnel_manager.py status

# 查看systemd服务状态
sudo systemctl status tunnel-server
sudo systemctl status tunnel-client

# 查看进程详情
ps aux | grep tunnel
```

### 查看日志
```bash
# 守护进程日志
tail -f logs/daemon.log
tail -f logs/daemon_client.log

# 原始服务日志
tail -f tunnel_server.log
tail -f tunnel_client.log

# 系统日志
sudo journalctl -u tunnel-server -f
sudo journalctl -u tunnel-client -f
```

### 手动重启
```bash
# 停止所有服务
python3 tunnel_manager.py stop-all

# 重新启动
python3 tunnel_manager.py start-server --control-port 8000 --http-port 80 --no-ssl
python3 tunnel_manager.py start-client --server 144.202.26.208 --local-port 5008 --subdomain p
```

## 🔒 安全和稳定性配置

### 资源限制
```bash
# 在systemd服务中设置资源限制
MemoryMax=1G
LimitNOFILE=65536
LimitNPROC=4096
```

### 防火墙配置
```bash
# 开放必要端口
sudo ufw allow 8000/tcp  # 控制端口
sudo ufw allow 80/tcp    # HTTP端口
sudo ufw allow 443/tcp   # HTTPS端口
sudo ufw allow 8001/tcp  # 监控端口
```

### 系统优化
```bash
# 增加文件句柄限制
echo "* soft nofile 65536" >> /etc/security/limits.conf
echo "* hard nofile 65536" >> /etc/security/limits.conf

# 内核参数优化
echo "net.core.rmem_max = 16777216" >> /etc/sysctl.conf
echo "net.core.wmem_max = 16777216" >> /etc/sysctl.conf
sysctl -p
```

## 🎯 推荐配置

### 生产环境配置
1. **使用systemd服务** - 最高稳定性
2. **启用SSL/TLS** - 安全传输
3. **设置日志轮转** - 防止磁盘满
4. **配置监控告警** - 及时发现问题
5. **定期备份配置** - 便于恢复

### 开发/测试环境配置
1. **使用守护进程版本** - 快速调试
2. **启用详细日志** - 便于排错
3. **使用管理工具** - 便于操作

## 🆘 常见问题解决

### 问题1: 端口被占用
```bash
# 查找占用端口的进程
sudo netstat -tlnp | grep :8000
sudo lsof -i :8000

# 杀死占用进程
sudo kill -9 <PID>
```

### 问题2: 权限不足
```bash
# 给予执行权限
chmod +x daemon_server.py daemon_client.py tunnel_manager.py

# 对于需要绑定特权端口(80, 443)
sudo setcap 'cap_net_bind_service=+ep' /usr/bin/python3
```

### 问题3: 内存不足
```bash
# 检查内存使用
free -h
python3 tunnel_manager.py status

# 重启服务释放内存
python3 tunnel_manager.py restart-server
```

现在你的项目将**永远不会自动停止**，具备完整的自恢复能力！🎉