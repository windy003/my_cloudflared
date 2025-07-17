# 内网穿透隧道服务

简单的内网穿透工具，支持HTTP流量转发。

## 文件说明

- `server.py` - 服务器端程序
- `client.py` - 客户端程序
- `start_server.bat` / `start_server.sh` - 服务器后台启动脚本
- `start_client.bat` / `start_client.sh` - 客户端后台启动脚本

## 快速开始

### 1. 服务器端部署（Linux）

```bash
# 前台运行
python3 server.py --control-port 8000 --http-port 80 --no-ssl

# 后台运行
./start_server.sh
```

### 2. 客户端部署（Windows）

```bat
# 前台运行
python client.py --server 144.202.26.208 --server-port 8000 --local 127.0.0.1 --local-port 5008 --subdomain p --no-ssl

# 后台运行
start_client.bat
```

### 3. 客户端部署（Linux）

```bash
# 前台运行
python3 client.py --server 144.202.26.208 --server-port 8000 --local 127.0.0.1 --local-port 5008 --subdomain p --no-ssl

# 后台运行
./start_client.sh
```

## 参数说明

### 服务器参数
- `--host` - 绑定地址，默认 0.0.0.0
- `--control-port` - 控制端口，默认 8000
- `--http-port` - HTTP端口，默认 80
- `--no-ssl` - 禁用SSL
- `--cert` - SSL证书文件路径
- `--key` - SSL密钥文件路径

### 客户端参数
- `--server` - 服务器地址
- `--server-port` - 服务器端口，默认 8000
- `--local` - 本地服务地址，默认 127.0.0.1
- `--local-port` - 本地服务端口
- `--subdomain` - 子域名
- `--no-ssl` - 禁用SSL

## 使用示例

### 无SSL模式（推荐）

**服务器：**
```bash
python3 server.py --control-port 8000 --http-port 80 --no-ssl
```

**客户端：**
```bash
python3 client.py --server 144.202.26.208 --server-port 8000 --local 127.0.0.1 --local-port 5008 --subdomain p --no-ssl
```

**访问：**
- `http://服务器IP/` - 查看服务器状态
- `http://p.域名/` - 通过子域名访问

### SSL模式

**服务器：**
```bash
sudo python3 server.py --control-port 8000 --http-port 443 --cert /path/to/cert.pem --key /path/to/key.pem
```

**客户端：**
```bash
python3 client.py --server 域名 --server-port 8000 --local 127.0.0.1 --local-port 5008 --subdomain p
```

## 后台运行

### Windows后台运行
使用 `pythonw` 和 `start /b` 命令：

```bat
# 服务器后台运行
start /b pythonw server.py --control-port 8000 --http-port 80 --no-ssl

# 客户端后台运行
start /b pythonw client.py --server 144.202.26.208 --server-port 8000 --local 127.0.0.1 --local-port 5008 --subdomain p --no-ssl
```

或直接运行：
- `start_server.bat` - 服务器后台启动
- `start_client.bat` - 客户端后台启动

### Linux后台运行
使用 `nohup` 命令：

```bash
# 服务器后台运行
nohup python3 server.py --control-port 8000 --http-port 80 --no-ssl > tunnel_server.log 2>&1 &

# 客户端后台运行
nohup python3 client.py --server 144.202.26.208 --server-port 8000 --local 127.0.0.1 --local-port 5008 --subdomain p --no-ssl > tunnel_client.log 2>&1 &
```

或直接运行：
- `./start_server.sh` - 服务器后台启动
- `./start_client.sh` - 客户端后台启动

## 日志文件

- `tunnel_server.log` - 服务器日志
- `tunnel_client.log` - 客户端日志

## 停止服务

### Windows
```bat
# 查找进程
tasklist | findstr python

# 终止进程
taskkill /f /pid 进程ID
```

### Linux
```bash
# 查找进程
ps aux | grep python

# 终止进程
kill 进程ID

# 或者终止所有相关进程
pkill -f server.py
pkill -f client.py
```

## 功能特性

- **自动重连** - 客户端支持无限重连
- **心跳检测** - 自动检测连接状态
- **多客户端** - 支持多个客户端同时连接
- **子域名支持** - 通过子域名访问不同的隧道
- **日志记录** - 详细的运行日志
- **SSL支持** - 可选的SSL加密传输

## 故障排除

1. **连接失败**
   - 检查服务器地址和端口
   - 确认防火墙设置
   - 检查网络连接

2. **无法访问**
   - 确认本地服务运行正常
   - 检查端口是否被占用
   - 查看日志文件

3. **服务停止**
   - 查看日志文件中的错误信息
   - 检查系统资源
   - 重启服务

## 注意事项

- 服务器需要公网IP
- 客户端需要能访问服务器
- 建议在防火墙中开放相应端口
- 定期检查日志文件大小
- 生产环境建议使用SSL