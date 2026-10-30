"""将基座 + LoRA 暴露为受密钥保护的本机 OpenAI Chat 兼容服务。"""
import argparse
import hmac
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.inference import generate, load_model


def create_app(model, tokenizer, token):
    if len(token) < 16:
        raise ValueError("服务密钥至少需要 16 字符")
    from fastapi import Depends, FastAPI, HTTPException
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    from pydantic import BaseModel, Field
    app = FastAPI(title="数据结构智练模型服务", docs_url=None, redoc_url=None)
    bearer = HTTPBearer()
    lock = threading.Lock()

    class Message(BaseModel):
        role: Literal["system", "user", "assistant"]
        content: str = Field(min_length=1, max_length=12000)

    class Completion(BaseModel):
        model: str = "ds-tutor-lora"
        messages: list[Message] = Field(min_length=1, max_length=20)
        max_tokens: int = Field(default=384, ge=1, le=1024)
        temperature: float = Field(default=0.2, ge=0, le=2)
        stream: bool = False

    def authorized(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        if not hmac.compare_digest(credentials.credentials, token):
            raise HTTPException(401, "Invalid API key")

    @app.get("/health")
    def health():
        return {"status": "ok", "adapter_loaded": True}

    @app.get("/v1/models", dependencies=[Depends(authorized)])
    def models():
        return {"object": "list", "data": [{"id": name, "object": "model"} for name in ("ds-tutor-base", "ds-tutor-lora")]}

    @app.post("/v1/chat/completions", dependencies=[Depends(authorized)])
    def completion(body: Completion):
        if body.stream:
            raise HTTPException(400, "This teaching endpoint supports non-streaming responses only")
        if body.model not in {"ds-tutor-base", "ds-tutor-lora"}:
            raise HTTPException(404, "Unknown model")
        if sum(len(m.content) for m in body.messages) > 24000:
            raise HTTPException(413, "Input is too long")
        if not lock.acquire(blocking=False):
            raise HTTPException(429, "Model is busy; retry later")
        try:
            result = generate(model, tokenizer, [m.model_dump() for m in body.messages], body.max_tokens,
                              body.model == "ds-tutor-lora")
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        finally:
            lock.release()
        return {"id": "chatcmpl-"+uuid.uuid4().hex, "object": "chat.completion", "created": int(time.time()),
                "model": body.model, "choices": [{"index": 0, "message": {"role": "assistant", "content": result["content"]},
                                                   "finish_reason": "length" if result["output_tokens"] >= body.max_tokens else "stop"}],
                "usage": {"prompt_tokens": result["input_tokens"], "completion_tokens": result["output_tokens"],
                          "total_tokens": result["input_tokens"]+result["output_tokens"]}}

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--quantize", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("MODEL_API_KEY", "")
    if len(token) < 16:
        raise SystemExit("请先通过环境变量 MODEL_API_KEY 配置至少 16 字符的服务密钥，不要把密钥写入源码。")
    import uvicorn
    model, tokenizer, base_name = load_model(args.adapter, args.model, args.quantize)
    app = create_app(model, tokenizer, token)
    print(f"Loaded base model {base_name} and LoRA adapter. Listening on loopback only.")
    # 不开启公网监听。远端主机通过 SSH 转发到开发电脑使用。
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
