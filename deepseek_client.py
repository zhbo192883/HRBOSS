# -*- coding: utf-8 -*-
"""
DeepSeek Chat Completions 封装。
接口与 OpenAI 兼容格式一致：POST {base_url}  body: {model, messages, ...}
文档: https://api-docs.deepseek.com/
"""
import json

try:
    import requests
except Exception:
    requests = None


class DeepSeekError(Exception):
    pass


class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str = 'https://api.deepseek.com/chat/completions',
                 model: str = 'deepseek-chat', timeout: int = 20):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.api_key) and requests is not None

    def chat(self, system_prompt: str, user_message: str, history=None,
              temperature: float = 0.6, max_tokens: int = 300) -> str:
        """
        history: 可选，list of {'role': 'user'|'assistant', 'content': str}，按时间顺序，
                 用于让AI了解最近几轮对话上下文（建议只传最近3~5轮，控制成本和跑题风险）。
        返回：AI生成的回复文本（已 strip）。失败抛 DeepSeekError。
        """
        if requests is None:
            raise DeepSeekError('未安装 requests 库，无法调用 DeepSeek API')
        if not self.api_key:
            raise DeepSeekError('未配置 DeepSeek API Key')

        messages = [{'role': 'system', 'content': system_prompt}]
        for h in (history or []):
            role = h.get('role')
            content = h.get('content', '')
            if role in ('user', 'assistant') and content:
                messages.append({'role': role, 'content': content})
        messages.append({'role': 'user', 'content': user_message})

        payload = {
            'model': self.model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
            'stream': False,
        }
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
        }
        try:
            resp = requests.post(self.base_url, headers=headers, data=json.dumps(payload), timeout=self.timeout)
        except Exception as e:
            raise DeepSeekError(f'请求失败: {e}')
        if resp.status_code != 200:
            raise DeepSeekError(f'HTTP {resp.status_code}: {resp.text[:300]}')
        try:
            data = resp.json()
            text = data['choices'][0]['message']['content']
            return (text or '').strip()
        except Exception as e:
            raise DeepSeekError(f'解析返回失败: {e} | 原始: {resp.text[:300]}')
