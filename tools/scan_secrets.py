"""上传前的密钥/敏感信息扫描。

只报告「文件:行号 + 命中类型 + 脱敏值」，不打印明文。
"""
import io
import os
import re
import sys

ROOT = os.path.abspath(".")
EXCLUDE_DIRS = {".venv", "node_modules", "__pycache__", ".git", ".pytest_cache", "logs", "web\\dist", "dist"}
PATTERNS = [
    ("openai/relay key", re.compile(r"\b(sk-[A-Za-z0-9._\-]{12,})")),
    ("aiping key", re.compile(r"\b(QC-[0-9a-f]{16,})")),
    ("github token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,})")),
    ("amap key", re.compile(r"\b([0-9a-f]{32})\b")),
    ("bearer", re.compile(r"Bearer\s+([A-Za-z0-9._\-]{20,})")),
    ("password", re.compile(r"(password|passwd|secret)\s*[=:]\s*[\"']?([^\s\"',]{8,})", re.I)),
]
TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".json", ".md", ".ps1", ".sh", ".yml", ".yaml", ".env",
            ".example", ".txt", ".cjs", ".ini", ".html", ".css"}


def mask(v: str) -> str:
    return v[:6] + "…" + v[-4:] if len(v) > 12 else "***"


def main() -> int:
    hits = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = os.path.relpath(dirpath, ROOT)
        if rel_dir.split(os.sep)[0] in EXCLUDE_DIRS:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, ROOT)
            ext = os.path.splitext(fn)[1].lower()
            if ext not in TEXT_EXT and not fn.startswith(".env"):
                continue
            if os.path.getsize(path) > 2_000_000:
                continue
            try:
                text = io.open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if len(line) > 600:
                    continue
                for label, pat in PATTERNS:
                    for m in pat.finditer(line):
                        val = m.group(m.lastindex or 0)
                        # 排除明显的占位符/文档示例
                        if any(k in val.lower() for k in ("your", "xxx", "example", "placeholder", "here")):
                            continue
                        if label == "amap key" and len(set(val)) < 6:
                            continue
                        hits.append((rel, lineno, label, mask(val)))

    if not hits:
        print("未发现疑似密钥")
        return 0
    print(f"发现 {len(hits)} 处疑似密钥：\n")
    for rel, lineno, label, m in hits:
        print(f"{rel}:{lineno:<5} [{label}] {m}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
