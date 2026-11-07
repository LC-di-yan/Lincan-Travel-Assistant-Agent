"""安装本地 git 钩子（.git/hooks 不进版本库，需每个克隆各自安装一次）。

    python tools/install_hooks.py          # 安装
    python tools/install_hooks.py --check  # 只检查是否已安装
    python tools/install_hooks.py --remove # 卸载

pre-commit 做两件事（合计约 1 秒）：
  1. `scan_secrets.py --staged` —— 只看本次暂存内容，拦住误提交的密钥；
  2. `check_as2_gate.py` —— 拦住 AgentScope 1.x 写法回潮。

由来：2026-11-06 一次 `git add -A` 把含明文 key 的调试文件提交并推送
（7f10cbf:data/cv.txt）。当时两个门禁脚本都已存在，但没有任何自动执行点。
"""
from __future__ import annotations

import argparse
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HOOK = """#!/bin/sh
# 由 tools/install_hooks.py 生成。跳过：git commit --no-verify
# 只扫暂存内容，避免被未跟踪的本地调试文件干扰。
PY=python
command -v python >/dev/null 2>&1 || PY=python3

echo "[pre-commit] 密钥扫描（暂存内容）"
"$PY" tools/scan_secrets.py --staged || {
    echo ""
    echo "提交被拦下：暂存内容里有疑似密钥。"
    echo "  - 真密钥：从暂存区移除（git restore --staged <file>）并清理文件"
    echo "  - 确认安全：python tools/scan_secrets.py --update 登记基线后重试"
    exit 1
}

echo "[pre-commit] AgentScope 1.x 写法门禁"
"$PY" tools/check_as2_gate.py || {
    echo ""
    echo "提交被拦下：出现 AgentScope 1.x 写法。请改用 utils/as_compat.py。"
    exit 1
}
"""


def hook_path() -> Path:
    r = subprocess.run(["git", "rev-parse", "--git-path", "hooks"],
                       cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace")
    rel = (r.stdout or ".git/hooks").strip()
    return (ROOT / rel / "pre-commit").resolve()


def main() -> int:
    ap = argparse.ArgumentParser(description="安装/检查/卸载 pre-commit 门禁钩子")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    p = hook_path()

    if args.check:
        ok = p.exists() and "install_hooks.py" in p.read_text(encoding="utf-8", errors="ignore")
        print(f"[hooks] {'已安装' if ok else '未安装'}：{p}")
        return 0 if ok else 1

    if args.remove:
        if p.exists() and "install_hooks.py" in p.read_text(encoding="utf-8", errors="ignore"):
            p.unlink()
            print(f"[hooks] 已卸载：{p}")
        else:
            print("[hooks] 未安装或由他人管理，未改动")
        return 0

    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and "install_hooks.py" not in p.read_text(encoding="utf-8", errors="ignore"):
        print(f"[hooks] 已存在非本工具的钩子，未覆盖：{p}")
        return 1
    # 换行必须是 LF，否则 Windows 下 sh 会报 bad interpreter
    p.write_bytes(HOOK.replace("\r\n", "\n").encode("utf-8"))
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"[hooks] 已安装：{p}")
    print("[hooks] 提交时会自动跑：密钥扫描（暂存）+ AgentScope 1.x 门禁")
    return 0


if __name__ == "__main__":
    sys.exit(main())
