import inspect
from agentscope.credential import TypeSafeCredential
print("TypeSafeCredential:", inspect.signature(TypeSafeCredential.__init__))
print("fields:", list(TypeSafeCredential.model_fields) if hasattr(TypeSafeCredential, "model_fields") else "?")
print()
try:
    from agentscope.classifier._jev import _model as jm
    src = inspect.getsource(jm)
    import re
    for kw in ["base_url", "/v1/", "decision", "endpoint", "payload"]:
        hits = [l.strip()[:130] for l in src.splitlines() if kw in l.lower()]
        print(f"-- {kw}: {len(hits)}")
        for h in hits[:3]:
            print("   ", h)
except Exception as e:
    print("jev probe fail:", e)
