"""模型通道自检：不用起服务，直接看主/备通道能不能用。

用法：
    python verify_llm.py            # 探活 + 一次真实请求
    python verify_llm.py --probe    # 只探活，不生成内容

2026-10-20 事故复盘用：上游 403 时页面上只看到「行程规划失败」，
这个脚本能在 3 秒内告诉你「哪条通道挂了、挂的原因、备用通道是否可用」。
"""
import asyncio
import sys

from config import LLM_CONFIG, LLM_FALLBACKS, LLM_PROBE_ON_STARTUP
from utils.llm_failover import build_chat_model
from utils.llm_errors import describe


def _mask(key: str) -> str:
    return f"{key[:6]}…{key[-4:]}" if key and len(key) > 12 else ("<empty>" if not key else "***")


async def main() -> int:
    print("── 配置 ────────────────────────────────────────────")
    print(f"主通道   : {LLM_CONFIG['base_url']}  model={LLM_CONFIG['model_name']}  key={_mask(LLM_CONFIG['api_key'])}")
    for fb in LLM_FALLBACKS:
        print(f"备用通道 : {fb['base_url']}  model={fb['model_name']}  key={_mask(fb.get('api_key', ''))}")
    if not LLM_FALLBACKS:
        print("备用通道 : 未配置（ALIGO_FALLBACK_* 为空，主通道挂了就直接失败）")

    model = build_chat_model(LLM_CONFIG, LLM_FALLBACKS, timeout=20.0)

    print("\n── 探活 ────────────────────────────────────────────")
    if hasattr(model, "probe"):
        report = await model.probe()
        for ch in report["channels"]:
            mark = "OK  " if ch.get("ok") else "FAIL"
            detail = "" if ch.get("ok") else f"  {ch.get('error', '')[:140]}"
            print(f"[{mark}] {ch['name']:<10} {ch['model']:<24} {detail}")
        if not report.get("active"):
            print("\n结论：所有通道都不可用，需要换 Key / 充值 / 换服务商。")
            return 2
    else:
        print("（未配置备用通道，跳过探活）")

    print("\n── 真实请求 ────────────────────────────────────────")
    try:
        resp = await model(
            [{"role": "user", "content": "只输出 JSON：{\"city\":\"上海\",\"days\":3}"}],
            max_tokens=200,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"请求失败：{describe(exc)}")
        return 3

    # ChatResponse.__getattr__ 会抛 KeyError，统一走项目的安全提取
    from utils.llm_response import extract_llm_text

    text = extract_llm_text(resp, fallback="")
    print(f"响应：{str(text)[:200] or '<空>'}")
    print(f"当前通道：{getattr(model, 'active_name', 'primary')}")
    print("\n结论：模型通道可用。")
    return 0


if __name__ == "__main__":
    if "--probe" in sys.argv:
        LLM_PROBE_ON_STARTUP = True
    sys.exit(asyncio.run(main()))
