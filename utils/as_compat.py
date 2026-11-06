# -*- coding: utf-8 -*-
"""AgentScope 1.x/2.x 双版本适配层。

设计约束（来自 docs/agentscope-2-upgrade-dev-plan.md §3.1/§5）：
- 全项目唯一允许接触 Msg.content 块结构的地方；
- 1.0.16 与 2.0.11 下行为逐位一致（迁移期保持 164 测试全绿，最后一步才切版本）；
- 业务代码禁止直接构造 Msg(content=裸str) / json.loads(x.content) / str(content)，
  一律经由此模块的 mk_msg / msg_text / msg_json。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

# ── 版本探测 ────────────────────────────────────────────────────────────────
try:  # agentscope >= 2.0：工厂函数（str 自动转块列表）
    from agentscope.message import AssistantMsg as _AssistantMsg
    from agentscope.message import SystemMsg as _SystemMsg
    from agentscope.message import UserMsg as _UserMsg

    AS_MAJOR = 2
except ImportError:  # agentscope 1.x：直接用 Msg（str content 合法）
    _AssistantMsg = _UserMsg = _SystemMsg = None
    AS_MAJOR = 1

from agentscope.message import Msg

__all__ = [
    "AS_MAJOR",
    "mk_msg",
    "msg_text",
    "msg_json",
    "as_messages",
    "chat_text",
    "build_chat_model",
    "setup",
]


# ── 内部工具 ────────────────────────────────────────────────────────────────
def _safe_getattr(obj: Any, name: str, default: Any = None) -> Any:
    """安全的 getattr。

    agentscope 1.x 的 ChatResponse 用 __getattr__ 抛 KeyError（不是 AttributeError），
    内置 getattr(obj, name, default) 只捕获 AttributeError，会漏出去 —— 实测踩坑。
    """
    try:
        return getattr(obj, name)
    except (AttributeError, KeyError, TypeError):
        return default


def _looks_like_blocks(content: Any) -> bool:
    """判断是否已是块列表（2.x ContentBlock 对象或 {"type": ...} dict）。

    注意：不能只认带 .text 的对象——ThinkingBlock/ToolCallBlock 等块没有 .text 字段。
    判据：dict 必须有字符串 type；对象必须有字符串 type 属性。
    """
    if not isinstance(content, list) or not content:
        return False
    for c in content:
        if isinstance(c, dict):
            if isinstance(c.get("type"), str):
                continue
            return False
        if isinstance(getattr(c, "type", None), str):
            continue
        return False
    return True


def _to_text(content: Any, fallback: str = "") -> str:
    if content is None:
        return fallback
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        # 兼容 skill shim 时代的 {"type": "text", "text": ...} 单块
        if content.get("type") == "text":
            return content.get("text") or fallback
        return json.dumps(content, ensure_ascii=False)
    if _looks_like_blocks(content):
        parts = []
        for c in content:
            if isinstance(c, dict):
                parts.append(c.get("text", "") if c.get("type") == "text" else "")
            else:
                # 2.x 真实块对象：只有 TextBlock 有 .text；ThinkingBlock 等不产生文本
                if getattr(c, "type", "") == "text":
                    parts.append(getattr(c, "text", "") or "")
        joined = "".join(p for p in parts if p)
        return joined or fallback
    try:
        return json.dumps(content, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(content)


def _factory_for(role: str):
    if AS_MAJOR >= 2:
        return {"user": _UserMsg, "system": _SystemMsg}.get(role, _AssistantMsg)
    return None


# ── 公开 API ────────────────────────────────────────────────────────────────
def mk_msg(
    name: str,
    content: Any,
    role: str = "assistant",
    metadata: Optional[dict] = None,
) -> Msg:
    """统一消息构造：str / dict / list / 块列表 / None 都能接。

    - str 与 dict/list 负载统一转为 JSON 文本（保持 1.x 时代 content 即 JSON 字符串的既有契约）；
    - 已是块列表的输入原样透传；
    - metadata 两个版本都支持。
    """
    if _looks_like_blocks(content):
        blocks = content
        factory = _factory_for(role)
        if factory is not None:
            return factory(name=name, content=blocks, metadata=metadata or {})
        return Msg(name=name, content=blocks, role=role, metadata=metadata or {})

    text = _to_text(content, fallback="")
    factory = _factory_for(role)
    if factory is not None:
        return factory(name=name, content=text, metadata=metadata or {})
    return Msg(name=name, content=text, role=role, metadata=metadata or {})


def msg_text(msg: Any, fallback: str = "") -> str:
    """把消息 / 响应取成纯文本。业务代码里所有 content 读取的唯一出口。

    - 2.x：优先 get_text_content()；content 为块列表时拼接 text 块；
    - 1.x：content 为 str 时直接返回；
    - thinking-only（无 text）→ 返回 fallback（保留 MiMo 特判语义）。
    """
    if msg is None:
        return fallback
    get = _safe_getattr(msg, "get_text_content")
    if callable(get):
        try:
            t = get()
        except Exception:
            t = None
        if isinstance(t, str) and t.strip():
            return t
    content = _safe_getattr(msg, "content")
    if isinstance(content, str):
        return content if content.strip() else fallback
    text = _to_text(content, fallback=fallback)
    return text


def msg_json(msg: Any, default: Any = None) -> Any:
    """从消息文本健壮解析 JSON（复用 utils.json_parser 六级降级）。"""
    from utils.json_parser import robust_json_parse

    text = msg_text(msg)
    if not text or not text.strip():
        return default
    try:
        return robust_json_parse(text, fallback=default)
    except (ValueError, TypeError):
        return default


def as_messages(items: Iterable[Any]) -> list:
    """把 1.x 风格 list[dict]（{"role","content"}）转成 list[Msg]。

    迁移期用它包住旧调用点（ChatModelBase.__call__ 在 2.x 要求 list[Msg]）；
    Msg 对象原样透传。
    """
    out = []
    for it in items:
        if AS_MAJOR >= 2:
            # 2.x：ChatModelBase.__call__ 要求 list[Msg]
            if isinstance(it, Msg):
                out.append(it)
            elif isinstance(it, dict):
                role = it.get("role") or "user"
                out.append(mk_msg(name=it.get("name") or role, content=it.get("content"), role=role))
            else:
                out.append(mk_msg(name="user", content=str(it), role="user"))
        else:
            # 1.x：OpenAIChatModel.__call__ 要求 list[dict]（已实测签名）
            if isinstance(it, Msg):
                out.append({"role": getattr(it, "role", "user"), "content": msg_text(it)})
            elif isinstance(it, dict):
                out.append(it)
            else:
                out.append({"role": "user", "content": str(it)})
    return out


def chat_text(resp: Any, fallback: str = "") -> str:
    """从模型响应（ChatResponse / ModelResponse / Msg / dict）提取纯文本。

    语义与 utils/llm_response.extract_llm_text 对齐：先 .text，再 .content，
    thinking-only → fallback。
    """
    if resp is None:
        return fallback
    t = _safe_getattr(resp, "text")
    if isinstance(t, str) and t.strip():
        return t
    if _safe_getattr(resp, "get_text_content") is not None or _safe_getattr(resp, "content") is not None:
        return msg_text(resp, fallback=fallback)
    if isinstance(resp, dict):
        c = resp.get("content") or resp.get("text") or ""
        return _to_text(c, fallback=fallback) if c else fallback
    s = str(resp)
    return s if s.strip() and s != "None" else fallback


def build_chat_model(cfg: dict, stream: bool = False, **overrides: Any):
    """全项目唯一 OpenAIChatModel 构造点（llm_failover 多通道共用）。

    1.x：model_name/api_key/generate_kwargs/client_kwargs 旧签名；
    2.x：credential=OpenAICredential(...) + model= + parameters=OpenAIChatModel.Parameters(...)。
    """
    import agentscope
    from agentscope.model import OpenAIChatModel

    generate_kwargs = {
        **(cfg.get("generate_kwargs") or {}),
        **(cfg.get("overrides") or {}),
        **{k: v for k, v in overrides.items() if k in ("max_tokens", "temperature", "top_p")},
    }
    client_kwargs = cfg.get("client_kwargs") or {}
    api_key = cfg.get("api_key")
    model_name = overrides.get("model", cfg.get("model_name"))
    base_url = cfg.get("base_url")
    stream = bool(overrides.get("stream", stream))

    major = int(getattr(agentscope, "__version__", "1").split(".")[0])
    if major >= 2:
        from agentscope.credential import OpenAICredential

        params_kwargs = {}
        if generate_kwargs.get("max_tokens") is not None:
            params_kwargs["max_tokens"] = generate_kwargs["max_tokens"]
        if generate_kwargs.get("temperature") is not None:
            params_kwargs["temperature"] = generate_kwargs["temperature"]
        if generate_kwargs.get("top_p") is not None:
            params_kwargs["top_p"] = generate_kwargs["top_p"]
        return OpenAIChatModel(
            credential=OpenAICredential(api_key=api_key, base_url=base_url),
            model=model_name,
            parameters=OpenAIChatModel.Parameters(**params_kwargs) if params_kwargs else None,
            stream=stream,
            max_retries=int(cfg.get("max_retries", 2)),
            retry_delay=float(cfg.get("retry_delay", 1.0)),
            client_kwargs=client_kwargs,
        )
    return OpenAIChatModel(
        model_name=model_name,
        api_key=api_key,
        stream=stream,
        client_kwargs={**client_kwargs, **({"base_url": base_url} if base_url and "base_url" not in client_kwargs else {})},
        generate_kwargs=generate_kwargs,
    )


def setup(logging_level: str = "INFO", **kwargs: Any) -> None:
    """替代 agentscope.init(project=, name=, logging_level=)。

    2.x：agentscope.setup_logger(level, filepath)；1.x：保留 init 兼容（project/name 语义 2.x 已删除）。
    函数名 init_agentscope() 的幂等语义由 config_agentscope.py 保持。
    """
    import agentscope

    major = int(getattr(agentscope, "__version__", "1").split(".")[0])
    if major >= 2:
        from agentscope import setup_logger

        setup_logger(level=logging_level)
        logger.info("AgentScope %s logger ready (setup_logger)", agentscope.__version__)
    else:
        agentscope.init(
            project=kwargs.get("project", "Aligo-Travel-Planning"),
            name=kwargs.get("name", "multi_agent_system"),
            logging_level=logging_level,
        )
        logger.info("AgentScope %s initialized", agentscope.__version__)


# ── 结构化输出（P6a）────────────────────────────────────────────────────────
def build_tool_schema(name: str, description: str, properties: Dict[str, Any], required: Optional[list] = None) -> Dict[str, Any]:
    """构造 OpenAI function-tool JSON schema（供强制单工具调用承载结构化输出）。"""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


def extract_tool_call_json(resp: Any, default: Any = None) -> Any:
    """从模型响应的 tool_call 块里取 JSON（2.x Agent.reply(structured_schema) 的机制）。

    端点需支持 function calling（glm/compatible-mode 实测支持 auto/required/forced 三种模式）。
    没有 tool_call 块或 JSON 非法 → 返回 default（调用方自行回退到文本解析）。
    """
    blocks = _safe_getattr(resp, "content", None)
    if not isinstance(blocks, list):
        return default
    for block in blocks:
        if getattr(block, "type", None) != "tool_call" and not (
            isinstance(block, dict) and block.get("type") == "tool_call"
        ):
            continue
        raw = getattr(block, "input", None)
        if raw is None and isinstance(block, dict):
            raw = block.get("input")
        if raw is None:
            continue
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            return default
    return default
