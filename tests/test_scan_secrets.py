# -*- coding: utf-8 -*-
"""密钥扫描器能力测试。

关键：扫描器「返回 0」必须是因为真的没有密钥，而不是因为它坏了。
本测试用合成样本正向验证检出能力，反向验证误报抑制与基线棘轮。
所有样本均为构造值，不是任何真实凭据。
"""
from __future__ import annotations

import sys
from pathlib import Path

project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tools.scan_secrets import (  # noqa: E402
    EXCLUDE_DIR_RE,
    _is_placeholder,
    _is_test_fixture,
    key_of,
    mask,
    scan,
)

# 合成样本（构造值，非真实凭据）
FAKE_OPENAI = "sk-" + "A1b2C3d4E5f6G7h8I9j0KlMnO"
FAKE_TYPESAFE = "sk_tr_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7"
FAKE_GITHUB = "ghp_" + "A1b2C3d4E5f6G7h8I9j0KlMnO"
FAKE_AWS = "AKIA" + "Z9Y8X7W6V5U4T3S2"


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_detects_openai_style_key(tmp_path):
    p = _write(tmp_path, "cfg.py", f'API_KEY = "{FAKE_OPENAI}"\n')
    hits = scan([p])
    assert any(h["label"] == "openai/relay key" for h in hits), hits


def test_detects_typesafe_key(tmp_path):
    p = _write(tmp_path, "cfg.py", f'KEY = "{FAKE_TYPESAFE}"\n')
    assert any(h["label"] == "typesafe key" for h in scan([p]))


def test_detects_github_token(tmp_path):
    p = _write(tmp_path, "cfg.py", f'TOKEN = "{FAKE_GITHUB}"\n')
    assert any(h["label"] == "github token" for h in scan([p]))


def test_detects_aws_access_key(tmp_path):
    p = _write(tmp_path, "cfg.py", f'AWS = "{FAKE_AWS}"\n')
    assert any(h["label"] == "aws access key" for h in scan([p]))


def test_detects_private_key_block(tmp_path):
    p = _write(tmp_path, "id_rsa.txt", "-----BEGIN RSA PRIVATE KEY-----\n")
    assert any(h["label"] == "private key block" for h in scan([p]))


def test_detects_bearer_token(tmp_path):
    p = _write(tmp_path, "req.md", "Authorization: Bearer A1b2C3d4E5f6G7h8I9j0KlMnO\n")  # nosec 合成样本，验证 bearer 检出
    assert any(h["label"] == "bearer" for h in scan([p]))


def test_never_returns_plaintext(tmp_path):
    p = _write(tmp_path, "cfg.py", f'KEY = "{FAKE_TYPESAFE}"\n')
    hits = scan([p])
    assert hits
    for h in hits:
        assert FAKE_TYPESAFE not in h["masked"], "脱敏值不得包含完整明文"
        assert "…" in h["masked"] or h["masked"] == "***"


def test_placeholders_are_ignored(tmp_path):
    p = _write(tmp_path, "doc.md", 'key = "sk-your-api-key-here-xxxx"\n')
    assert scan([p]) == []
    assert _is_placeholder("sk-your-key")
    assert _is_placeholder("<key-prefix>")


def test_test_fixtures_are_ignored():
    assert _is_test_fixture("sk-test-key-1234abcd", "tests/test_decision_engine.py")
    assert _is_test_fixture("sk-dummy-7890", "tests\\test_x.py")
    # 同样的串出现在生产代码里必须仍然报出
    assert not _is_test_fixture("sk-test-key-1234abcd", "utils/decision_engine.py")


def test_virtualenvs_and_build_dirs_excluded():
    for d in [".venv", ".venv-as1", ".venv-as2", "venv312", "node_modules",
              "__pycache__", ".git", "dist", "build", ".pytest_cache"]:
        assert EXCLUDE_DIR_RE.match(d), d
    assert not EXCLUDE_DIR_RE.match("utils")
    assert not EXCLUDE_DIR_RE.match("agents")


def test_baseline_key_is_line_independent(tmp_path):
    a = _write(tmp_path, "a.py", f'\n\nKEY = "{FAKE_OPENAI}"\n')
    hits_a = scan([a])
    b = _write(tmp_path, "b.py", f'KEY = "{FAKE_OPENAI}"\n')
    hits_b = scan([b])
    # 行号不同不影响基线键的「类型+脱敏值」部分
    assert hits_a and hits_b
    assert hits_a[0]["line"] != hits_b[0]["line"]
    assert key_of(hits_a[0]).split(":", 1)[1] == key_of(hits_b[0]).split(":", 1)[1]


def test_mask_shapes():
    assert mask("short") == "***"
    m = mask(FAKE_OPENAI)
    m2 = mask(FAKE_TYPESAFE)
    assert m.startswith("sk-A1b") and m.endswith("MnO")
    assert "…" in m and "…" in m2

def test_nosec_inline_suppression(tmp_path):
    """行内豁免：刻意构造的样本可标注 nosec，但必须有该标记才生效。"""
    secret_line = f'KEY = "{FAKE_OPENAI}"'
    plain = _write(tmp_path, "a.py", secret_line + "\n")
    assert scan([plain]), "无标记时必须报出"

    marked = _write(tmp_path, "b.py", secret_line + "  # nosec 合成样本\n")
    assert scan([marked]) == [], "带 nosec 标记时应豁免"

    html = _write(tmp_path, "c.md", f"token: {FAKE_GITHUB} <!-- nosec 文档示例 -->\n")
    assert scan([html]) == [], "Markdown 注释形式也应生效"
