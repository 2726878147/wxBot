import os
import random
import shutil
import threading
import time
from datetime import datetime
import pyautogui
from wxauto import WeChat


class User:
    def __init__(self, name, prompt_name, logger, config):
        self.config = config
        self.name = name
        self.prompt_name = prompt_name
        self.user_queues = {}
        self.user_timers = 0
        self.user_wait_time = 0
        self.make_user_auto_time()
        self.logger = logger
        self.root_dir = os.path.dirname(os.path.abspath(__file__))
        self.prompt = self.get_user_prompt()
        self.chat_contexts = []  # 存储用户的对话上下文
        self.is_sending_message = False  # 正在发送消息不向DeepSeek发送
        self.can_send_messages = True  # 是否可以发送消息（处理图片数据时等待）
        self.queue_lock = threading.Lock()  # 用户级别的队列锁

    def get_user_prompt(self):
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prompt_path = os.path.join(root_dir, 'prompts', f'{self.prompt_name}.md')

        if not os.path.exists(prompt_path):
            self.logger.error(f"Prompt文件不存在: {prompt_path}")
            raise FileNotFoundError(f"Prompt文件 {self.prompt_name}.md 未找到于 prompts 目录")

        with open(prompt_path, 'r', encoding='utf-8') as file:
            return file.read()

    def make_user_auto_time(self):
        self.user_timers = time.time()
        self.user_wait_time = random.uniform(self.config["MIN_WAIT_TIME"], self.config["MAX_WAIT_TIME"]) * 3600

    def make_log_user(self, content):
        log_file = os.path.join(self.root_dir, self.config["MEMORY_TEMP_DIR"], f'{self.name}_{self.prompt_name}_User_log.txt')
        log_entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | [User] {content}\n"

        if os.path.exists(log_file) and os.path.getsize(log_file) > 1 * 1024 * 1024:
            archive_file = os.path.join(self.root_dir, self.config["MEMORY_TEMP_DIR"],
                                        f'{self.name}_log_archive_{int(time.time())}.txt')
            shutil.move(log_file, archive_file)

        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)

    def make_log_reply(self, content):

        log_file = os.path.join(self.root_dir, self.config['MEMORY_TEMP_DIR'], f'{self.name}_{self.prompt_name}_AI_log.txt')
        log_entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | [AI] {content}\n"

        if os.path.exists(log_file) and os.path.getsize(log_file) > 1 * 1024 * 1024:  # 1MB
            archive_file = os.path.join(self.root_dir, self.config['MEMORY_TEMP_DIR'],
                                        f'{self.name}_log_archive_{int(time.time())}.txt')
            shutil.move(log_file, archive_file)

        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
