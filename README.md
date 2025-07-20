# 内网穿透隧道服务

简单的内网穿透工具，支持HTTP流量转发。

## 核心文件

- `server.py` - 服务器端程序
- `client.py` - 客户端程序  

## 快速开始

### 1. 服务器端部署（VPS）

```bash
# 无SSL模式启动
python3 server.py --control-port 8000 --http-port 80 --no-ssl

# SSL模式启动
sudo python3 server.py --control-port 8000 --http-port 443 --cert /path/to/cert.pem --key /path/to/key.pem
```

### 2. 客户端部署

```bash
# 基本启动命令
python client.py --server YOUR_SERVER_IP --server-port 8000 --local 127.0.0.1 --local-port LOCAL_PORT --subdomain SUBDOMAIN

# 示例：连接到服务器并暴露本地5008端口
python client.py --server 144.202.26.208 --server-port 8000 --local 127.0.0.1 --local-port 5008 --subdomain p
```

## 使用说明

### 服务器参数
- `--control-port` - 控制端口（默认8000）
- `--http-port` - HTTP端口（默认8080，避免权限问题）
- `--no-ssl` - 禁用SSL模式

### 客户端参数
- `--server` - 服务器地址
- `--server-port` - 服务器端口（默认8000）
- `--local` - 本地服务地址
- `--local-port` - 本地服务端口
- `--subdomain` - 子域名
- `--no-ssl` - 禁用SSL模式

## 访问方式

- `http://服务器IP:8080/` - 查看服务器状态
- `http://子域名.域名:8080/` - 通过子域名访问

## 故障排除

常见问题：
1. **连接失败** - 检查服务器地址、端口和网络连接
2. **服务停止** - 查看日志文件中的错误信息
3. **端口占用** - 确保指定端口未被其他程序占用
4. **服务自动停止** - 已优化重连机制，会自动重新连接
5. **频繁重连** - 优化了重连间隔，前3次失败快速重连（5/10/15秒）

## 停止服务

**Linux/VPS：**
```bash
# 查找进程
ps aux | grep python

# 终止进程
kill 进程ID
```

**Windows：**
```cmd
# 查找进程
tasklist | findstr python

# 终止进程
taskkill /f /pid 进程ID
```

## 功能特性

### 🔄 智能重连策略
- **快速恢复**: 前3次失败快速重连（5/10/15秒）
- **梯度延迟**: 4-10次失败30秒，11-30次失败1分钟，30次后2分钟
- **自适应延迟**: 根据连接成功历史动态调整重连时间
- **连接成功率监控**: 失败率过高时自动增加重连延迟
- **心跳监控**: 20秒心跳间隔，60秒超时检测

### 📊 日志轮转机制
- **客户端日志**: 自动轮转，最大5MB，保留3个备份文件
- **服务器日志**: 自动轮转，最大10MB，保留5个备份文件
- **防止日志文件过大**: 避免磁盘空间不足

### 💾 内存优化
- **定期清理**: 每10次心跳自动执行垃圾回收
- **内存监控**: 实时监控内存使用情况
- **高内存告警**: 使用量过高时自动告警

## 日志分析

### 查看日志
```bash
# 查看服务器日志
tail -f tunnel_server.log

# 查看客户端日志
tail -f tunnel_client.log

# 检查重连情况
grep "重连" tunnel_client.log | tail -10

# 检查连接状态
grep "客户端.*注册" tunnel_server.log | tail -5
```

## 注意事项

- 服务器需要公网IP
- 建议在防火墙中开放相应端口
- 智能重连会根据网络状况自动调整策略
- 日志文件会自动轮转，无需手动清理