# -*- coding: utf-8 -*-
"""DeepSeek 异步调用层：行为决策 / 聊天流式 / 余额 / 连接测试 / 识图。

- 全程在后台线程的 asyncio 事件循环中运行，绝不阻塞 UI。
- 单次超时 8s，不重试（避免堆积）；错误通过信号上报，由主程序决定是否切兜底。
- 日志中 Key 一律脱敏。
"""
import asyncio
import json
import threading
from typing import Any, Dict, List, Optional

import httpx
from PyQt6.QtCore import QObject, pyqtSignal

from . import const
from .logging_setup import setup_logging
from .util import mask_key

log = setup_logging()

TIMEOUT = 8.0


class LLMClient(QObject):
    # 信号均通过 Qt 队列投递到主线程
    verified = pyqtSignal(bool, str)
    behavior_ready = pyqtSignal(dict)
    chat_delta = pyqtSignal(str)
    chat_done = pyqtSignal(str, str)      # full_text, sticker_keyword
    chat_failed = pyqtSignal(str)
    balance_ready = pyqtSignal(dict)
    balance_failed = pyqtSignal(str)
    status = pyqtSignal(str)
    failures = pyqtSignal(int, str)       # 连续失败次数, 原因

    def __init__(self, config) -> None:
        super().__init__()
        self.cfg = config
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._client = None
        self._fail_count = 0
        self._busy = False                 # 行为请求进行中（复用上一帧）
        self._chat_busy = False
        self._fallback_model: Optional[str] = None   # 模型名被拒时回退到官方模型

    def _model_name(self) -> str:
        return self._fallback_model or self.cfg.model

    def _is_model_error(self, code: int, text: str) -> bool:
        return code in (400, 404) and "model" in (text or "").lower()

    # ------------------------------------------------------------ 生命周期
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, name="llm-loop", daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._client = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True)
        self._loop.run_forever()

    def stop(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    async def _aclose(self) -> None:
        if self._client:
            await self._client.aclose()

    def _submit(self, coro) -> None:
        if self._loop is None:
            self.start()
            # 稍等循环就绪
            for _ in range(50):
                if self._loop is not None:
                    break
                threading.Event().wait(0.02)
        if self._loop:
            asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ------------------------------------------------------------ 请求头
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }

    def _chat_url(self) -> str:
        base = self.cfg.base_url
        if base.endswith("/v1"):
            return base + "/chat/completions"
        return base + "/chat/completions"

    def _models_url(self) -> str:
        base = self.cfg.base_url
        if base.endswith("/v1"):
            return base + "/models"
        return base + "/models"

    def _balance_url(self) -> str:
        base = self.cfg.base_url
        if base.endswith("/v1"):
            base = base[:-3]
        return base + "/user/balance"

    # ------------------------------------------------------------ 测试连接
    def verify(self) -> None:
        self._submit(self._verify())

    async def _verify(self) -> None:
        if not self.cfg.has_key():
            self.verified.emit(False, "还没有填写 API Key 哦")
            return
        try:
            r = await self._client.get(self._models_url(), headers=self._headers())
            if r.status_code == 200:
                self.verified.emit(True, "连接成功，模型可用")
                return
            self.verified.emit(False, self._explain(r.status_code, r.text))
        except httpx.TimeoutException:
            self.verified.emit(False, "连接超时：请检查网络或 base_url")
        except Exception as e:
            self.verified.emit(False, f"连接失败：{type(e).__name__}")

    def _explain(self, code: int, text: str) -> str:
        if code in (401, 403):
            return "API Key 无效或已失效（401/403）"
        if code == 429:
            return "请求过于频繁，被限流了（429）"
        if code >= 500:
            return f"服务端错误（{code}）"
        snippet = (text or "")[:120].replace("\n", " ")
        return f"错误（{code}）：{snippet}"

    # ------------------------------------------------------------ 行为决策
    def request_behavior(self, prompt: str) -> None:
        if self._busy:
            return
        self._busy = True
        self._submit(self._behavior(prompt))

    async def _behavior(self, prompt: str) -> None:
        try:
            payload = {
                "model": self._model_name(),
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "根据环境决定下一步动作，只输出JSON。"},
                ],
                "temperature": 0.4,
                "max_tokens": 120,
                "response_format": {"type": "json_object"},
                "stream": False,
            }
            r = await self._client.post(self._chat_url(), headers=self._headers(), json=payload)
            if r.status_code != 200:
                if self._is_model_error(r.status_code, r.text) and not self._fallback_model:
                    self._fallback_model = const.DEFAULT_MODEL
                    log.warning("模型 %s 不可用，自动回退到 %s", self.cfg.model, const.DEFAULT_MODEL)
                    await self._behavior(prompt)
                    return
                self._on_fail(r.status_code, self._explain(r.status_code, r.text))
                return
            data = r.json()
            text = data["choices"][0]["message"]["content"]
            obj = _safe_json(text)
            if obj is None:
                # 解析失败仅重试一次
                text2 = await self._behavior_retry(prompt)
                obj = _safe_json(text2) if text2 else None
            if obj is None:
                self._on_fail(0, "JSON 解析失败")
                return
            self._fail_count = 0
            self.behavior_ready.emit(obj)
        except httpx.TimeoutException:
            self._on_fail(-1, "超时")
        except Exception as e:
            self._on_fail(-2, type(e).__name__)
        finally:
            self._busy = False

    async def _behavior_retry(self, prompt: str) -> Optional[str]:
        try:
            payload = {
                "model": self.cfg.model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "只输出JSON，不要多余文字。"},
                ],
                "temperature": 0.2, "max_tokens": 120,
                "response_format": {"type": "json_object"},
            }
            r = await self._client.post(self._chat_url(), headers=self._headers(), json=payload)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
        except Exception:
            pass
        return None

    def _on_fail(self, code: int, reason: str) -> None:
        self._fail_count += 1
        if code in (401, 403):
            self.cfg.mark_verified(False)
        log.warning("LLM 请求失败(%s)：%s", code, reason)
        self.failures.emit(self._fail_count, reason)

    # ------------------------------------------------------------ 聊天（流式）
    def chat(self, messages: List[Dict[str, str]]) -> None:
        if self._chat_busy:
            return
        self._chat_busy = True
        self._submit(self._chat(messages))

    async def _chat(self, messages: List[Dict[str, str]]) -> None:
        full = ""
        try:
            payload = {
                "model": self._model_name(),
                "messages": messages,
                "temperature": float(self.cfg.get("temperature", 0.4)),
                "max_tokens": 512,
                "stream": True,
            }
            async with self._client.stream(
                "POST", self._chat_url(), headers=self._headers(), json=payload
            ) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode("utf-8", "ignore")
                    if self._is_model_error(r.status_code, body) and not self._fallback_model:
                        self._fallback_model = const.DEFAULT_MODEL
                        log.warning("模型 %s 不可用，自动回退到 %s", self.cfg.model, const.DEFAULT_MODEL)
                        await self._chat(messages)
                        return
                    self.chat_failed.emit(self._explain(r.status_code, body))
                    self._on_fail(r.status_code, self._explain(r.status_code, body))
                    return
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"].get("content") or ""
                    except Exception:
                        continue
                    if delta:
                        full += delta
                        self.chat_delta.emit(delta)
            self._fail_count = 0
            text, keyword = _split_sticker(full)
            self.chat_done.emit(text, keyword)
        except httpx.TimeoutException:
            self.chat_failed.emit("对话超时，网络好像不太通")
            self._on_fail(-1, "超时")
        except Exception as e:
            self.chat_failed.emit(f"对话失败：{type(e).__name__}")
            self._on_fail(-2, type(e).__name__)
        finally:
            self._chat_busy = False

    # ------------------------------------------------------------ 识图
    def see_screen(self, image_data_url: str, prompt: str) -> None:
        self._submit(self._see(image_data_url, prompt))

    async def _see(self, image_data_url: str, prompt: str) -> None:
        full = ""
        try:
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": "看看主人的屏幕，用大肥鱼的语气说说你看到了什么~"},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ]},
            ]
            payload = {
                "model": self._model_name(),
                "messages": messages,
                "temperature": 0.5,
                "max_tokens": 300,
                "stream": True,
            }
            async with self._client.stream(
                "POST", self._chat_url(), headers=self._headers(), json=payload
            ) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode("utf-8", "ignore")
                    if self._is_model_error(r.status_code, body) and not self._fallback_model:
                        self._fallback_model = const.DEFAULT_MODEL
                        log.warning("模型 %s 不可用，自动回退到 %s", self.cfg.model, const.DEFAULT_MODEL)
                        await self._see(image_data_url, prompt)
                        return
                    self.chat_failed.emit("本鱼的眼睛好像出问题了…（当前模型可能不支持识图）")
                    self._on_fail(r.status_code, self._explain(r.status_code, body))
                    return
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content") or ""
                    except Exception:
                        continue
                    if delta:
                        full += delta
                        self.chat_delta.emit(delta)
            text, keyword = _split_sticker(full)
            self.chat_done.emit(text, keyword)
        except Exception:
            self.chat_failed.emit("本鱼看不清屏幕啦，可能模型不支持识图哦")

    # ------------------------------------------------------------ 余额
    def query_balance(self) -> None:
        self._submit(self._balance())

    async def _balance(self) -> None:
        if not self.cfg.has_key():
            self.balance_failed.emit("未配置 API Key")
            return
        try:
            r = await self._client.get(self._balance_url(), headers=self._headers())
            if r.status_code == 200:
                self.balance_ready.emit(r.json())
            else:
                self.balance_failed.emit(self._explain(r.status_code, r.text))
        except httpx.TimeoutException:
            self.balance_failed.emit("查询超时")
        except Exception as e:
            self.balance_failed.emit(type(e).__name__)


# ---------------------------------------------------------------- 工具
def _safe_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None


def _split_sticker(text: str):
    """从回复末尾解析 [表情:xxx]，返回 (正文, 关键词)。"""
    import re
    keyword = None
    m = re.search(r"\[表情[:：]\s*([^\]]+)\]", text)
    if m:
        keyword = m.group(1).strip()
        text = (text[:m.start()] + text[m.end():]).strip()
    return text, keyword
