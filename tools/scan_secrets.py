"""上传前的密钥/敏感信息扫描（可作为 CI 门禁）。

只报告「文件:行号 + 命中类型 + 脱敏值」，**从不打印明文**。

设计要点
--------
1. **默认只扫 git 已跟踪文件**：密钥只有进了版本库才算泄漏；未跟踪的本地
   调试产物不该阻塞提交。用 `--all` 可扫工作树（仍尊重 .gitignore）。
2. **排除任何虚拟环境/构建产物**：旧版只排 `.venv`，漏掉 `.venv-as1/as2`，
   导致把 site-packages 里上千处 `password=*** 当成命中。
3. **棘轮基线**：已知安全项（测试假 key 等）登记在
   `data/secret_scan_allowlist.json`，只有**新增**命中才返回退出码 1。
   与 `tools/check_as2_gate.py` 同一套 --update / --prune 约定。
4. **测试假 key 自动识别**：tests/ 下明显的占位串不再需要人工登记。

用法
----
    python tools/scan_secrets.py              # 门禁：新命中 → exit 1
    python tools/scan_secrets.py --update     # 把当前命中写入基线
    python tools/scan_secrets.py --prune      # 清理已修复的基线条目
    python tools/scan_secrets.py --all        # 连未跟踪文件一起扫（尊重 gitignore）
    python tools/scan_secrets.py --json       # 机器可读输出
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "data" / "secret_scan_allowlist.json"

# 目录名匹配：任何 .venv*/venv* 都排除（旧版漏了 .venv-as1 / .venv-as2）
EXCLUDE_DIR_RE = re.compile(
    r"^(?:\.venv.*|venv.*|node_modules|__pycache__|\.git|\.pytest_cache|\.mypy_cache"
    r"|\.ruff_cache|dist|build|logs|coverage|htmlcov|\.tox|egg-info)$",
    re.I,
)

PATTERNS = [
    ("openai/relay key", re.compile(r"\b(sk-[A-Za-z0-9._\-]{12,})")),
    ("typesafe key", re.compile(r"\b(sk_tr_[A-Za-z0-9]{20,})")),
    ("aiping key", re.compile(r"\b(QC-[0-9a-f]{16,})")),
    ("github token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,})")),
    ("aws access key", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
    ("private key block", re.compile(r"(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")),
    ("amap key", re.compile(r"\b([0-9a-f]{32})\b")),
    ("bearer", re.compile(r"Bearer\s+([A-Za-z0-9._\-]{20,})")),
    ("password", re.compile(r"(?:password|passwd|secret)\s*[=:]\s*[\"']([^\"'\s,]{8,})[\"']", re.I)),
]

TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".json", ".md", ".ps1", ".sh", ".yml", ".yaml",
            ".env", ".example", ".txt", ".cjs", ".mjs", ".ini", ".toml", ".cfg", ".html", ".css"}

PLACEHOLDER_WORDS = ("your", "xxx", "example", "placeholder", "here", "changeme",
                     "<key", "redacted", "masked", "todo", "replace")
# 行内豁免（bandit 惯例）：用于「刻意构造得像真 key」的测试样本。
# 必须写明理由，例如：  # nosec 合成样本，用于验证检出能力
# 比登记基线更好：豁免与代码同处一行，评审时直接可见。
NOSEC_RE = re.compile(r"#\s*nosec\b|<!--\s*nosec\b", re.I)
# tests/ 下的合成串特征：全小写单词 + 少量顺序数字/字母，无真实 key 的随机大小写混合
FIXTURE_HINTS = ("test", "dummy", "fake", "mock", "sample", "abcd", "1234", "7890",
                 "mnop", "dict", "key-", "notreal", "invalid")


def mask(v: str) -> str:
    return v[:6] + "…" + v[-4:] if len(v) > 12 else "***"


def _is_placeholder(val: str) -> bool:
    low = val.lower()
    return any(k in low for k in PLACEHOLDER_WORDS)


def _is_test_fixture(val: str, rel: str) -> bool:
    """tests/ 下明显的假 key 不算泄漏（真实 key 不会含 test/dummy/abcd 这类词）。"""
    norm = rel.replace("\\", "/").lower()
    if not (norm.startswith("tests/") or "/tests/" in norm or norm.startswith("test_")):
        return False
    low = val.lower()
    return any(h in low for h in FIXTURE_HINTS)


def _git_files(args: list[str]) -> list[str] | None:
    """git 输出按 UTF-8 解码：Windows 默认 GBK 会在中文文件名上炸。"""
    try:
        r = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=ROOT, capture_output=True, check=True,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    out = r.stdout or ""
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def iter_files(scan_all: bool, staged: bool) -> list[Path]:
    if staged:
        listed = _git_files(["diff", "--cached", "--name-only", "--diff-filter=ACM"])
    elif not scan_all:
        listed = _git_files(["ls-files"])
    else:
        listed = None  # 走工作树遍历

    found: list[Path] = []
    if listed is not None:
        for rel in listed:
            p = ROOT / rel
            if p.is_file() and not _excluded(rel) and _wanted(p):
                found.append(p)
        return found

    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if not EXCLUDE_DIR_RE.match(d)]
        rel_dir = os.path.relpath(dirpath, ROOT)
        if rel_dir != "." and _excluded(rel_dir):
            dirnames[:] = []
            continue
        for fn in filenames:
            p = Path(dirpath) / fn
            rel = os.path.relpath(p, ROOT)
            if _excluded(rel) or not _wanted(p):
                continue
            if _git_ignored(rel):
                continue
            found.append(p)
    return found


def _excluded(rel: str) -> bool:
    parts = re.split(r"[\\/]", rel.replace("\\", "/"))
    return any(EXCLUDE_DIR_RE.match(part) for part in parts if part)


def _wanted(p: Path) -> bool:
    if p.suffix.lower() not in TEXT_EXT and not p.name.startswith(".env"):
        return False
    try:
        return p.stat().st_size <= 2_000_000
    except OSError:
        return False


def _git_ignored(rel: str) -> bool:
    r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT, capture_output=True)
    return r.returncode == 0


def scan(files: list[Path]) -> list[dict]:
    hits: list[dict] = []
    for p in files:
        rel = os.path.relpath(p, ROOT)
        try:
            text = io.open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if len(line) > 600 or NOSEC_RE.search(line):
                continue
            for label, pat in PATTERNS:
                for m in pat.finditer(line):
                    val = m.group(m.lastindex or 0)
                    if _is_placeholder(val) or _is_test_fixture(val, rel):
                        continue
                    if label == "amap key" and len(set(val)) < 6:
                        continue
                    hits.append({
                        "path": rel.replace("\\", "/"),
                        "line": lineno,
                        "label": label,
                        "masked": mask(val),
                    })
    return hits


def key_of(h: dict) -> str:
    """基线键：路径 + 类型 + 脱敏值（不含行号，避免上下移动造成噪音）。"""
    return f"{h['path']}:{h['label']}:{h['masked']}"


def load_allowlist() -> list[str]:
    if not ALLOWLIST.exists():
        return []
    try:
        return json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def save_allowlist(keys: list[str]) -> None:
    ALLOWLIST.parent.mkdir(parents=True, exist_ok=True)
    ALLOWLIST.write_text(json.dumps(sorted(set(keys)), ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="密钥扫描门禁（不打印明文）")
    ap.add_argument("--all", action="store_true", help="扫工作树（尊重 .gitignore），默认只扫已跟踪文件")
    ap.add_argument("--staged", action="store_true", help="只扫已暂存文件（pre-commit 用）")
    ap.add_argument("--update", action="store_true", help="把当前命中写入基线")
    ap.add_argument("--prune", action="store_true", help="清理基线里已修复的条目")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args(argv)

    files = iter_files(args.all, args.staged)
    hits = scan(files)
    allow = load_allowlist()
    keys = [key_of(h) for h in hits]

    if args.update:
        save_allowlist(keys)
        print(f"[secrets] 基线已更新：{len(set(keys))} 条（扫描 {len(files)} 个文件）")
        return 0

    if args.prune:
        current = set(keys)
        stale = [a for a in allow if a not in current]
        save_allowlist([a for a in allow if a in current])
        print(f"[secrets] 清理 {len(stale)} 条已修复项；剩余 {len(set(allow) & current)} 条")
        return 0

    allow_set = set(allow)
    new_hits = [h for h in hits if key_of(h) not in allow_set]

    if args.json:
        print(json.dumps({
            "scanned": len(files), "hits": len(hits),
            "baselined": len(hits) - len(new_hits), "new": new_hits,
        }, ensure_ascii=False, indent=1))
        return 1 if new_hits else 0

    scope = "staged" if args.staged else ("working tree" if args.all else "tracked")
    print(f"[secrets] scope={scope} files={len(files)} hits={len(hits)} "
          f"baselined={len(hits) - len(new_hits)} new={len(new_hits)}")
    for h in new_hits[:40]:
        print(f"  NEW {h['path']}:{h['line']} [{h['label']}] {h['masked']}")
    if new_hits:
        print("[secrets] FAIL — 新增疑似密钥。确认安全后运行 --update 登记基线，否则请移除。")
        return 1
    print("[secrets] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
