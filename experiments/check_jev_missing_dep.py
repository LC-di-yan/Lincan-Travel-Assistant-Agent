import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
# 模拟 typesafe_sdk 缺失：验证 jev 后端是否会拖垮主链路
import builtins
real_import = builtins.__import__
def blocked(name, *a, **k):
    if name.startswith('typesafe_sdk'):
        raise ImportError('No module named typesafe_sdk (simulated)')
    return real_import(name, *a, **k)
builtins.__import__ = blocked
from utils.decision_engine import DecisionEngine
eng = DecisionEngine(api_key='sk_tr_dummy', mode='assist', backend='jev')
async def main():
    try:
        d = await eng.route('帮我订杭州的酒店')
        print('route returned:', 'None (degraded OK)' if d is None else type(d).__name__)
        print('last_error:', eng.last_error[:100])
    except Exception as e:
        print('UNCAUGHT -> would break main chain:', type(e).__name__, str(e)[:120])
asyncio.run(main())