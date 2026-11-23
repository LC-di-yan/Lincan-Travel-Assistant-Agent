"""JSON 记忆的并发、原子保存、读取副本及路径边界。"""
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import json
import multiprocessing

import pytest

from context.long_term_memory import LongTermMemory


def save_messages(path, count):
    memory = LongTermMemory("shared_user", path)
    for index in range(count):
        memory.add_chat_message("user", f"测试消息 {index}")


@pytest.mark.parametrize("user_id", ["../outside", "..\\outside", "C:\\outside", "/outside", "", "a" * 65, "CON", "nul", "a.b"])
def test_unsafe_user_names_are_rejected(tmp_path, user_id):
    with pytest.raises(ValueError):
        LongTermMemory(user_id, str(tmp_path))


def test_multiple_instances_threads_do_not_lose_updates(tmp_path):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: save_messages(str(tmp_path), 15), range(4)))
    memory = LongTermMemory("shared_user", str(tmp_path))
    assert len(memory.get_chat_history()) == 60
    assert memory.get_statistics()["total_messages"] == 60


def test_multiple_processes_do_not_lose_updates(tmp_path):
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(save_messages, str(tmp_path), 10) for _ in range(2)]
        for future in futures:
            future.result(timeout=60)
    assert len(LongTermMemory("shared_user", str(tmp_path)).get_chat_history()) == 20


def test_returned_collections_are_detached_from_storage(tmp_path):
    memory = LongTermMemory("copy_user", str(tmp_path))
    memory.add_expense({"amount": 50})
    expenses = memory.get_expenses()
    expenses[0]["amount"] = 999
    expenses.append({"amount": 999})
    assert len(memory.get_expenses()) == 1
    assert memory.get_expenses()[0]["amount"] == 50


def test_failed_atomic_replace_preserves_previous_file(tmp_path, monkeypatch):
    import utils.json_store as storage
    memory = LongTermMemory("atomic_user", str(tmp_path))
    memory.save_preference("home_location", "北京")
    original = (tmp_path / "atomic_user.json").read_bytes()
    def fail(*args):
        raise OSError("模拟磁盘写入失败")
    monkeypatch.setattr(storage.os, "replace", fail)
    with pytest.raises(OSError):
        memory.save_preference("home_location", "上海")
    assert (tmp_path / "atomic_user.json").read_bytes() == original
    assert memory.get_preference("home_location") == "北京"


def test_corrupted_file_is_not_silently_replaced(tmp_path):
    path = tmp_path / "broken_user.json"
    path.write_text('{"未完成":', encoding="utf-8")
    with pytest.raises(ValueError):
        LongTermMemory("broken_user", str(tmp_path))
    assert path.read_text(encoding="utf-8") == '{"未完成":'


def test_old_preferences_migrate_without_read_side_effects(tmp_path):
    path = tmp_path / "legacy_user.json"
    path.write_text(json.dumps({"preferences": {"home_location": "北京"}}), encoding="utf-8")
    original = path.read_bytes()
    memory = LongTermMemory("legacy_user", str(tmp_path))
    assert memory.get_preference("home_location") == "北京"
    assert path.read_bytes() == original
    memory.add_chat_message("user", "测试")
    assert LongTermMemory("legacy_user", str(tmp_path)).get_preference("home_location") == "北京"


def test_admin_memory_transfer_preserves_source_and_refuses_overwrite(tmp_path):
    from tools.migrate_browser_memory import migrate_browser_memory
    source = LongTermMemory("default_user", str(tmp_path))
    source.save_preference("home_location", "北京")
    original = (tmp_path / "default_user.json").read_bytes()
    user = "user_" + "a" * 32
    migrate_browser_memory("default_user", user, tmp_path)
    assert LongTermMemory(user, str(tmp_path)).get_preference("home_location") == "北京"
    assert (tmp_path / "default_user.json").read_bytes() == original
    with pytest.raises(FileExistsError):
        migrate_browser_memory("default_user", user, tmp_path)
    with pytest.raises(ValueError):
        migrate_browser_memory("default_user", "../outside", tmp_path)
