"""服务端 OpenAI Chat 兼容客户端。错误信息不包含密钥或服务返回正文。"""
import os
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from dotenv import dotenv_values, load_dotenv

from ds_tutor.bank import ROOT

load_dotenv(ROOT / ".env", override=False)


def reload_model_settings():
    """用户主动刷新本地模型配置；不修改访问口令或学习空间设置。"""
    values = dotenv_values(ROOT / ".env")
    allowed = {"LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_TIMEOUT", "LLM_MAX_TOKENS",
               "LLM_SEND_ENABLE_THINKING", "LOCAL_BASE_URL", "LOCAL_API_KEY", "LOCAL_MODEL"}
    for key in allowed:
        if key in values:
            os.environ[key] = values[key] or ""


class ModelError(RuntimeError):
    pass


@dataclass
class Settings:
    base_url: str
    api_key: str
    model: str
    timeout: int = 60
    max_tokens: int = 700
    send_thinking: bool = False

    @property
    def ready(self):
        return bool(self.api_key and self.base_url and self.model)


def settings_for(mode):
    if mode == "云端 API":
        return Settings(os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                        os.getenv("LLM_API_KEY", ""), os.getenv("LLM_MODEL", "qwen-plus"),
                        int(os.getenv("LLM_TIMEOUT", "60")), int(os.getenv("LLM_MAX_TOKENS", "700")),
                        os.getenv("LLM_SEND_ENABLE_THINKING", "true").lower() == "true")
    return Settings(os.getenv("LOCAL_BASE_URL", "http://127.0.0.1:8000/v1"),
                    os.getenv("LOCAL_API_KEY", ""), os.getenv("LOCAL_MODEL", "ds-tutor-lora"),
                    120, 700, False)


def complete(messages, settings):
    if not settings.ready:
        raise ModelError("尚未配置模型连接。请在服务端 .env 中设置地址、模型名和密钥，然后重启应用。")
    parsed = urlparse(settings.base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ModelError("模型服务地址无效。")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ModelError("远程模型服务请使用 HTTPS，或经 SSH 隧道转发到本机。")
    payload = dict(model=settings.model, messages=messages, temperature=0.2,
                   max_tokens=settings.max_tokens, stream=False)
    if settings.send_thinking:
        payload["enable_thinking"] = False
    started = time.monotonic()
    try:
        response = requests.post(settings.base_url.rstrip("/") + "/chat/completions", json=payload,
                                 headers={"Authorization": f"Bearer {settings.api_key}"},
                                 timeout=(10, settings.timeout))
    except requests.Timeout:
        raise ModelError("模型响应超时，请稍后重试。题库解析仍然可以使用。") from None
    except requests.RequestException:
        raise ModelError("无法连接模型服务，请检查网络和服务端地址。") from None
    if response.status_code != 200:
        reasons = {401: "鉴权失败，请检查密钥", 403: "账号没有调用权限", 404: "模型名称或接口地址不存在",
                   429: "请求受限或可用额度不足"}
        raise ModelError(f"模型调用失败（HTTP {response.status_code}）：{reasons.get(response.status_code, '服务暂不可用')}。")
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError()
    except (ValueError, KeyError, TypeError, IndexError):
        raise ModelError("模型返回了无法识别的结果，请检查接口兼容性。") from None
    return {"content": content.strip(), "model": data.get("model", settings.model),
            "seconds": round(time.monotonic() - started, 2), "usage": data.get("usage", {})}
