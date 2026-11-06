import inspect, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from dotenv import load_dotenv
load_dotenv()
from agentscope.classifier import JevClassifierModel
from agentscope.credential import TypeSafeCredential

m = JevClassifierModel(credential=TypeSafeCredential(api_key=os.environ["NEOHOUSE_API_KEY"], base_url="https://tokenrhythm.studio"), model="NeoHorse-Jev-4B", timeout=15)
print("client vars:", {k: type(v).__name__ for k, v in vars(m.client).items()})
cfg = getattr(m.client, "config", None) or getattr(m.client, "_config", None)
print("config:", cfg)
if cfg is not None:
    print("config vars:", vars(cfg))

from typesafe_sdk._core import transport
print("MIN_COMPRESSED_BODY_LENGTH:", transport.MIN_COMPRESSED_BODY_LENGTH)
src = inspect.getsource(transport)
i = src.find("MIN_COMPRESSED_BODY_LENGTH")
print(src[max(0,i-300):i+500])
