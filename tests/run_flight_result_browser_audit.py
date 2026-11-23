"""Replay the itinerary, rail and accommodation cards in an isolated browser."""
import argparse
import json
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from run_flightdeck_visual_audit import assert_no_overflow, guarded_page, preview, save_recording


def activity(time, name, location="", transport="", details=""):
    return {"time": time, "activity": name, "location": location, "transport": transport, "description": details}


ITINERARY = {
    "title": "上海 · 会展差旅三天", "duration": "3 天 2 晚", "route": "北京 → 上海 → 北京",
    "estimated_budget": "CNY 2,400（规划估算）", "price_notice": "列车票价与指定日期房价未核验；请以原渠道为准。",
    "sources": [{"title": "会场交通说明", "url": "https://www.sniec.net/"}],
    "notes": ["展会入场请携带有效身份证件。"],
    "daily_plans": [
        {"day": 1, "date": "2026-11-25", "city": "上海", "theme": "抵达与入住",
         "activities": [activity("09:10", "出发前往上海", "北京南站", "G115", "出发前核对车次和进站时间。"),
                        activity("14:20–15:00", "抵达后前往住宿", "上海虹桥站", "地铁", "入住以酒店确认时间为准。")]},
        {"day": 2, "date": "2026-11-26", "city": "上海", "theme": "会展与会后联络",
         "activities": [activity("09:00", "签到入场", "展馆 2 号门", "从住宿步行至会场"),
                        activity("10:30", "参加行业交流会", "主会场", details="现场可能调整议程。"),
                        activity("时间待定", "与合作方会后沟通", details="待对方回复，无已定时刻。")],
         "meals": {"lunch": "会场周边简餐", "dinner": "会后自理"}},
        {"day": 3, "date": "2026-11-27", "city": "上海", "theme": "整理材料与返程",
         "activities": [activity("上午", "整理会议材料"), activity("18:00", "返程", "上海虹桥站", "G22")]},
    ],
}


def train(no, departs, arrives, seats):
    return {"train_no": no, "train_type": "高铁", "from_station": "北京南", "to_station": "上海虹桥",
            "depart_time": departs, "arrive_time": arrives, "duration": "约 4 小时 30 分",
            "second_class": seats, "first_class": "无", "business": "--"}


TRAINS = {
    "availability_status": "partial", "price_status": "unavailable", "query_success": True,
    "results": {"from": "北京南", "to": "上海虹桥", "date": "2026-11-25", "queried_at": "2026-11-21T02:25:00Z",
                "summary": "部分车次数据可用；上下车站与余票以 12306 为准。",
                "sources": [{"title": "铁路12306", "url": "https://www.12306.cn/"}],
                "trains": [train("G115", "09:10", "13:36", "有"), train("G123", "10:00", "14:42", "候补"),
                           train("G135", "11:05", "15:41", "有"), train("G147", "12:30", "17:02", "无")]},
}


def hotel(number, name, cost, location="", distance=""):
    return {"id": str(number), "name": name, "address": "上海市浦东新区 · 会场周边", "cost": cost,
            "rating": "4.6", "location": location, "distance": distance}


HOTELS = {
    "results": {"city": "上海", "keyword": "会场周边住宿", "count": 6, "price_status": "reference_only",
                "sources": [{"title": "高德地图", "url": "https://www.amap.com/"}],
                "hotels": [hotel(1, "会展中心商务酒店", "468–528", "121.563,31.211", "720"),
                           hotel(2, "芳甸路会展公寓", "", "", "1100"),
                           hotel(3, "世纪大道商务酒店", "389", "121.538,31.223", "1900"),
                           hotel(4, "金桥商旅酒店", "356"), hotel(5, "浦东便捷酒店", "329"),
                           hotel(6, "世纪公园商旅酒店", "418")]},
}
RESULTS = [
    {"agent_name": agent, "node_id": key, "status": "success", "data": data}
    for agent, key, data in [("itinerary_planning", "itinerary", {"itinerary": ITINERARY}),
                             ("train_ticket", "outbound", TRAINS), ("hotel_search", "hotels", HOTELS)]
]


def stream(emit, _):
    emit("complete", {"status": "completed", "results": RESULTS})


def run_mode(browser, assets, output, mode, record):
    compact = mode != "desktop"
    reduced = mode == "reduced"
    width, height = (320, 650) if reduced else (390, 844) if compact else (1366, 900)
    with preview(assets, chat_script=stream) as (base, posted, _), TemporaryDirectory() as clips, ExitStack() as stack:
        ctx = browser.new_context(viewport={"width": width, "height": height}, is_mobile=compact, has_touch=compact,
                                  color_scheme="dark" if compact else "light", device_scale_factor=1,
                                  reduced_motion="reduce" if reduced else "no-preference",
                                  record_video_dir=clips if record else None,
                                  record_video_size={"width": width, "height": height} if record else None)
        stack.callback(ctx.close)
        errors = []
        page = guarded_page(ctx, errors)
        page.goto(base, wait_until="networkidle")
        paths = page.evaluate("performance.getEntriesByType('resource').map(e=>new URL(e.name).pathname)")
        assert not any(any(chunk + "-" in path for chunk in ("FlightResult", "ItineraryCard", "TrainCard", "HotelCard"))
                       for path in paths), paths
        page.get_by_role("textbox", name="输入消息").fill("查看上海会展的逐日行程、铁路车票和会场附近住宿。")
        page.get_by_role("button", name="开始规划").click()
        days = page.get_by_role("region", name="逐日行程")
        rail = page.get_by_role("region", name="铁路车票")
        hotels = page.get_by_role("region", name="住宿候选")
        expect(hotels).to_be_visible()

        def top(element):
            element.evaluate("e=>e.scrollIntoView({block:'start'})")

        def pause(ms=950):
            if record:
                page.wait_for_timeout(ms)

        top(days)
        second = days.get_by_role("button", name="第 2 天", exact=False)
        expect(second).to_have_attribute("aria-expanded", "false")
        expect(second).to_contain_text("1 项时刻待核验")
        expect(days.get_by_text("预计预算：CNY 2,400", exact=False)).to_be_visible()
        expect(days.get_by_role("link", name="会场交通说明")).to_have_attribute("href", "https://www.sniec.net/")
        expect(days.get_by_text("与合作方会后沟通")).to_be_hidden()
        page.evaluate("""window.dayTrace=0; document.addEventListener('animationstart', e=>{
            if(e.animationName==='fdr-follow-order') window.dayTrace++
        })""")
        pause()
        if reduced:
            second.focus()
            second.press("Enter")
            expect(second).to_be_focused()
        else:
            second.click()
        expect(second).to_have_attribute("aria-expanded", "true")
        detail = days.locator(".fdr-day-detail").nth(1)
        expect(detail.get_by_text("时刻待核验", exact=True)).to_be_visible()
        expect(detail.get_by_text("午餐：会场周边简餐")).to_be_visible()
        assert detail.locator(".fdr-stop-time").all_inner_texts() == ["09:00", "10:30", "时刻待核验"]
        if reduced:
            assert detail.locator(".fdr-dayrail").evaluate("e=>getComputedStyle(e,'::after').animationName") == "none"
        else:
            page.wait_for_function("window.dayTrace === 1")
        if record:
            page.wait_for_timeout(370)
            days.get_by_role("button", name="第 1 天", exact=False).click()
            top(days)
            page.screenshot(path=output / f"{mode}-itinerary.png")
        pause(800)
        second.click()
        second.click()
        assert page.evaluate("window.dayTrace") == (0 if reduced else 1)
        days.get_by_role("button", name="展开全部").click()
        expect(days.get_by_text("整理会议材料")).to_be_visible()
        days.get_by_role("button", name="导出", exact=True).click()
        expect(days.get_by_role("menuitem", name="打印 / PDF")).to_be_visible()
        page.keyboard.press("Escape")
        expect(days.get_by_role("menu", name="导出行程")).to_have_count(0)

        top(rail)
        expect(rail.get_by_text("官方票价未核验")).to_be_visible()
        expect(rail.get_by_text("查询时间 2026-11-21 10:25", exact=False)).to_be_visible()
        expect(rail.get_by_role("link", name="铁路12306")).to_have_attribute("href", "https://www.12306.cn/")
        expect(rail.get_by_role("link", name="前往12306核验")).to_be_visible()
        expect(rail.get_by_text("G147", exact=True)).to_have_count(0)
        assert rail.locator(".fdr-train").first.locator(".fdr-seats dd").all_inner_texts() == ["有", "无", "未提供"]
        pause()
        rail.get_by_role("button", name="展开其余 1 趟").click()
        expect(rail.get_by_text("G147", exact=True)).to_be_visible()
        expect(rail.get_by_text("官方票价未核验")).to_be_visible()
        top(rail)
        if record:
            page.screenshot(path=output / f"{mode}-rail.png")
        pause(1300)

        top(hotels)
        expect(hotels.get_by_role("link", name="高德地图", exact=True)).to_have_attribute("href", "https://www.amap.com/")
        expect(hotels.get_by_text("指定日期的房价与房态未核验")).to_be_visible()
        expect(hotels.get_by_text("参考 ¥468–528")).to_be_visible()
        expect(hotels.get_by_text("房价待核验", exact=True).first).to_be_visible()
        expect(hotels.get_by_role("link", name="在高德打开：芳甸路会展公寓")).to_have_count(0)
        assert "uri.amap.com/marker" in hotels.get_by_role("link", name="在高德打开：会展中心商务酒店").get_attribute("href")
        pause()
        hotels.get_by_role("button", name="查看全部 6 家").click()
        expect(hotels.get_by_text("参考 ¥418")).to_be_visible()
        expect(hotels.get_by_role("link", name="高德地图", exact=True)).to_be_visible()
        top(hotels)
        if record:
            page.screenshot(path=output / f"{mode}-stay.png")
        pause(1350)
        assert_no_overflow(page)
        assert page.locator(".flight-result").evaluate_all("es=>es.every(e=>e.scrollWidth<=e.clientWidth+1)")
        assert [p for p, _ in posted if p == "/api/chat" or p.startswith("/api/personal/")] == ["/api/chat"]
        assert not errors, errors
        clip = page.video
        ctx.close()
        return {"视口": [width, height], "首次主动展开描线": 0 if reduced else 1, "只读操作追加业务请求": 0,
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
    print("三类卡片的桌面、手机和减动回放通过。")


if __name__ == "__main__":
    main()
