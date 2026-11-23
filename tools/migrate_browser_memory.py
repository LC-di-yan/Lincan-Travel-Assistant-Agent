"""停服后由本机管理员复制旧 JSON 记忆到新浏览器身份；不删除源文件。"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils.json_store import atomic_write_json, file_transaction, validate_user_id


def migrate_browser_memory(source_user: str, target_user: str, storage_path) -> Path:
    validate_user_id(source_user)
    validate_user_id(target_user)
    if not re.fullmatch(r"user_[0-9a-f]{32}", target_user):
        raise ValueError("目标必须是新浏览器会话返回的用户标识")
    root = Path(storage_path).resolve()
    source = (root / f"{source_user}.json").resolve()
    target = (root / f"{target_user}.json").resolve()
    if not source.is_relative_to(root) or not target.is_relative_to(root):
        raise ValueError("记忆文件必须位于指定目录中")
    if source == target:
        raise ValueError("源用户与目标用户必须不同")
    with file_transaction(source), file_transaction(target):
        if target.exists():
            raise FileExistsError("目标用户已有数据，已拒绝覆盖；请先备份并人工合并")
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("源记忆格式无效")
        data = deepcopy(data)
        data["user_id"] = target_user
        atomic_write_json(target, data)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-user", required=True, help="旧用户标识，例如 default_user")
    parser.add_argument("--target-user", required=True, help="新浏览器返回的用户标识")
    parser.add_argument("--memory-dir", type=Path, default=ROOT / "data" / "memory", help="JSON 记忆目录")
    args = parser.parse_args()
    try:
        target = migrate_browser_memory(args.source_user, args.target_user, args.memory_dir)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"迁移未执行：{exc}\n")
    print(f"记忆已复制到 {target}，原始文件完整保留。")


if __name__ == "__main__":
    main()
