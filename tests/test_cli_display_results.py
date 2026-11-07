# -*- coding: utf-8 -*-
"""AligoCLI._display_results 渲染契约测试。

背景：tests/test_cli_qa.py 依赖 cli.AligoCLI._display_results 把聚合结果渲染成文本，
但该方法此前在 cli.py 中缺失（既有接口漂移），导致 QA 脚本 10 题全部卡在渲染步骤。
本测试锁定聚合渲染契约，并与流式路径共用 _display_single_agent_result 的事实。
"""
from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from rich.console import Console  # noqa: E402

from cli import AligoCLI  # noqa: E402


def _render(result_data) -> str:
    """不走 AligoCLI.__init__（需要 key/DB），只验证渲染逻辑。"""
    cli = AligoCLI.__new__(AligoCLI)
    buf = StringIO()
    cli.console = Console(file=buf, force_terminal=False, no_color=True, width=200)
    cli._display_results(result_data)
    return buf.getvalue().strip()


def _rag_item(answer: str, priority: int = 1) -> dict:
    return {
        "agent_name": "rag_knowledge",
        "priority": priority,
        "status": "success",
        "data": {"answer": answer},
    }


def test_renders_agent_answers_from_aggregated_results():
    out = _render({
        "status": "completed",
        "agents_executed": 1,
        "results": [_rag_item("住宿费上限 600 元/晚")],
    })
    assert "住宿费上限 600 元/晚" in out


def test_respects_priority_order():
    out = _render({
        "status": "completed",
        "results": [
            _rag_item("后执行的内容", priority=2),
            _rag_item("先执行的内容", priority=1),
        ],
    })
    assert out.index("先执行的内容") < out.index("后执行的内容")


def test_top_level_error_is_surfaced():
    out = _render({"error": "解析结果失败"})
    assert "解析结果失败" in out


def test_no_agents_status_is_handled():
    out = _render({"status": "no_agents", "message": "没有需要调度的智能体"})
    assert "没有需要调度的智能体" in out


def test_partial_failure_is_flagged():
    out = _render({
        "status": "partial_failure",
        "errors": 1,
        "results": [
            _rag_item("正常答案"),
            {"agent_name": "hotel_search", "priority": 2, "status": "error",
             "data": {"error": "高德接口超时"}},
        ],
    })
    assert "正常答案" in out
    assert "高德接口超时" in out
    assert "部分智能体失败" in out


def test_empty_and_none_inputs_do_not_raise():
    assert "没有可显示的结果" in _render(None)
    assert "没有可显示的结果" in _render({})
    assert "没有产生智能体结果" in _render({"status": "completed", "results": []})


def test_shares_renderer_with_streaming_path():
    """聚合路径与流式路径必须产出同一行文本（共用 _display_single_agent_result）。"""
    item = _rag_item("同一份答案")
    aggregated = _render({"status": "completed", "results": [item]})

    cli = AligoCLI.__new__(AligoCLI)
    buf = StringIO()
    cli.console = Console(file=buf, force_terminal=False, no_color=True, width=200)
    cli._display_single_agent_result(item)
    assert buf.getvalue().strip() == aggregated
