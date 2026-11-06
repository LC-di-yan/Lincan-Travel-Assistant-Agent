# -*- coding: utf-8 -*-
"""AgentScope 2.0 升级静态门禁（docs/agentscope-2-upgrade-dev-plan.md §4.P0）。

用法：
    python tools/check_as2_gate.py            # 检查：白名单之外的违规 = 退出码 1
    python tools/check_as2_gate.py --update   # 把当前全部违规写入白名单（棘轮基准）
    python tools/check_as2_gate.py --prune    # 从白名单里删掉已修复的条目（收缩棘轮）

白名单：data/as2_gate_allowlist.json，形如 ["path:line:pattern_id", ...]
机制：违规集合 ⊆ 白名单 才算通过；随 P2/P3 推进用 --prune 收缩白名单。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "data" / "as2_gate_allowlist.json"

SKIP_DIR = re.compile(r"(^|[\\/])(\.git|venv|\.venv|node_modules|site-packages|__pycache__|experiments|data|cache|image|private|db|docs|web)([\\/]|$)")
SCAN_FILES = ["agents", ".claude/skills", "server", "context", "rag_core", "utils", "scripts", "tools", "tests", "cli.py"]
SELF = Path(__file__).name

# pattern_id -> (regex, 说明)
PATTERNS = {
    "agentbase_import": (r"from agentscope\.agent import.*AgentBase|import AgentBase\b", "2.x 已删除 AgentBase，改用 agents.base.SkillAgentBase"),
    "agentscope_init": (r"agentscope\.init\(", "agentscope.init 已删除，用 utils.as_compat.setup / agentscope.setup_logger"),
    "json_loads_content": (r"json\.loads\s*\([^)]*\.content", "content 是块列表，用 utils.as_compat.msg_json"),
    "str_of_content": (r"str\s*\([^()]*\.content\s*\)|str\s*\(content\)", "禁止 str(content)，用 utils.as_compat.msg_text"),
    "content_slice": (r"\.content\s*\[", "禁止对 content 切片（2.x 是块列表），用 msg_text"),
    "len_of_content": (r"len\s*\([^)]*\.content\s*\)", "len(content) 在 2.x 是块数，用 msg_text"),
    "direct_msg_call": (r"(?<![_\w])Msg\s*\(", "业务代码禁止直接构造 Msg，用 utils.as_compat.mk_msg / 工厂函数"),
    "dict_model_call": (r"\.model\s*\(\s*\[\s*\{|\bmodel\s*\(\s*\[\s*\{", "模型调用禁止传 dict 列表，用 utils.as_compat.as_messages"),
    "direct_model_ctor": (r"OpenAIChatModel\s*\(", "模型构造统一走 utils.as_compat.build_chat_model（1.x/2.x 签名不同）"),
}


def iter_py_files():
    seen = set()
    for item in SCAN_FILES:
        p = ROOT / item
        if p.is_file():
            yield p
            continue
        if not p.is_dir():
            continue
        for f in sorted(p.rglob("*.py")):
            rel = f.relative_to(ROOT).as_posix()
            if SKIP_DIR.search("/" + rel):
                continue
            if f.name in ("as_compat.py", SELF):
                continue
            if rel in seen:
                continue
            seen.add(rel)
            yield f


def scan():
    violations = []
    for f in iter_py_files():
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = f.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for pid, (pat, _doc) in PATTERNS.items():
                if re.search(pat, line):
                    violations.append(f"{rel}:{pid}")
                    break  # 同文件同模式只记一条，避免行号漂移造成噪声
    return violations


def main(argv):
    mode = "--update" if "--update" in argv else ("--prune" if "--prune" in argv else "check")
    violations = scan()
    allow = []
    if ALLOWLIST.exists():
        allow = json.loads(ALLOWLIST.read_text(encoding="utf-8"))

    if mode == "--update":
        ALLOWLIST.write_text(json.dumps(violations, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[gate] allowlist updated: {len(violations)} entries")
        return 0

    unknown = [v for v in violations if v not in allow]
    if mode == "--prune":
        fixed = [a for a in allow if a not in set(violations)]
        allow = [a for a in allow if a in set(violations)]
        ALLOWLIST.write_text(json.dumps(allow, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[gate] pruned {len(fixed)} fixed entries; {len(allow)} remain")
        return 0

    print(f"[gate] violations={len(violations)} allowlist={len(allow)} unknown={len(unknown)}")
    for v in unknown[:40]:
        print("  MISSING-ALLOWLIST:", v)
    if unknown:
        print("  提示：路径:模式 粒度；修复后运行 --prune 收缩白名单")
    if unknown:
        print("[gate] FAIL - 新违规必须先修复或加入白名单")
        return 1
    print("[gate] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
