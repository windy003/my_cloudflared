#!/bin/bash

# 内网穿透隧道安装脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查权限
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此脚本需要以root权限运行"
        exit 1
    fi
}

# 安装依赖
install_dependencies() {
    log_info "安装系统依赖..."
    
    if command -v apt-get &> /dev/null; then
        apt-get update
        apt-get install -y python3 python3-pip python3-venv
    elif command -v yum &> /dev/null; then
        yum install -y python3 python3-pip
    elif command -v dnf &> /dev/null; then
        dnf install -y python3 python3-pip
    else
        log_error "不支持的包管理器"
        exit 1
    fi
}

# 创建用户
create_user() {
    if ! id "tunnel" &>/dev/null; then
        log_info "创建tunnel用户..."
        useradd -r -m -s /bin/bash tunnel
    else
        log_info "tunnel用户已存在"
    fi
}

# 安装服务器
install_server() {
    log_info "安装隧道服务器..."
    
    # 创建目录
    mkdir -p /opt/my_cloudflared
    mkdir -p /var/log/tunnel-server
    
    # 复制文件
    cp *.py /opt/my_cloudflared/
    cp config.json /opt/my_cloudflared/
    cp requirements.txt /opt/my_cloudflared/
    
    # 安装Python依赖
    cd /opt/my_cloudflared
    python3 -m pip install -r requirements.txt
    
    # 设置权限
    chown -R root:root /opt/my_cloudflared
    chmod +x /opt/my_cloudflared/server.py
    
    # 安装systemd服务
    cp systemd/tunnel-server.service /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable tunnel-server
    
    log_info "服务器安装完成"
}

# 安装客户端
install_client() {
    log_info "安装隧道客户端..."
    
    # 创建目录
    mkdir -p /home/tunnel/my_cloudflared
    
    # 复制文件
    cp *.py /home/tunnel/my_cloudflared/
    cp config.json /home/tunnel/my_cloudflared/
    cp requirements.txt /home/tunnel/my_cloudflared/
    
    # 安装Python依赖
    cd /home/tunnel/my_cloudflared
    python3 -m pip install -r requirements.txt
    
    # 设置权限
    chown -R tunnel:tunnel /home/tunnel/my_cloudflared
    chmod +x /home/tunnel/my_cloudflared/client.py
    
    # 安装systemd服务
    cp systemd/tunnel-client.service /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable tunnel-client
    
    log_info "客户端安装完成"
}

# 配置防火墙
configure_firewall() {
    log_info "配置防火墙..."
    
    if command -v ufw &> /dev/null; then
        ufw allow 8000/tcp
        ufw allow 80/tcp
        ufw allow 443/tcp
    elif command -v firewall-cmd &> /dev/null; then
        firewall-cmd --permanent --add-port=8000/tcp
        firewall-cmd --permanent --add-port=80/tcp
        firewall-cmd --permanent --add-port=443/tcp
        firewall-cmd --reload
    else
        log_warn "未检测到防火墙管理工具，请手动开放端口 8000, 80, 443"
    fi
}

# 主菜单
show_menu() {
    echo ""
    echo "======================================"
    echo "   内网穿透隧道安装脚本"
    echo "======================================"
    echo "1. 安装服务器端"
    echo "2. 安装客户端"
    echo "3. 安装完整套件"
    echo "4. 仅安装依赖"
    echo "5. 退出"
    echo "======================================"
    read -p "请选择安装选项 [1-5]: " choice
}

# 主函数
main() {
    check_root
    
    show_menu
    
    case $choice in
        1)
            install_dependencies
            install_server
            configure_firewall
            log_info "服务器端安装完成！使用 'systemctl start tunnel-server' 启动服务"
            ;;
        2)
            install_dependencies
            create_user
            install_client
            log_info "客户端安装完成！使用 'systemctl start tunnel-client' 启动服务"
            ;;
        3)
            install_dependencies
            create_user
            install_server
            install_client
            configure_firewall
            log_info "完整套件安装完成！"
            ;;
        4)
            install_dependencies
            log_info "依赖安装完成！"
            ;;
        5)
            log_info "退出安装"
            exit 0
            ;;
        *)
            log_error "无效选项"
            exit 1
            ;;
    esac
}

# 运行主函数
main