#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
存储性能对比测试：JSON 文件 vs PostgreSQL

使用方法:
  1. 纯 JSON 测试（无需 PG）:
     python tests/benchmark_storage.py

  2. 对比测试（需要 PG）:
     set ALIGO_DATABASE_URL=postgresql://<user>:<password>@localhost:5432/<db>
     python tests/benchmark_storage.py

  3. 仅 PG 测试:
     set ALIGO_DATABASE_URL=postgresql://<user>:<password>@localhost:5432/<db>
     set BENCH_JSON=0
     python tests/benchmark_storage.py
"""
import sys
import os
import asyncio
import time
import statistics
import shutil
import tempfile
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ──────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────
ROUNDS = 100          # 每项测试重复次数
WARMUP = 10           # 预热次数（不计入统计）
BENCH_JSON = os.environ.get("BENCH_JSON", "1") != "0"
BENCH_PG = bool(os.environ.get("ALIGO_DATABASE_URL", ""))

if not BENCH_JSON and not BENCH_PG:
    print("Nothing to benchmark. Set BENCH_JSON=1 or ALIGO_DATABASE_URL.")
    sys.exit(0)

# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────
def fmt_us(us: float) -> str:
    if us < 1000:
        return f"{us:.0f}µs"
    return f"{us/1000:.1f}ms"

def fmt_row(label: str, json_us: float = None, pg_us: float = None, winner: str = "") -> str:
    parts = [f"  {label:<32}"]
    if json_us is not None:
        parts.append(f"  JSON  {fmt_us(json_us):>10}")
    if pg_us is not None:
        parts.append(f"  PG    {fmt_us(pg_us):>10}")
    if json_us and pg_us:
        ratio = pg_us / json_us if json_us > 0 else 0
        if ratio < 1:
            parts.append(f"  PG 快 {1/ratio:.1f}x")
        else:
            parts.append(f"  JSON 快 {ratio:.1f}x")
    return "".join(parts)

def bench_sync(fn, rounds=ROUNDS, warmup=WARMUP) -> float:
    """同步函数基准测试，返回平均微秒数"""
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1_000_000)
    return statistics.median(times)

async def bench_async(fn, rounds=ROUNDS, warmup=WARMUP) -> float:
    """异步函数基准测试，返回平均微秒数"""
    for _ in range(warmup):
        await fn()
    times = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        await fn()
        times.append((time.perf_counter() - t0) * 1_000_000)
    return statistics.median(times)

# ──────────────────────────────────────────────
# 测试数据
# ──────────────────────────────────────────────
SAMPLE_PREFS = [
    ("home_location", "北京"),
    ("hotel_brands", ["汉庭", "如家", "全季"]),
    ("airlines", ["国航", "东航"]),
    ("seat_preference", "靠窗"),
    ("budget_level", "中等"),
]

SAMPLE_EXPENSE = {
    "category": "餐饮",
    "amount": 88.5,
    "currency": "CNY",
    "description": "午餐 - 牛肉面",
    "date": "2026-07-28",
}

SAMPLE_TRIP = {
    "origin": "上海",
    "destination": "北京",
    "start_date": "2026-08-01",
    "end_date": "2026-08-03",
    "purpose": "出差",
}

# ──────────────────────────────────────────────
# JSON 测试
# ──────────────────────────────────────────────
def run_json_benchmark():
    from context.long_term_memory import LongTermMemory

    tmpdir = tempfile.mkdtemp(prefix="aligo_bench_json_")
    try:
        mem = LongTermMemory("bench_user", storage_path=tmpdir)

        # --- 写入偏好 ---
        def write_pref():
            for pt, pv in SAMPLE_PREFS:
                mem.save_preference(pt, pv)

        # --- 读取全部偏好 ---
        def read_prefs():
            mem.get_preference()

        # --- 读取单个偏好 ---
        def read_single_pref():
            mem.get_preference("hotel_brands")

        # --- 追加酒店品牌 ---
        counter = [0]
        def add_hotel():
            counter[0] += 1
            mem.add_hotel_brand(f"品牌{counter[0]}")

        # --- 写入聊天消息 ---
        def write_chat():
            mem.add_chat_message("user", "我要从上海去北京出差", "sess_01")

        # --- 读取聊天历史 ---
        def read_chat():
            mem.get_chat_history(limit=20)

        # --- 写入行程 ---
        def write_trip():
            mem.save_trip_history(SAMPLE_TRIP)

        # --- 读取行程 ---
        def read_trips():
            mem.get_trip_history(limit=10)

        # --- 写入费用 ---
        def write_expense():
            mem.add_expense(SAMPLE_EXPENSE)

        # --- 读取费用 ---
        def read_expenses():
            mem.get_expenses(limit=20)

        # --- 删除费用 ---
        def delete_expense():
            if mem.get_expenses():
                mem.delete_expense(0)

        # --- 获取统计 ---
        def get_stats():
            mem.get_statistics()

        # --- 常去目的地 ---
        def get_freq():
            mem.get_frequent_destinations(5)

        results = {}
        results["save_preference"]     = bench_sync(write_pref)
        results["get_preference(all)"] = bench_sync(read_prefs)
        results["get_preference(one)"] = bench_sync(read_single_pref)
        results["add_hotel_brand"]     = bench_sync(add_hotel)
        results["add_chat_message"]    = bench_sync(write_chat)
        results["get_chat_history"]    = bench_sync(read_chat)
        results["save_trip_history"]   = bench_sync(write_trip)
        results["get_trip_history"]    = bench_sync(read_trips)
        results["add_expense"]         = bench_sync(write_expense)
        results["get_expenses"]        = bench_sync(read_expenses)
        results["delete_expense"]      = bench_sync(delete_expense)
        results["get_statistics"]      = bench_sync(get_stats)
        results["get_freq_dest"]       = bench_sync(get_freq)

        return results
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ──────────────────────────────────────────────
# PG 测试
# ──────────────────────────────────────────────
async def run_pg_benchmark():
    from db.connection import get_pool, close_pool
    from context.long_term_memory import PostgresLongTermMemory

    pool = await get_pool()
    if pool is None:
        return None

    # 建表
    schema_path = project_root / "db" / "schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        await pool.execute(f.read())

    mem = PostgresLongTermMemory("bench_user", pool)

    # 预热：确保用户存在
    await mem._ensure_user()

    # --- 写入偏好 ---
    async def write_pref():
        for pt, pv in SAMPLE_PREFS:
            await mem.save_preference(pt, pv)

    # --- 读取全部偏好 ---
    async def read_prefs():
        await mem.get_preference()

    # --- 读取单个偏好 ---
    async def read_single_pref():
        await mem.get_preference("hotel_brands")

    # --- 追加酒店品牌 ---
    counter = [0]
    async def add_hotel():
        counter[0] += 1
        await mem.add_hotel_brand(f"品牌{counter[0]}")

    # --- 写入聊天消息 ---
    async def write_chat():
        await mem.add_chat_message("user", "我要从上海去北京出差", "sess_01")

    # --- 读取聊天历史 ---
    async def read_chat():
        await mem.get_chat_history(limit=20)

    # --- 写入行程 ---
    async def write_trip():
        await mem.save_trip_history(SAMPLE_TRIP)

    # --- 读取行程 ---
    async def read_trips():
        await mem.get_trip_history(limit=10)

    # --- 写入费用 ---
    async def write_expense():
        await mem.add_expense(SAMPLE_EXPENSE)

    # --- 读取费用 ---
    async def read_expenses():
        await mem.get_expenses(limit=20)

    # --- 删除费用 ---
    async def delete_expense():
        exps = await mem.get_expenses()
        if exps:
            await mem.delete_expense(0)

    # --- 获取统计 ---
    async def get_stats():
        await mem.get_statistics()

    # --- 常去目的地 ---
    async def get_freq():
        await mem.get_frequent_destinations(5)

    results = {}
    results["save_preference"]     = await bench_async(write_pref)
    results["get_preference(all)"] = await bench_async(read_prefs)
    results["get_preference(one)"] = await bench_async(read_single_pref)
    results["add_hotel_brand"]     = await bench_async(add_hotel)
    results["add_chat_message"]    = await bench_async(write_chat)
    results["get_chat_history"]    = await bench_async(read_chat)
    results["save_trip_history"]   = await bench_async(write_trip)
    results["get_trip_history"]    = await bench_async(read_trips)
    results["add_expense"]         = await bench_async(write_expense)
    results["get_expenses"]        = await bench_async(read_expenses)
    results["delete_expense"]      = await bench_async(delete_expense)
    results["get_statistics"]      = await bench_async(get_stats)
    results["get_freq_dest"]       = await bench_async(get_freq)

    # 清理测试数据
    await pool.execute("DELETE FROM users WHERE user_id='bench_user'")
    await close_pool()

    return results


# ──────────────────────────────────────────────
# 批量写入压力测试
# ──────────────────────────────────────────────
def run_json_batch_test(n: int = 500):
    from context.long_term_memory import LongTermMemory
    tmpdir = tempfile.mkdtemp(prefix="aligo_bench_batch_")
    try:
        mem = LongTermMemory("batch_user", storage_path=tmpdir)
        t0 = time.perf_counter()
        for i in range(n):
            mem.add_chat_message("user", f"消息内容第{i}条，测试批量写入性能", "sess_01")
        elapsed = (time.perf_counter() - t0) * 1000
        return elapsed
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

async def run_pg_batch_test(n: int = 500):
    from db.connection import get_pool, close_pool
    from context.long_term_memory import PostgresLongTermMemory
    pool = await get_pool()
    if pool is None:
        return None
    mem = PostgresLongTermMemory("batch_user", pool)
    await mem._ensure_user()
    t0 = time.perf_counter()
    for i in range(n):
        await mem.add_chat_message("user", f"消息内容第{i}条，测试批量写入性能", "sess_01")
    elapsed = (time.perf_counter() - t0) * 1000
    await pool.execute("DELETE FROM users WHERE user_id='batch_user'")
    await close_pool()
    return elapsed


# ──────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────
async def main():
    print("=" * 68)
    print("  Aligo 存储性能对比  —  JSON 文件 vs PostgreSQL")
    print(f"  每项测试: {ROUNDS} 轮 (取中位数), 预热 {WARMUP} 轮")
    print("=" * 68)

    json_results = None
    pg_results = None

    if BENCH_JSON:
        print("\n▶ JSON 文件模式测试中...")
        json_results = run_json_benchmark()
        print("  ✓ 完成")

    if BENCH_PG:
        print("\n▶ PostgreSQL 模式测试中...")
        pg_results = await run_pg_batch_test.__wrapped__() if hasattr(run_pg_batch_test, '__wrapped__') else None
        pg_results = await run_pg_benchmark()
        if pg_results is None:
            print("  ✗ 数据库连接失败，跳过 PG 测试")
        else:
            print("  ✓ 完成")

    # 打印对比表
    print("\n" + "=" * 68)
    print("  单次操作延迟对比 (中位数)")
    print("=" * 68)

    all_keys = []
    if json_results:
        all_keys = list(json_results.keys())
    elif pg_results:
        all_keys = list(pg_results.keys())

    for key in all_keys:
        j = json_results.get(key) if json_results else None
        p = pg_results.get(key) if pg_results else None
        print(fmt_row(key, j, p))

    # 批量写入测试
    print("\n" + "=" * 68)
    print(f"  批量写入 {500} 条聊天消息")
    print("=" * 68)

    if BENCH_JSON:
        json_batch = run_json_batch_test(500)
        print(f"  JSON  {fmt_us(json_batch * 1000):>10}")

    if BENCH_PG:
        pg_batch = await run_pg_batch_test(500)
        if pg_batch is not None:
            print(f"  PG    {fmt_us(pg_batch * 1000):>10}")
            if BENCH_JSON:
                ratio = json_batch / pg_batch if pg_batch > 0 else 0
                if ratio > 1:
                    print(f"  → PG 快 {ratio:.1f}x (批量连接复用)")
                else:
                    print(f"  → JSON 快 {1/ratio:.1f}x (无网络开销)")

    # 总结
    print("\n" + "=" * 68)
    print("  分析说明")
    print("=" * 68)
    print("""
  • JSON 读写 = 纯内存操作 + 文件序列化，单次极快
  • PG 读写   = 网络往返 + SQL 执行，单次有固定开销 (~0.5-2ms)
  • JSON 的代价：
    - 全量加载/写回，数据量越大越慢
    - 无并发安全，多进程写入会丢数据
    - 进程崩溃丢失未 flush 的数据
    - 无法水平扩展
  • PG 的优势：
    - 写入即持久化，崩溃不丢数据
    - 支持并发读写
    - 可水平扩展（多实例共享数据库）
    - 支持索引查询、聚合统计
    - 数据量增长不影响单次操作性能
  • 结论：单用户小数据量场景 JSON 更快；
    多用户/生产环境 PG 是唯一可靠选择
""")


if __name__ == "__main__":
    asyncio.run(main())
