import runpy
from pathlib import Path


def test_fallback_credentials_stay_in_their_original_slot(monkeypatch):
    monkeypatch.setenv("ALIGO_API_KEY", "primary-example")
    monkeypatch.setenv("ALIGO_FALLBACK_BASE_URLS", "base1, ,base3,base4")
    monkeypatch.setenv("ALIGO_FALLBACK_MODEL_NAMES", "model1,model2,model3,")
    monkeypatch.setenv("ALIGO_FALLBACK_API_KEYS", ",unused,key3,key4")
    channels = runpy.run_path(str(Path(__file__).resolve().parents[1] / "config.py"))["LLM_FALLBACKS"]
    assert [(c["base_url"], c["model_name"], c["api_key"]) for c in channels] == [
        ("base1", "model1", "primary-example"), ("base3", "model3", "key3"),
    ]
