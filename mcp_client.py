import asyncio
from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
import json
from typing import Optional
from contextlib import AsyncExitStack
import os
from dotenv import load_dotenv

from mcp.client.stdio import stdio_client

# 加载环境变量
load_dotenv()

# 从环境变量获取配置
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', 'sk-c75206b1e7d54fa4b58fa1a6d5402586')
DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')


class MCPClient:
    def __init__(self):
        """初始化 MCP 客户端"""
        self.exit_stack = AsyncExitStack()
        self.openai_api_key = DEEPSEEK_API_KEY
        self.base_url = DEEPSEEK_BASE_URL
        self.model = DEEPSEEK_MODEL
        self.client = OpenAI(api_key=self.openai_api_key, base_url=self.base_url)
        self.session: Optional[ClientSession] = None

    async def connect_to_mock_server(self, server_script_path: str):
        """连接到 MCP 服务器并列出可用工具"""
        is_python = server_script_path.endswith(".py")
        is_js = server_script_path.endswith(".js")
        if not (is_python or is_js):
            raise ValueError("服务器脚本文件名必须以 .py 或 .js 结尾")

        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path],
            env=None
        )

        # 启动 MCP 服务器并建立通信
        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

        await self.session.initialize()

        # 列出 MCP 服务器上的工具
        response = await self.session.list_tools()
        tools = response.tools
        print("\n已连接到服务器，支持以下工具:", [tool.name for tool in tools])

    async def process_query(self, query: str) -> str:
        """使用大模型处理查询并调用可用的 MCP 工具 (Function Calling)"""
        try:
            messages = [{"role": "user", "content": query}]
            response = await self.session.list_tools()
            available_tools = [{
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema
                }
            } for tool in response.tools]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=available_tools
            )

            content = response.choices[0]
            if content.finish_reason == "tool_calls":
                tool_call = content.message.tool_calls[0]
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                try:
                    result = await self.session.call_tool(tool_name, tool_args)
                    print(f"\n\n[Calling tool {tool_name} with args {tool_args}]\n\n")

                    messages.append(content.message.model_dump())
                    messages.append({
                        "role": "tool",
                        "content": result.content[0].text,
                        "tool_call_id": tool_call.id,
                    })

                    #############对messages进行修改#############

                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                    )
                    return response.choices[0].message.content
                except Exception as e:
                    print(f"工具调用失败: {str(e)}")
                    return f"抱歉，工具调用失败: {str(e)}"

            return response.message.content
        except Exception as e:
            print(f"处理查询时发生错误: {str(e)}")
            return f"抱歉，处理您的请求时发生错误: {str(e)}"

    async def chat_loop(self):
        """运行交互式聊天循环"""
        print("\nMCP 客户端已启动！输入 'quit' 退出")
        try:
            while True:
                try:
                    query = input("\nQuery: ").strip()
                    if query.lower() == 'quit':
                        break
                    response = await self.process_query(query)
                    print(f"\nResponse: {response}")
                except KeyboardInterrupt:
                    print("\n\n程序被用户中断")
                    break
                except Exception as e:
                    print(f"\n⚠ 发生错误: {str(e)}")
        finally:
            print("\n正在清理资源...")
            await self.cleanup()

    async def cleanup(self):
        """清理资源"""
        await self.exit_stack.aclose()


async def main():
    client = MCPClient()
    try:
        await client.connect_to_mock_server('.\server.py')
        await client.chat_loop()
    finally:
        await client.cleanup()


if __name__ == "__main__":
    import sys

    asyncio.run(main())
