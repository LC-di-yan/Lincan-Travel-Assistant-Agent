"""Exercise and record proposal decisions against the production web bundle."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from playwright.sync_api import expect, sync_playwright

from run_flightdeck_visual_audit import assert_no_overflow, guarded_page, preview, save_recording


def leg(train, date, departure, arrival, start, end):
    return {"train_no": train, "from_station": start, "to_station": end,
            "departs": f"{date}T{departure}:00+08:00", "arrives": f"{date}T{arrival}:00+08:00"}


def proposal(letter, train, times, hotel, walk, hotel_price, total):
    costs = [
        {"kind": key, "amount": amount, "currency": "CNY",
         "quality": "user_budget" if key == "other" else "verified_quote",
         "queried_at": None if key == "other" else "2026-11-21T10:25:00+08:00"}
        for key, amount in [("outbound", "553"), ("inbound", "553"), ("hotel", hotel_price), ("other", "240")]
    ]
    return {
        "id": f"fixture-{letter}", "status": "validated", "budget_status": "within",
        "known_subtotals": {"CNY": total}, "cost_items": costs,
        "outbound": leg(train, "2026-11-25", *times, "北京南", "上海虹桥"),
        "inbound": leg("G22", "2026-11-27", "18:00", "22:29", "上海虹桥", "北京南"),
        "hotel": {"id": f"hotel-{letter}", "name": hotel, "address": "上海市浦东新区"},
        "commute": {"duration_min": walk}, "reasons": [f"酒店至会场步行约 {walk} 分钟（地图估算）"],
    }


A = proposal("A", "G115", ("09:10", "13:36"), "会展中心酒店", 8, "868.50", "2214.50")
B = proposal("B", "G123", ("10:00", "14:42"), "世纪大道商务酒店", 18, "730.50", "2076.50")
C = {**B, "id": "fixture-C", "status": "provisional", "known_subtotals": {"CNY": "1346"},
     "budget_status": "unverified", "cost_items": [{**row, "amount": None} if row["kind"] == "hotel" else row
                                                  for row in B["cost_items"]], "issues": ["住宿报价待核验。"]}


def plan_result(options, session, personal=True):
    plan = {
        "request": {"origin": "北京", "destination": "上海", "depart_date": "2026-11-25",
                    "resolved_return_date": "2026-11-27", "hotel_nights": 2, "budget": {"amount": "2400", "currency": "CNY"}},
        "recommended": options[0] if options else None, "alternatives": options,
        "validation": {"note": "报价时点仅供核对，未预订。"},
    }
    return {
        "status": "completed", "trip_plan": plan,
        "results": [{"node_id": "proposal", "agent_name": "itinerary_planning", "status": "success",
                     "data": {"answer": "核对往返车次、住宿和到会场的时间。", "trip_plan": plan}}],
        **({"candidate_ref": "fixture-candidate", "candidate_session_id": session,
            "personal_conflicts": {"issues": []}} if personal else {}),
    }


def start(page, text):
    editor = page.get_by_role("textbox", name="输入消息")
    editor.fill(text)
    editor.press("Enter")
    deck = page.get_by_role("region", name="差旅方案对比").last
    expect(deck).to_be_visible()
    return deck


def budgets(page):
    paths = page.evaluate("performance.getEntriesByType('resource').map(e=>new URL(e.name).pathname)")
    assert not any("TripPlanCard-" in path or "proposalComparison-" in path for path in paths), paths


def verify_mode(browser, assets, output, mode, record):
    mobile = mode == "mobile"
    width, height = (390, 844) if mobile else (1366, 900)
    confirmed = Event()
    saves = []

    def stream(emit, body):
        if body["message"] == "选择方案2":
            if confirmed.wait(20):
                emit("complete", {"status": "completed", "results": [], "selected_proposal": B["id"]})
        else:
            result = plan_result([A, B], body["session_id"])
            result["personal_conflicts"] = {"issues": [
                {"id": "calendar-1", "severity": "definite", "message": "与已安排的会议重叠。",
                 "other": {"plan_id": "fixture-old", "version": 2}, "blocks_schedule": True},
                {"id": "trip-1", "severity": "unknown", "message": "本行程有建议活动的时段待核对。",
                 "other": None, "blocks_schedule": False},
            ]}
            emit("complete", result)

    def write(route):
        saves.append(route.request.post_data_json)
        route.fulfill(json={"plan_id": "fixture-plan", "version": 1})

    with preview(assets, chat_script=stream, get_fixture=lambda path: (
        {"enabled": True, "csrf_token": "local-fixture"} if path == "/api/personal/capabilities" else None
    )) as (base, posted, _), TemporaryDirectory() as clips, ExitStack() as stack:
        context = browser.new_context(
            viewport={"width": width, "height": height}, is_mobile=mobile, has_touch=mobile, device_scale_factor=1,
            color_scheme="dark" if mobile else "light",
            record_video_dir=clips if record else None, record_video_size={"width": width, "height": height} if record else None,
        )
        stack.callback(context.close)
        errors = []
        page = guarded_page(context, errors)
        page.route("**/api/personal/trips", write)
        page.goto(base, wait_until="networkidle")
        budgets(page)

        def hold(ms=750):
            if record:
                page.wait_for_timeout(ms)  # viewer pacing, not part of the application

        deck = start(page, "周三从北京去上海出差三天，预算 2400 元，比较住宿和到会场的时间。")
        deck.evaluate("e=>e.scrollIntoView({block:'start'})")
        expect(deck).to_contain_text("G115")
        expect(deck).to_contain_text("预览不等于确认")
        a = deck.get_by_role("button", name="预览方案 A")
        b = deck.get_by_role("button", name="预览方案 B")
        expect(a).to_have_attribute("aria-pressed", "true")
        hold()
        deck.get_by_role("button", name="对比差异").click()
        table = deck.get_by_role("table", name="方案 A 与 B 的差异")
        expect(deck.locator(".proposal-delta")).to_contain_text("B 比 A 少")
        expect(deck.locator(".proposal-delta")).to_contain_text("138.00")
        expect(deck.locator(".proposal-delta")).to_contain_text("多走约 10 分钟")
        expect(table.get_by_role("row", name="返程", exact=False).first).to_have_attribute("data-difference", "false")
        expect(table).to_contain_text("步行约 18 分钟")
        top = table.bounding_box()["y"]
        page.evaluate("""window.proposalMotion=[]; document.addEventListener('animationstart', event => {
            if (event.animationName.startsWith('proposal-')) window.proposalMotion.push(event.animationName)
        })""")
        hold()
        b.click()
        expect(table.get_by_role("columnheader", name="方案 B", exact=False)).to_contain_text("预览中")
        expect(deck.get_by_label("方案 B 概览")).to_contain_text("G123")
        page.wait_for_function("window.proposalMotion.includes('proposal-switch')")
        assert abs(table.bounding_box()["y"] - top) < 2, (top, table.bounding_box())
        page.wait_for_function("document.getAnimations().every(a=>a.playState!=='running')")
        page.screenshot(path=output / f"{mode}-compare.png")
        hold(1000)
        # A quick round trip must use the last user input; comparison columns stay A then B.
        b.evaluate("e=>{ e.previousElementSibling.click(); e.click(); e.previousElementSibling.click() }")
        expect(a).to_have_attribute("aria-pressed", "true")
        assert [col.inner_text().splitlines()[0] for col in table.get_by_role("columnheader").all()] == ["对照项", "方案 A", "方案 B"]
        b.click()
        deck.get_by_role("button", name="收起对比").click()
        deck.get_by_role("button", name="展开行程与费用明细").click()
        expect(deck.get_by_text("日期待核验")).to_have_count(0)
        expect(deck.get_by_text("费用依据", exact=False)).to_be_visible()
        expect(deck).to_contain_text("查询于 2026-11-21 10:25")
        deck.locator(".proposal-sheet-top").evaluate("e=>e.scrollIntoView({block:'start'})")
        page.wait_for_function("document.getAnimations().every(a=>a.playState!=='running')")
        page.screenshot(path=output / f"{mode}-detail.png")
        hold()
        assert [p for p, _ in posted if p == "/api/chat"] == ["/api/chat"] and not saves
        saving = page.get_by_role("region", name="保存行程草稿")
        scheduled = saving.locator("details").filter(has_text="与已有安排有关的提示")
        local = saving.locator("details").filter(has_text="本行程时间与信息提示")
        expect(scheduled.locator("summary")).to_contain_text("1 项确定冲突")
        expect(local.locator("summary")).to_contain_text("1 项待核验")
        expect(scheduled.get_by_role("link", name="查看原安排")).to_be_hidden()
        expect(local.get_by_text("本行程有建议活动的时段待核对。", exact=False)).to_be_hidden()
        expect(saving.get_by_role("button", name="保存为草稿")).to_be_visible()
        saving.screenshot(path=output / f"{mode}-conflicts-collapsed.png")
        scheduled.locator("summary").press("Enter")
        expect(scheduled.get_by_role("link", name="查看原安排")).to_have_attribute("href", "#/personal/trips/fixture-old?v=2")
        expect(local.get_by_text("本行程有建议活动的时段待核对。", exact=False)).to_be_hidden()
        saving.screenshot(path=output / f"{mode}-conflicts-expanded.png")
        scheduled.locator("summary").press("Space")
        expect(scheduled.get_by_role("link", name="查看原安排")).to_be_hidden()
        local.locator("summary").click()
        expect(local.get_by_text("本行程有建议活动的时段待核对。", exact=False)).to_be_visible()
        local.locator("summary").click()
        assert not saves
        expect(page.get_by_label("保存时采用")).to_have_value("")
        deck.get_by_role("button", name="收起行程与费用明细").click()
        choice = deck.get_by_role("button", name="选择方案 2")
        choice.click()
        expect(deck).to_contain_text("等待确认回执")
        expect(deck).not_to_contain_text("已确认方案 B")
        expect(page.get_by_label("保存时采用")).to_have_value("")
        assert not saves
        hold()
        confirmed.set()
        expect(deck).to_contain_text("已确认方案 B")
        expect(page.get_by_label("保存时采用")).to_have_value(B["id"])
        assert not saves
        a.click()
        expect(deck).to_contain_text("已确认方案 B")
        expect(page.get_by_label("保存时采用")).to_have_value(B["id"])
        hold()
        deck.get_by_role("button", name="前往保存草稿").click()
        saving = page.get_by_role("region", name="保存行程草稿")
        expect(saving).to_be_focused()
        expect(saving).to_contain_text("本次草稿采用方案 B，保留其他候选。")
        hold()
        saving.get_by_role("button", name="保存为草稿").click()
        expect(saving.get_by_role("link", name="已保存第 1 版草稿，前往查看")).to_be_visible()
        assert len(saves) == 1 and saves[0]["candidate_ref"] == "fixture-candidate" and saves[0]["option_id"] == B["id"]
        chat = [body["message"] for path, body in posted if path == "/api/chat"]
        assert len(chat) == 2 and chat[-1] == "选择方案2"
        assert_no_overflow(page)
        assert not errors, errors
        hold(1000)
        clip = page.video
        context.close()
        return {"视口": [width, height], "规划": 1, "确认": 1, "保存": 1, "草稿采用": "B",
                "录屏": save_recording(clip, output / f"{mode}-operation") if clip else None}


def verify_edges(browser, assets):
    def stream(emit, body):
        text = body["message"]
        if text.startswith("选择方案"):
            return emit("clarification", {"question": "当前报价已过期，请重新规划。"})
        options = {"无候选": [], "单候选": [A], "三候选": [A, B, C]}[text]
        emit("complete", plan_result(options, body["session_id"], personal=False))

    with preview(assets, chat_script=stream) as (base, posted, _):
        context = browser.new_context(viewport={"width": 320, "height": 650}, is_mobile=True, has_touch=True,
                                      reduced_motion="reduce")
        errors = []
        page = guarded_page(context, errors)
        page.goto(base, wait_until="networkidle")
        deck = start(page, "无候选")
        expect(deck).to_contain_text("暂无可对比的候选")
        deck = start(page, "单候选")
        expect(deck.get_by_role("button", name="对比差异")).to_have_count(0)
        expect(deck.get_by_role("button", name="选择方案 1")).to_be_visible()
        deck = start(page, "三候选")
        deck.get_by_role("button", name="对比差异").click()
        button = deck.get_by_role("button", name="预览方案 C")
        button.focus()
        button.press("Enter")
        expect(button).to_be_focused()
        table = deck.get_by_role("table", name="方案 A 与 C 的差异")
        expect(table).to_contain_text("仅已知费用小计")
        expect(table).to_contain_text("未能确认符合预算")
        expect(deck).to_contain_text("才计算费用差")
        expect(deck.get_by_role("button", name="选择方案 3")).to_have_count(0)
        assert deck.locator(".proposal-preview").evaluate("e=>getComputedStyle(e).animationName") == "none"
        assert table.evaluate("e=>e.scrollWidth <= e.clientWidth+1")
        assert_no_overflow(page)
        deck.get_by_role("button", name="预览方案 B").click()
        deck.get_by_role("button", name="选择方案 2").click()
        expect(deck).to_contain_text("未收到确认回执")
        expect(deck).not_to_contain_text("已确认方案 B")
        expect(page.get_by_role("region", name="保存行程草稿")).to_have_count(0)
        assert len([p for p, _ in posted if p == "/api/chat"]) == 4
        assert not errors, errors
        context.close()
        return "0、1、3 候选；320px 减动和键盘；缺价不计算差额；过期不确认；无保存能力仍可比较"


def verify_third_option(browser, assets):
    third = proposal("C", "G135", ("11:05", "15:41"), "浦东会场附近酒店", 13, "803", "2149")

    def stream(emit, body):
        if body["message"] == "选择方案3":
            return emit("complete", {"status": "completed", "results": [], "selected_proposal": third["id"]})
        emit("complete", plan_result([A, B, third], body["session_id"]))

    def caps(path):
        if path == "/api/personal/capabilities":
            return {"enabled": True, "csrf_token": "local-fixture"}

    with preview(assets, chat_script=stream, get_fixture=caps) as (base, posted, _):
        context = browser.new_context()
        errors, drafts = [], []
        page = guarded_page(context, errors)

        def write(route):
            drafts.append(route.request.post_data_json)
            route.fulfill(json={"plan_id": "fixture-plan", "version": 1})

        page.route("**/api/personal/trips", write)
        page.goto(base, wait_until="networkidle")
        deck = start(page, "核对三份可选方案")
        deck.get_by_role("button", name="预览方案 C").click()
        deck.get_by_role("button", name="对比差异").click()
        expect(deck.get_by_role("table", name="方案 A 与 C 的差异")).to_contain_text("G135")
        deck.get_by_label("左对比方案").select_option(label="方案 B")
        comparison = deck.get_by_role("table", name="方案 B 与 C 的差异")
        expect(comparison).to_contain_text("G135")
        expect(comparison.get_by_role("rowheader", name="返程", exact=True)).to_be_visible()
        deck.get_by_role("button", name="只看差异").click()
        expect(comparison.get_by_role("rowheader", name="返程", exact=True)).to_have_count(0)
        expect(comparison).to_contain_text("G135")
        deck.get_by_role("button", name="选择方案 3").click()
        expect(deck).to_contain_text("已确认方案 C")
        assert not drafts
        page.get_by_role("button", name="保存为草稿").click()
        expect(page.get_by_role("link", name="已保存第 1 版草稿，前往查看")).to_be_visible()
        assert len(drafts) == 1 and drafts[0]["option_id"] == third["id"]
        assert [body["message"] for path, body in posted if path == "/api/chat"] == ["核对三份可选方案", "选择方案3"]
        assert not errors, errors
        context.close()
        return "以 A 对比 C；显式确认 C；主动保存携带 C 的 option_id"


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
        report = {mode: verify_mode(browser, args.assets.resolve(), args.output, mode, args.record)
                  for mode in ("desktop", "mobile")}
        report["边界场景"] = verify_edges(browser, args.assets.resolve())
        report["第三候选"] = verify_third_option(browser, args.assets.resolve())
        report["浏览器"] = browser.version
        browser.close()
    (args.output / "replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已验证桌面和手机方案对比、确认与主动保存。")


if __name__ == "__main__":
    main()
