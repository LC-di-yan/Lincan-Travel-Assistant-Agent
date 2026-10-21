"""一次性抓取系统界面截图（用于 README / 展示页）。

用法：
    .venv\\Scripts\\python.exe tools\\capture_screenshots.py
要求服务已在 http://127.0.0.1:3003 运行。
"""
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ALIGO_SHOT_BASE", "http://127.0.0.1:3003")
CHROME = os.environ.get("ALIGO_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
VIEWPORT = {"width": 1440, "height": 900}

# (文件名, 依次发送的消息)
SHOTS = [
    ("01-home", []),
    ("02-itinerary", ["明天从北京去上海出差3天，预算2000"]),
    ("03-hotel", ["上海有什么推荐酒店"]),
    ("04-weather", ["明天上海天气怎么样"]),
    ("05-train", ["查一下明天北京到上海的高铁"]),
    ("06-preference", ["我住酒店喜欢汉庭"]),
    ("07-expense-currency", ["今天打车花了80元", "100美元等于多少人民币"]),
]


def wait_done(page, timeout_ms: int = 180_000):
    """等「处理中」消失，说明这一轮回复结束。"""
    page.wait_for_function(
        "() => !document.body.innerText.includes('处理中')",
        timeout=timeout_ms,
    )


def send(page, text: str):
    box = page.get_by_role("textbox", name="输入消息")
    box.click()
    box.fill(text)
    page.get_by_role("button", name="发送消息").click()
    page.wait_for_timeout(600)
    wait_done(page)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, headless=True)
        for name, messages in SHOTS:
            ctx = browser.new_context(
                viewport=VIEWPORT, locale="zh-CN", timezone_id="Asia/Shanghai",
                color_scheme="light", device_scale_factor=1,
            )
            page = ctx.new_page()
            page.goto(BASE, wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(1200)
            for msg in messages:
                send(page, msg)
            page.wait_for_timeout(800)
            target = OUT / f"{name}.png"
            page.screenshot(path=str(target))
            print(f"[OK] {target.name}  {target.stat().st_size // 1024} KB")
            ctx.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
