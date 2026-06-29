# utils/logger.py
import time

class Logger:
    def __init__(self, module_name: str):
        self.module_name = module_name

    def info(self, msg: str):
        print(f"[{time.ticks_ms()}] [INFO] [{self.module_name}] {msg}")

    def error(self, msg: str):
        print(f"[{time.ticks_ms()}] [ERROR] [{self.module_name}] {msg}")

    def debug(self, msg: str):
        print(f"[{time.ticks_ms()}] [DEBUG] [{self.module_name}] {msg}")