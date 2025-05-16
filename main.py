import logging
import os
import re
import shutil
import threading
import time
import random
from datetime import datetime
import asyncio

import pyautogui
import yaml
from wxauto import WeChat
from model.User import User
from model.Ai import Ai

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

root_dir = os.path.dirname(os.path.abspath(__file__))

queue_lock = threading.Lock()

memory_dir = os.path.join(root_dir, "temp", "memory")
if not os.path.exists(memory_dir):
    os.makedirs(memory_dir)
    logger.info(f"创建内存目录: {memory_dir}")

# 修改配置文件中的内存目录路径
config["MEMORY_TEMP_DIR"] = memory_dir

wx = WeChat()

emoji_timer = None
emoji_timer_lock = threading.Lock()

user_list = [User(name=config["LISTEN_LIST"][0], prompt_name=config["LISTEN_LIST"][1], logger=logger, config=config)]
for user in user_list:
    wx.AddListenChat(who=user.name, savepic=True)

ai = Ai(logger=logger, config=config)


###################################### 消息监听 存入'/tmp/memory'中 消息在user.user_queues中 ######################################
def message_listener():
    global wx
    logger.info("开始监听消息...")
    while True:
        try:
            if wx is None:
                logger.info("尝试重新连接微信...")
                wx = WeChat()
                logger.info("微信连接成功")

                for user in user_list:
                    wx.AddListenChat(who=user.name, savepic=True)
                logger.info("成功添加监听")

            msgs = wx.GetListenMessage()
            if msgs:
                logger.info(f"收到新消息: {msgs}")
            for chat in msgs:
                who = chat.who
                one_msgs = msgs.get(chat)
                logger.info(f"处理来自 {who} 的消息: {one_msgs}")
                print(f"【{who}】：{one_msgs}")
                for msg in one_msgs:
                    msg_type = msg.type
                    content = msg.content
                    logger.info(f'【{who}】：{content}')
                    if not content:
                        continue
                    if msg_type != 'friend':
                        logger.debug(f"非好友消息，忽略! 消息类型: {msg_type}")
                        continue
                    if who == msg.sender:
                        if '[动画表情]' in content and config["SEND_EMOJI_SWITCH"]:
                            handle_emoji_message(msg, who)
                        else:
                            handle_wx_message(msg, who)
                    else:
                        logger.debug(f"非需要处理消息: {content}")

        except Exception as e:
            logger.error(f"Message: {str(e)}")
            wx = None
        time.sleep(1)


def handle_emoji_message(msg, who):
    global emoji_timer
    name = who
    user = [user for user in user_list if user.name == name][0]
    user.can_send_messages = False

    def timer_callback():
        global emoji_timer
        with emoji_timer_lock:
            handle_wx_message(msg, who)
            emoji_timer = None

    with emoji_timer_lock:
        if emoji_timer is not None:
            emoji_timer.cancel()
        emoji_timer = threading.Timer(3.0, timer_callback)
        emoji_timer.start()


def handle_wx_message(msg, who):
    try:
        name = who
        user = [user for user in user_list if user.name == name][0]
        content = getattr(msg, 'content', None) or getattr(msg, 'text', None)
        img_path = None
        is_emoji = False

        user.make_user_auto_time()

        if content and content.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
            if config["HANDLE_IMAGE_SWITCH"]:
                img_path = content
                is_emoji = False
                content = None
            else:
                content = "[图片]"

        if content and "[动画表情]" in content:
            if config["HANDLE_EMOJI_SWITCH"]:
                img_path = screenshot_save(name)
                is_emoji = True
                content = None
            else:
                content = "[动画表情]"
                clean_temp_files()

        if img_path:
            user.logger.info(f"处理图片消息 - {name}: {img_path}")
            user.can_send_messages = False
            recognized_text = ai.moonshot_image(img_path, is_emoji=is_emoji, user=user)
            content = recognized_text if content is None else f"{content} {recognized_text}"
            clean_temp_files()

        if content:
            if config["MEMORY_SWITCH"]:
                user.make_log_user(content)

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            content = f"[{current_time}] {content}"
            logger.info(f"处理消息 - {name}: {content}")
            sender_name = name

            with user.queue_lock:  # 使用用户级别的锁
                if not user.user_queues:
                    user.user_queues = {
                        'messages': [content],
                        'name': name,
                        'last_message_time': time.time()
                    }
                    logger.info(f"已为 {sender_name} 初始化消息队列")
                else:
                    if len(user.user_queues['messages']) >= 5:
                        user.user_queues['messages'].pop(0)
                    user.user_queues['messages'].append(content)
                    user.user_queues['last_message_time'] = time.time()

                    logger.info(f"{sender_name} 的消息已加入队列并更新最后消息时间")
        else:
            logger.warning("无法获取消息内容")
    except Exception as e:
        logger.error(f"消息处理失败: {str(e)}")


def screenshot_save(name):
    screenshot_folder = os.path.join(root_dir, 'screenshot')
    if not os.path.exists(screenshot_folder):
        os.makedirs(screenshot_folder)
    screenshot_path = os.path.join(screenshot_folder, f'{name}_{datetime.now().strftime("%Y%m%d%H%M%S")}.png')

    try:
        # 激活并定位微信聊天窗口
        wx_chat = WeChat()
        wx_chat.ChatWith(name)
        chat_window = pyautogui.getWindowsWithTitle(name)[0]

        # 确保窗口被前置和激活
        if not chat_window.isActive:
            chat_window.activate()
        if not chat_window.isMaximized:
            chat_window.maximize()

        # 获取窗口的坐标和大小
        x, y, width, height = chat_window.left, chat_window.top, chat_window.width, chat_window.height

        time.sleep(1)

        # 截取指定窗口区域的屏幕
        screenshot = pyautogui.screenshot(region=(x, y, width, height))
        screenshot.save(screenshot_path)
        logger.info(f'已保存截图: {screenshot_path}')
        return screenshot_path
    except Exception as e:
        logger.error(f'保存截图失败: {str(e)}')


def clean_temp_files():
    if os.path.isdir("screenshot"):
        shutil.rmtree("screenshot")
        print(f"目录 screenshot 已成功删除")
    else:
        print(f"目录 screenshot 不存在，无需删除")

    if os.path.isdir("wxauto文件"):
        shutil.rmtree("wxauto文件")
        print(f"目录 wxauto文件 已成功删除")
    else:
        print(f"目录 wxauto文件 不存在，无需删除")


###################################### 在主线程中运行 ################################################


def remove_timestamps(text):
    """
    移除文本中所有[YYYY-MM-DD HH:MM:SS]格式的时间戳
    并自动清理因去除时间戳产生的多余空格
    """
    # 定义严格的时间戳正则模式（精确到秒级）
    timestamp_pattern = r'\[\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\s(?:2[0-3]|[01]\d):[0-5]\d:[0-5]\d\]'

    # 使用正则替换，将时间戳替换为空字符串
    return re.sub(
        pattern=timestamp_pattern,
        repl='',
        string=text
    ).strip()  # 最后统一清理首尾空格


async def process_user_messages(user):
    with user.queue_lock:  # 使用用户级别的锁
        if not user.user_queues:
            return
        messages = user.user_queues['messages']
        user.user_queues = {}

    merged_message = ' '.join(messages)
    logger.info(f"处理合并消息 ({user.name}): {merged_message}")

    reply = await ai.get_deepseek_response(merged_message, user)
    
    if "</think>" in reply:
        reply = reply.split("</think>", 1)[1].strip()

    if "## 记忆片段" not in reply:
        await send_reply(user, reply)

async def send_reply(user, reply):
    try:
        user.is_sending_message = True
        reply = remove_timestamps(reply)
        
        if '\\' in reply:
            parts = [p.strip() for p in reply.split('\\') if p.strip()]
            for i, part in enumerate(parts):
                wx.SendMsg(part, user.name)
                logger.info(f"分段回复 {user.name}: {part}")
                user.make_log_reply(part)

                if i < len(parts) - 1:
                    next_part = parts[i + 1]
                    delay = len(next_part) * (
                        config['AVERAGE_TYPING_SPEED'] + 
                        random.uniform(config['RANDOM_TYPING_SPEED_MIN'],
                                    config['RANDOM_TYPING_SPEED_MAX'])
                    )
                    if delay < 2:
                        delay = 2
                    await asyncio.sleep(delay)
        else:
            wx.SendMsg(reply, user.name)
            logger.info(f"回复 {user.name}: {reply}")
            user.make_log_reply(reply)

        user.is_sending_message = False

    except Exception as e:
        logger.error(f"发送回复失败: {str(e)}")
        user.is_sending_message = False

async def send_message():
    while True:
        tasks = []
        current_time = time.time()
        for user in user_list:
            if user.user_queues and current_time - user.user_queues['last_message_time'] > config['WAITING_TIME'] and user.can_send_messages and not user.is_sending_message:
                tasks.append(process_user_messages(user))
        if tasks:
            await asyncio.gather(*tasks)
        await asyncio.sleep(1)

def send_message_main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(send_message())
    except Exception as e:
        logger.error(f"消息处理循环发生错误: {str(e)}")
    finally:
        loop.close()


###################################### 启动线程 ################################################
def main():
    try:
        # 确保临时目录存在
        memory_temp_dir = os.path.join(root_dir, config['MEMORY_TEMP_DIR'])
        os.makedirs(memory_temp_dir, exist_ok=True)

        # clean_up_temp_files()

        global wx
        wx = WeChat()

        listener_thread = threading.Thread(target=message_listener)
        listener_thread.daemon = True
        listener_thread.start()

        checker_thread = threading.Thread(target=send_message_main)
        checker_thread.daemon = True
        checker_thread.start()

        # if ENABLE_MEMORY:
        #     # 启动记忆管理线程
        #     memory_thread = threading.Thread(target=memory_manager)
        #     memory_thread.daemon = True
        #     memory_thread.start()

        # # 启动后台线程来检查用户超时
        # if ENABLE_AUTO_MESSAGE:
        #     threading.Thread(target=check_user_timeouts, daemon=True).start()

        logger.info("开始运行BOT...")

        while True:
            time.sleep(1)
    except Exception as e:
        logger.error(f"发生异常: {str(e)}")
    except FileNotFoundError as e:
        logger.error(f"初始化失败: {str(e)}")
        print(f"\033[31m错误：{str(e)}\033[0m")
        exit(1)
    finally:
        logger.info("程序退出")


if __name__ == "__main__":
    main()
