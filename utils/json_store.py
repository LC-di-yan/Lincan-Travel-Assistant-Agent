"""JSON 文件事务：跨线程、跨进程加锁，并以原子替换防止半写文件。"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from weakref import WeakValueDictionary

_locks = WeakValueDictionary()
_locks_guard = threading.Lock()


def validate_user_id(user_id: str) -> str:
    """用户标识只能是文件名，不能包含路径或 Windows 保留设备名。"""
    if not isinstance(user_id, str) or not re.fullmatch(r"[\w-]{1,64}", user_id):
        raise ValueError("用户标识只能包含 1 至 64 个字母、数字、下划线或短横线")
    if re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", user_id, re.I):
        raise ValueError("用户标识不能使用系统保留名称")
    return user_id


@contextmanager
def file_transaction(path):
    """锁文件与数据文件分离，原子替换数据时锁仍有效。"""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locks_guard:
        lock = _locks.setdefault(str(path), threading.RLock())
    with lock, open(str(path) + ".lock", "a+b") as handle:
        if os.name == "nt":
            import msvcrt
            # Windows 允许锁定文件末尾之外的区间；不要在取锁前写哨兵字节，
            # 否则另一个进程已经锁住首字节时会触发写入权限错误。
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write_json(path, data):
    """调用方负责事务锁；写入失败时保留上一份有效文件并向上报告。"""
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
