"""Replay weather, place sources and an explicitly confirmed ledger operation."""
import argparse
import json
import re
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from playwright.sync_api import expect, sync_playwright

from run_flightdeck_visual_audit import assert_no_overflow, guarded_page, preview, save_recording


CONFIRM = "确认费用 " + "ab" * 12
EXPIRED = "确认费用 " + "cd" * 12
ITEMS = [
    {"description": "展会注册费", "category": "其他", "amount": 38.5, "currency": "USD", "date": "2026-11-21"},
    {"description": "会场出租车", "category": "交通", "amount": 64, "currency": "CNY", "date": "2026-11-21"},
]
WEATHER = {
    "query_type": "天气查询", "results": {
        "city": "上海", "presentation_version": 2,
        "requested_range": {"label": "今天和明天", "start_date": "2026-11-21", "end_date": "2026-11-22", "include_current": True},
        "current": {"temp": 16, "weather": "阴", "wind": "东北风 3 级", "humidity": 68,
                    "date_iso": "2026-11-21", "observed_at": "2026-11-21 10:30（北京时间）"},
        "forecast": [
            {"date": "今天 · 11/21", "date_iso": "2026-11-21", "weather": "多云", "night_weather": "阴", "temp_range": "12~18°C"},
            {"date": "明天 · 11/22", "date_iso": "2026-11-22", "weather": "小雨", "night_weather": "阴", "temp_range": "11~17°C"},
        ],
        "advice": [{"date_iso": "2026-11-22", "travel_tips": "前往会场请带伞。"}],
        "sources": [{"title": "高德天气", "url": "https://www.amap.com/"}],
    },
}


def place(number, name, address, coordinates="", cost=""):
    return {"id": str(number), "name": name, "address": address, "location": coordinates, "cost": cost,
            "rating": "4.6", "distance": "680"}


PLACES = {
    "results": {"city": "上海", "keyword": "会场周边简餐", "count": 6,
                "restaurants": [
                    place(1, "芳甸路简餐", "浦东新区芳甸路", "121.554,31.211", "48"),
                    place(2, "会展食集 · 本帮小馆", "浦东新区龙阳路会展中心南入口附近", "", "65"),
                    place(3, "浦东面馆", "浦东新区龙阳路"), place(4, "世纪大道便餐", "浦东新区世纪大道"),
                    place(5, "花木路饭堂", "浦东新区花木路"), place(6, "会展北门咖啡", "会展中心北门"),
                ], "sources": [{"title": "高德地图", "url": "https://www.amap.com/"}]},
}


def result(agent, node, data):
    return {"agent_name": agent, "node_id": node, "status": "success", "data": data}


def run_mode(browser, assets, output, mode, record):
    reduced = mode == "reduced"
    mobile = mode != "desktop"
    width, height = (320, 650) if reduced else (390, 844) if mobile else (1366, 900)
    received = Event()

    def stream(emit, body):
        command = body["message"]
        if command == CONFIRM:
            if not received.wait(20):
                return
            rows = [result("expense_tracking", "ledger", {"action": "record", "expenses": ITEMS,
                    "totals_by_currency": {"USD": 38.5, "CNY": 64}, "answer": "已一次性记录 2 笔费用。"})]
        elif command == EXPIRED:
            rows = [result("expense_tracking", "ledger", {"action": "error", "answer": "该确认已过期，未修改账本。请重新发起操作。"})]
        elif command.startswith("记"):
            token = EXPIRED if "过期" in command else CONFIRM
            rows = [result("expense_tracking", "ledger", {"action": "preview", "operation": "record", "expenses": ITEMS,
                    "confirmation_command": token, "answer": "两笔费用尚未写入。请核对用途、金额和币种。"})]
        else:
            rows = [result("information_query", "weather", WEATHER), result("restaurant_search", "places", PLACES)]
        emit("complete", {"status": "completed", "results": rows})

    with preview(assets, chat_script=stream) as (base, posted, _), TemporaryDirectory() as clips, ExitStack() as stack:
        context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=mobile, has_touch=mobile,
                                      device_scale_factor=1, color_scheme="dark" if mobile else "light",
                                      reduced_motion="reduce" if reduced else "no-preference",
                                      record_video_dir=clips if record else None,
                                      record_video_size={"width": width, "height": height} if record else None)
        stack.callback(context.close)
        errors = []
        page = guarded_page(context, errors)
        page.goto(base, wait_until="networkidle")

        def prompt(text):
            editor = page.get_by_role("textbox", name="输入消息")
            editor.fill(text)
            editor.press("Enter")

        def top(element):
            element.evaluate("e=>e.scrollIntoView({block:'start'})")

        def capture(element, label, delay=1100):
            top(element)
            if record:
                page.screenshot(path=output / f"{mode}-{label}.png")
                page.wait_for_timeout(delay)

        page.evaluate("""window.receiptStamps=0;document.addEventListener('animationstart',e=>{
            if(e.animationName==='fdr-expense-confirmed') window.receiptStamps++
        })""")
        prompt("看上海今天和明天的天气，再找会场附近的简餐。")
        weather = page.get_by_role("region", name="天气预报")
        expect(weather.get_by_role("region", name="观测实况")).to_contain_text("16°C")
        expect(weather.get_by_role("region", name="观测实况")).to_contain_text("观测时间：2026-11-21 10:30")
        forecast = weather.get_by_role("region", name="按日预报")
        expect(forecast).to_contain_text("11~17°C")
        expect(forecast).not_to_contain_text("观测时间")
        expect(weather.get_by_role("link", name="高德天气")).to_have_attribute("href", "https://www.amap.com/")
        capture(weather, "weather")

        places = page.get_by_role("region", name="餐饮清单")
        expect(places.get_by_role("link", name="高德地图", exact=True)).to_be_visible()
        expect(places.get_by_role("link", name="在高德打开：会展食集 · 本帮小馆")).to_have_count(0)
        expect(places.get_by_role("link", name="在高德打开：芳甸路简餐")).to_have_attribute(
            "href", re.compile(r"^https://uri\.amap\.com/marker\?"))
        top(places)
        if record:
            page.wait_for_timeout(550)
        places.get_by_role("button", name="查看全部 6 家").click()
        expect(places.get_by_text("会展北门咖啡")).to_be_visible()
        expect(places.get_by_role("link", name="高德地图", exact=True)).to_be_visible()
        capture(places, "places")
        assert len([p for p, _ in posted if p == "/api/chat"]) == 1
        assert page.evaluate("window.receiptStamps") == 0

        prompt("记一笔展会注册费 38.50 美元和一笔会场出租车 64 元。")
        receipts = page.get_by_role("region", name="费用回执")
        draft = receipts.first
        expect(draft).to_contain_text("待确认 · 账本未修改")
        expect(draft).to_contain_text("USD 38.50")
        expect(draft).to_contain_text("CNY 64.00")
        expect(draft).not_to_contain_text("账本已更新")
        activity = page.get_by_role("region", name="协作回执").last
        if activity.get_by_role("button", name="展开详情").count():
            activity.get_by_role("button", name="展开详情").click()
        expect(activity.get_by_role("list", name="任务状态")).to_contain_text("费用预览待确认")
        capture(draft, "pending")
        button = draft.get_by_role("button", name="确认这项费用操作")
        if reduced:
            button.focus()
            button.press("Enter")
        else:
            button.click()
        expect(draft).to_contain_text("已提交确认 · 等待账本回执")
        expect(draft.get_by_role("button", name="确认这项费用操作")).to_have_count(0)
        expect(receipts).to_have_count(1)
        assert page.evaluate("window.receiptStamps") == 0
        if record:
            top(draft)
            page.wait_for_timeout(650)
        received.set()
        done = receipts.last
        expect(done).to_contain_text("账本已更新")
        expect(done).to_contain_text("当前费用账本")
        expect(done).to_contain_text("已一次性记录 2 笔费用")
        expect(done).to_contain_text("USD 38.50")
        expect(done).to_contain_text("CNY 64.00")
        expect(draft).to_contain_text("预览快照 · 当时未写入")
        if not reduced:
            page.wait_for_function("window.receiptStamps === 1")
            if record:
                page.wait_for_function("document.getAnimations().every(a=>a.playState!=='running')")
        capture(done, "confirmed", 1400)
        assert page.evaluate("window.receiptStamps") == (0 if reduced else 1)
        assert CONFIRM not in page.locator("body").inner_text()
        assert [body["message"] for path, body in posted if path == "/api/chat"].count(CONFIRM) == 1
        assert_no_overflow(page)
        assert page.locator(".flight-result").evaluate_all("es=>es.every(e=>e.scrollWidth<=e.clientWidth+1)")

        if reduced:
            prompt("记一笔用于测试的过期确认。")
            receipts.last.get_by_role("button", name="确认这项费用操作").click()
            expect(receipts.last).to_contain_text("未收到成功回执")
            expect(receipts.last).not_to_contain_text("账本已更新")
            assert page.evaluate("window.receiptStamps") == 0
        assert not errors, errors
        clip = page.video
        context.close()
        return {"视口": [width, height], "手动确认请求": 1, "成功回执提示动效": 0 if reduced else 1,
                "录像": save_recording(clip, output / f"{mode}-operation") if clip else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chromium-exe", type=Path)
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=args.chromium_exe, args=["--disable-background-networking"])
        report = {mode: run_mode(browser, args.assets.resolve(), args.output, mode, args.record and mode != "reduced")
                  for mode in ("desktop", "mobile", "reduced")}
        report["浏览器"] = browser.version
        browser.close()
    (args.output / "replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("天气、地点与费用确认的桌面、手机和减动回放通过。")


if __name__ == "__main__":
    main()
