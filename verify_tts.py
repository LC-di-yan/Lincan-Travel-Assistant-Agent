"""验证 mimo-v2.5-tts 是否可用（从 .env 读取密钥，脚本中不保存密钥）"""
import os
import base64
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("ALIGO_API_KEY", "").strip()
BASE_URL = os.environ.get("ALIGO_BASE_URL", "").strip()
MODEL_NAME = os.environ.get("ALIGO_MODEL_NAME", "mimo-v2-pro").strip()


def check_env():
    errors = []
    if not API_KEY:
        errors.append("ALIGO_API_KEY 未设置，请在 .env 文件中配置")
    if not BASE_URL:
        errors.append("ALIGO_BASE_URL 未设置，请在 .env 文件中配置")
    if errors:
        print("[错误] 环境变量检查失败：")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    # 安全打印：只显示前 8 位
    masked = API_KEY[:8] + "..." if len(API_KEY) > 8 else "..."
    print(f"[配置] BASE_URL: {BASE_URL}")
    print(f"[配置] MODEL_NAME: {MODEL_NAME}")
    print(f"[配置] API_KEY: {masked}")


def test_chat():
    """先验证基础 chat 接口通不通"""
    try:
        from openai import OpenAI
    except ImportError:
        print("[错误] 缺少 openai 包，请安装：pip install openai")
        sys.exit(1)

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    print("\n[步骤 1/3] 测试基础 chat 接口 ...")
    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": "你好"}],
            max_tokens=20,
        )
        content = resp.choices[0].message.content
        print(f"[成功] chat 接口正常，返回: {content[:30]}...")
        return True
    except Exception as e:
        print(f"[失败] chat 接口测试失败: {e}")
        return False


def test_tts():
    """测试 mimo-v2.5-tts 流式接口"""
    from openai import OpenAI

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    print("\n[步骤 2/3] 测试 TTS 接口 (model=mimo-v2.5-tts, voice=冰糖) ...")

    try:
        stream = client.chat.completions.create(
            model="mimo-v2.5-tts",
            messages=[
                {"role": "user", "content": "用自然亲切的语气朗读"},
                {"role": "assistant", "content": "欢迎使用 Aligo 智能旅行助手。"},
            ],
            audio={"format": "pcm16", "voice": "冰糖"},
            stream=True,
        )

        chunk_count = 0
        total_bytes = 0
        first_audio_received = False
        audio_attrs = set()

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            audio = getattr(delta, "audio", None)
            if audio:
                if not first_audio_received:
                    print(f"[成功] 收到首个音频 chunk，audio 字段类型: {type(audio)}")
                    if isinstance(audio, dict):
                        audio_attrs = set(audio.keys())
                        print(f"[成功] audio 字段包含 keys: {audio_attrs}")
                    first_audio_received = True

                if isinstance(audio, dict) and "data" in audio:
                    pcm_data = base64.b64decode(audio["data"])
                    total_bytes += len(pcm_data)
                chunk_count += 1

        if first_audio_received:
            print(f"[成功] TTS 流式接口可用，共 {chunk_count} 个 chunk，音频数据约 {total_bytes} bytes")
            return True, audio_attrs
        else:
            print("[失败] TTS 接口没有返回任何音频数据（chunk.choices[0].delta.audio 为空）")
            return False, set()

    except Exception as e:
        print(f"[失败] TTS 接口调用失败: {type(e).__name__}: {e}")
        return False, set()


def test_tts_models():
    """测试文档中提到的其它 TTS 模型是否可调用"""
    from openai import OpenAI

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    models_to_try = ["mimo-v2.5-tts", "mimo-v2.5-tts-voicedesign", "mimo-v2.5-tts-voiceclone"]
    print("\n[步骤 3/3] 探测可用 TTS 模型 ...")
    for model in models_to_try:
        try:
            # 只请求一个 chunk，快速验证模型是否存在
            stream = client.chat.completions.create(
                model=model,
                messages=[{"role": "assistant", "content": "测试。"}],
                audio={"format": "pcm16", "voice": "冰糖"},
                stream=True,
            )
            for chunk in stream:
                delta = getattr(chunk.choices[0], "delta", None)
                if delta and getattr(delta, "audio", None):
                    print(f"  [可用] {model}")
                    break
            else:
                print(f"  [无数据] {model}（接口未报错，但未返回音频）")
        except Exception as e:
            err = str(e)
            if "model" in err.lower() or "not found" in err.lower() or "does not exist" in err.lower():
                print(f"  [不可用] {model}: 模型不存在或无权访问")
            else:
                print(f"  [异常] {model}: {err[:80]}")


if __name__ == "__main__":
    check_env()
    chat_ok = test_chat()
    if not chat_ok:
        print("\n[结论] 基础 chat 接口不通，请检查 ALIGO_API_KEY 和 ALIGO_BASE_URL")
        sys.exit(1)

    tts_ok, attrs = test_tts()
    test_tts_models()

    print("\n" + "=" * 60)
    if tts_ok:
        print("[结论] mimo-v2.5-tts 在当前配置下可用，语音输出方案可行。")
        print(f"[提示] 实际开发中请确认 audio 字段结构，当前 keys: {attrs}")
    else:
        print("[结论] mimo-v2.5-tts 在当前配置下不可用，语音输出方案需要先解决供应商/模型问题。")
    print("=" * 60)
