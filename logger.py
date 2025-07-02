import logging
import logging.handlers
import os
from datetime import datetime

def setup_logger(name, log_file, level=logging.INFO, max_bytes=10*1024*1024, backup_count=5):
    """设置日志记录器with rotation"""
    
    # 创建日志目录
    log_dir = os.path.dirname(log_file) if os.path.dirname(log_file) else 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 创建logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 清除现有的处理器
    logger.handlers.clear()
    
    # 创建格式化器
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 文件处理器 (支持日志轮转)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger

def setup_access_logger(log_file='logs/access.log'):
    """设置访问日志记录器"""
    access_logger = logging.getLogger('access')
    access_logger.setLevel(logging.INFO)
    access_logger.handlers.clear()
    
    # 访问日志格式
    access_formatter = logging.Formatter(
        '%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 访问日志文件处理器
    access_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=10, encoding='utf-8'
    )
    access_handler.setLevel(logging.INFO)
    access_handler.setFormatter(access_formatter)
    access_logger.addHandler(access_handler)
    
    return access_logger

class ErrorHandler:
    """统一的错误处理类"""
    
    def __init__(self, logger):
        self.logger = logger
        self.error_count = 0
        self.last_errors = []
        self.max_last_errors = 100
    
    def handle_exception(self, exc, context="", reraise=False):
        """处理异常"""
        self.error_count += 1
        error_msg = f"{context}: {type(exc).__name__}: {str(exc)}"
        
        # 记录错误
        self.logger.error(error_msg, exc_info=True)
        
        # 保存最近的错误
        self.last_errors.append({
            'timestamp': datetime.now(),
            'context': context,
            'error': str(exc),
            'type': type(exc).__name__
        })
        
        # 保持列表大小
        if len(self.last_errors) > self.max_last_errors:
            self.last_errors.pop(0)
        
        if reraise:
            raise exc
    
    def get_error_stats(self):
        """获取错误统计"""
        return {
            'total_errors': self.error_count,
            'recent_errors': self.last_errors[-10:],  # 最近10个错误
            'error_types': {}
        }