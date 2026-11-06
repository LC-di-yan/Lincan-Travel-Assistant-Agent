# -*- coding: utf-8 -*-
"""静态门禁测试：AgentScope 2.x 迁移期禁止的写法（棘轮机制）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.check_as2_gate import ALLOWLIST, scan  # noqa: E402


def test_no_ungated_legacy_patterns():
    violations = scan()
    allow = set(json.loads(ALLOWLIST.read_text(encoding="utf-8"))) if ALLOWLIST.exists() else set()
    unknown = [v for v in violations if v not in allow]
    assert not unknown, (
        "发现未登记的 1.x 写法（应改用 utils/as_compat.py）：\n  "
        + "\n  ".join(unknown[:20])
        + "\n\n修复后运行: python tools/check_as2_gate.py --prune"
    )


def test_allowlist_is_shrinking_not_stale():
    """白名单里不应保留已修复的条目（防止棘轮虚高掩盖回归）。"""
    violations = set(scan())
    allow = set(json.loads(ALLOWLIST.read_text(encoding="utf-8"))) if ALLOWLIST.exists() else set()
    stale = sorted(allow - violations)
    assert not stale, (
        f"白名单有 {len(stale)} 条已修复项未清理，请运行 "
        f"python tools/check_as2_gate.py --prune\n  " + "\n  ".join(stale[:10])
    )
