# 内网穿透隧道系统

一个基于Python的内网穿透解决方案，支持通过公网VPS访问NAT后面的家用电脑服务。

## 功能特性

- ✅ **SSL/TLS加密通信** - 保证数据传输安全
- ✅ **子域名映射** - 支持 `p.windy.run` 格式访问
- ✅ **心跳检测** - 自动检测和重连断开的连接
- ✅ **HTTP请求转发** - 完整的HTTP协议支持
- ✅ **自动重连机制** - 客户端断线自动重连
- ✅ **连接监控** - 实时监控连接状态和统计
- ✅ **Web管理界面** - 友好的Web控制台
- ✅ **配置文件支持** - 灵活的配置管理
- ✅ **访问日志统计** - 详细的访问记录和统计
- ✅ **系统服务支持** - systemd服务管理

## 系统架构

```
外网用户 → VPS服务器(server.py) → NAT内网(client.py) → 本地服务
         p.windy.run                 家用电脑           localhost:5008
```

## 快速开始

### 1. 安装依赖

```bash
# 使用自动安装脚本
sudo ./install.sh

# 或手动安装
pip install -r requirements.txt
```

### 2. 服务器端部署 (VPS)

```bash
# SSL模式 (推荐)
sudo python3 server.py --control-port 8000 --http-port 443 \
  --cert /etc/letsencrypt/live/windy.run/fullchain.pem \
  --key /etc/letsencrypt/live/windy.run/privkey.pem

# 非SSL模式 (测试用)
python3 server.py --control-port 8000 --http-port 80 --no-ssl
```

### 3. 客户端部署 (内网电脑)

```bash
python3 client.py --server 144.202.26.208 --server-port 8000 \
  --local 127.0.0.1 --local-port 5008 --subdomain p
```

### 4. 访问服务

访问 `https://p.windy.run` 即可访问内网服务

## 配置文件

编辑 `config.json` 进行详细配置：

```json
{
  "server": {
    "host": "0.0.0.0",
    "control_port": 8000,
    "http_port": 443,
    "use_ssl": true,
    "cert_file": "/etc/letsencrypt/live/windy.run/fullchain.pem",
    "key_file": "/etc/letsencrypt/live/windy.run/privkey.pem"
  },
  "client": {
    "server_host": "144.202.26.208",
    "server_port": 8000,
    "local_host": "127.0.0.1",
    "local_port": 5008,
    "subdomain": "p"
  }
}
```

## 系统服务

### 服务器端

```bash
# 安装服务
sudo cp systemd/tunnel-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tunnel-server

# 启动/停止
sudo systemctl start tunnel-server
sudo systemctl stop tunnel-server
sudo systemctl status tunnel-server
```

### 客户端

```bash
# 安装服务
sudo cp systemd/tunnel-client.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tunnel-client

# 启动/停止
sudo systemctl start tunnel-client
sudo systemctl stop tunnel-client
sudo systemctl status tunnel-client
```

## Web管理界面

启动Web管理界面：

```bash
python3 web_admin.py
```

访问 `http://localhost:8001` 查看：
- 实时连接统计
- 隧道状态监控
- 访问日志分析
- 性能指标

## 日志管理

### 查看日志

```bash
# 服务器日志
tail -f tunnel_server.log
journalctl -u tunnel-server -f

# 客户端日志
tail -f tunnel_client.log
journalctl -u tunnel-client -f

# 访问日志
tail -f logs/access.log
```

### 日志轮转

日志文件自动轮转，默认：
- 单文件最大 10MB
- 保留 5 个备份文件
- 自动压缩旧日志

## 故障排除

### 常见问题

1. **连接被拒绝**
   - 检查防火墙设置
   - 确认端口开放状态
   - 验证SSL证书路径

2. **SSL握手失败**
   - 检查证书文件权限
   - 确认证书有效期
   - 验证域名配置

3. **频繁重连**
   - 检查网络稳定性
   - 调整心跳间隔
   - 查看错误日志

### 调试模式

```bash
# 启用详细日志
python3 server.py --debug
python3 client.py --debug
```

## 性能优化

### 服务器端

- 调整 `max_connections` 限制并发连接数
- 设置 `request_timeout` 控制请求超时
- 使用 `worker_processes` 提高并发处理能力

### 客户端

- 调整 `heartbeat_interval` 优化心跳频率
- 设置 `reconnect_delay` 控制重连间隔
- 使用连接池减少建连开销

## API接口

### 统计API

```bash
# 获取服务器统计
curl http://localhost:8001/api/stats

# 获取隧道列表
curl http://localhost:8001/api/tunnels
```

## 安全建议

1. **启用SSL/TLS** - 生产环境必须使用加密传输
2. **防火墙配置** - 只开放必要端口
3. **访问控制** - 限制客户端IP范围
4. **定期更新** - 保持系统和依赖库最新
5. **监控日志** - 及时发现异常访问

## 许可证

MIT License

## 贡献

欢迎提交Issues和Pull Requests！

## 联系方式

如有问题请创建Issue或联系维护者。