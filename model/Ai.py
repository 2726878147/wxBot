import base64
import aiohttp

import requests
from openai import OpenAI


class Ai:
    def __init__(self, logger, config):
        self.config = config
        self.logger = logger
        self.DEEPSEEK_API_KEY = config["DEEPSEEK_API_KEY"]
        self.DEEPSEEK_BASE_URL = config["DEEPSEEK_BASE_URL"]
        self.DEEPSEEK_MODEL = config["DEEPSEEK_MODEL"]
        self.MOONSHOT_API_KEY = config["MOONSHOT_API_KEY"]
        self.MOONSHOT_BASE_URL = config["MOONSHOT_BASE_URL"]
        self.MOONSHOT_MODEL = config["MOONSHOT_MODEL"]
        self.MAX_TOKEN = config["MAX_TOKEN"]
        self.TEMPERATURE = config["TEMPERATURE"]
        self.MOONSHOT_TEMPERATURE = config["MOONSHOT_TEMPERATURE"]
        self.openai_client = self.get_client()

    def get_client(self):
        return OpenAI(api_key=self.DEEPSEEK_API_KEY, base_url=self.DEEPSEEK_BASE_URL)

    def moonshot_image(self, image_path, is_emoji=False, user=None):
        with open(image_path, 'rb') as img_file:
            image_content = base64.b64encode(img_file.read()).decode('utf-8')
        headers = {
            'Authorization': f'Bearer {self.MOONSHOT_API_KEY}',
            'Content-Type': 'application/json'
        }
        text_prompt = "请描述这个图片" if not is_emoji else "请描述这个聊天窗口的最后一张表情包"
        data = {
            "model": self.MOONSHOT_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_content}"}},
                        {"type": "text", "text": text_prompt}
                    ]
                }
            ],
            "temperature": self.MOONSHOT_TEMPERATURE
        }
        try:
            response = requests.post(f"{self.MOONSHOT_BASE_URL}/chat/completions", headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            recognized_text = result['choices'][0]['message']['content']
            if is_emoji:
                if "最后一张表情包是" in recognized_text:
                    recognized_text = recognized_text.split("最后一张表情包是", 1)[1].strip()
                recognized_text = "发送了表情包：" + recognized_text
            else:
                recognized_text = "发送了图片：" + recognized_text
            self.logger.info(f"Moonshot AI图片识别结果: {recognized_text}")
            if user:
                user.can_send_messages = True
            return recognized_text

        except Exception as e:
            self.logger.error(f"调用Moonshot AI识别图片失败: {str(e)}")
            if user:
                user.can_send_messages = True
            return ""

    async def get_deepseek_response(self, message, user):
        """
        异步版本的DeepSeek响应获取方法
        """
        try:
            self.logger.info(f"调用 Chat API - 用户ID: {user.name}, 消息: {message}")
            user_prompt = user.prompt
            user.chat_contexts.append({"role": "user", "content": message})

            MAX_GROUPS = 10
            while len(user.chat_contexts) > MAX_GROUPS * 2:
                user.chat_contexts.pop(0)

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.DEEPSEEK_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.DEEPSEEK_MODEL,
                        "messages": [
                            {"role": "system", "content": user_prompt},
                            *user.chat_contexts[-MAX_GROUPS * 2:]
                        ],
                        "temperature": self.TEMPERATURE,
                        "max_tokens": self.MAX_TOKEN,
                        "stream": False
                    }
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        self.logger.error(f"API请求失败: {error_text}")
                        return "服务响应异常，请稍后再试"

                    result = await response.json()
                    if not result.get('choices'):
                        user.logger.error("API返回空choices")
                        return "服务响应异常，请稍后再试"

                    reply = result['choices'][0]['message']['content'].strip()
                    user.chat_contexts.append({"role": "assistant", "content": reply})

                    self.logger.info(f"API回复: {reply}")
                    return reply

        except Exception as e:
            ErrorImformation = str(e)
            self.logger.error(f"Chat调用失败: {str(e)}", exc_info=True)
            if "real name verification" in ErrorImformation:
                print("\033[31m错误：API服务商反馈请完成实名认证后再使用！ \033[0m")
            elif "rate" in ErrorImformation:
                print("\033[31m错误：API服务商反馈当前访问API服务频次达到上限，请稍后再试！ \033[0m")
            elif "paid" in ErrorImformation:
                print("\033[31m错误：API服务商反馈您正在使用付费模型，请先充值再使用或使用免费额度模型！ \033[0m")
            elif "Api key is invalid" in ErrorImformation:
                print("\033[31m错误：API服务商反馈API KEY不可用，请检查配置选项！ \033[0m")
            elif "busy" in ErrorImformation:
                print("\033[31m错误：API服务商反馈服务器繁忙，请稍后再试！ \033[0m")
            else:
                print("\033[31m错误： " + str(e) + "\033[0m")
            return "抱歉，我现在有点忙，稍后再聊吧。"