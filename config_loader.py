import json
import os
import logging

class Config:
    def __init__(self, config_file="config.json"):
        self.config_file = config_file
        self.config = self.load_config()
    
    def load_config(self):
        """加载配置文件"""
        if not os.path.exists(self.config_file):
            logging.warning(f"配置文件 {self.config_file} 不存在，使用默认配置")
            return self.get_default_config()
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logging.info(f"成功加载配置文件: {self.config_file}")
            return config
        except Exception as e:
            logging.error(f"加载配置文件失败: {e}")
            return self.get_default_config()
    
    def get_default_config(self):
        """获取默认配置"""
        return {
            "server": {
                "host": "0.0.0.0",
                "control_port": 8000,
                "http_port": 80,
                "use_ssl": False,
                "cert_file": None,
                "key_file": None,
                "max_connections": 100,
                "heartbeat_timeout": 90,
                "request_timeout": 300
            },
            "client": {
                "server_host": "127.0.0.1",
                "server_port": 8000,
                "local_host": "127.0.0.1",
                "local_port": 8080,
                "subdomain": None,
                "use_ssl": False,
                "reconnect_delay": 5,
                "max_reconnect_delay": 300,
                "heartbeat_interval": 20
            },
            "logging": {
                "level": "INFO",
                "file": "tunnel.log",
                "max_size": "10MB",
                "backup_count": 5
            }
        }
    
    def get(self, key, default=None):
        """获取配置值，支持点分隔符"""
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def save_config(self):
        """保存配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logging.info(f"配置已保存到: {self.config_file}")
            return True
        except Exception as e:
            logging.error(f"保存配置文件失败: {e}")
            return False