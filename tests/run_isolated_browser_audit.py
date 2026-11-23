"""Exercise the built React app, real Aligo server and local provider fixtures."""

import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


REPO = Path(__file__).resolve().parents[1]
QUESTION = "你的具体起点和终点是哪里，更在意省钱还是少换乘？"


def _restrict_network():
    real = socket.socket

    class LoopbackSocket(real):
        def connect(self, address):
            assert self.family not in (socket.AF_INET, socket.AF_INET6) or address[0] in {"127.0.0.1", "::1"}
            return super().connect(address)

        def connect_ex(self, address):
            assert self.family not in (socket.AF_INET, socket.AF_INET6) or address[0] in {"127.0.0.1", "::1"}
            return super().connect_ex(address)

    pair = socket.socketpair

    def socketpair(*args, **kwargs):
        socket.socket = real
        try:
            return pair(*args, **kwargs)
        finally:
            socket.socket = LoopbackSocket

    socket.socket = LoopbackSocket
    socket.socketpair = socketpair


def _provider():
    import asyncio
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from mock_audio_provider import app

    calls = []

    @app.get("/fixtures/calls")
    async def show_calls():
        return calls

    @app.get("/otn/login/init")
    async def rail_init():
        return {}

    @app.get("/otn/leftTicket/queryZ")
    async def rail(request: Request):
        params = request.query_params
        start, end, day = (params["leftTicketDTO." + item] for item in ("from_station", "to_station", "train_date"))
        calls.append({"node": "rail", "from": start, "to": end, "day": day})
        await asyncio.sleep(0.18)
        row = [""] * 33
        is_return = start == "SHH" and end == "GZQ"
        row[3] = "G201" if is_return else "G102"
        row[6:11] = [start, end, "15:00", "21:00", "06:00"] if is_return else [start, end, "09:00", "15:00", "06:00"]
        row[30] = "有"
        cities = {"SHH": "上海", "BJP": "北京", "GZQ": "广州"}
        return {"httpstatus": 200, "data": {"map": {c: cities.get(c, c) for c in (start, end)}, "result": ["|".join(row)]}}

    @app.get("/v3/weather/weatherInfo")
    async def weather(request: Request):
        params = request.query_params
        calls.append({"node": "weather", "city": params["city"]})
        if params["city"] == "110000":
            await asyncio.sleep(1.25)
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        if params["extensions"] == "base":
            return {"status": "1", "lives": [{"temperature": "5", "weather": "晴",
                      "winddirection": "北", "windpower": "3", "reporttime": now.strftime("%Y-%m-%d %H:%M:%S")}]}
        return {"status": "1", "forecasts": [{"casts": [
            {"date": (now.date() + timedelta(days=i)).isoformat(), "dayweather": "小雨", "nightweather": "阴",
             "daytemp": "7", "nighttemp": "-2", "daywind": "北", "nightwind": "北", "daypower": "3", "nightpower": "3"}
            for i in range(4)
        ]}]}

    @app.get("/v3/place/text")
    async def hotels():
        calls.append({"node": "hotels"})
        await asyncio.sleep(0.10)
        return {"status": "1", "count": "1", "pois": [{
            "id": "fixture-point", "name": "合成住宿", "location": "121.5,31.2",
            "biz_ext": {"cost": "300", "rating": "4.5"},
        }]}

    @app.get("/v3/geocode/geo")
    async def geocode():
        return {"status": "1", "geocodes": [{"city": [], "province": "上海市", "level": "兴趣点", "location": "121.51,31.21"}]}

    @app.get("/v3/direction/walking")
    async def walking():
        calls.append({"node": "commute"})
        return {"status": "1", "route": {"paths": [{"distance": "900", "duration": "720"}]}}

    @app.get("/v1/latest")
    async def exchange():
        calls.append({"node": "exchange"})
        return {"date": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(), "rates": {"CNY": 7.2}}

    @app.post("/model/chat/completions")
    async def chat_model(request: Request):
        body = await request.json()
        name = body["model"]
        tool = body.get("tool_choice")
        calls.append({"node": "model", "role": name})
        if tool:
            result = {"intents": [{"type": "itinerary_planning", "confidence": 1}], "agent_schedule": [],
                      "fast_event": {"missing_info": ["目的地", "出发日期"]},
                      "needs_clarification": True, "clarification_question": "请问想去哪里？什么时候出发？"}
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "type": "function", "id": "call-fixture",
                "function": {"name": "submit_intent", "arguments": json.dumps(result, ensure_ascii=False)},
            }]}
        elif name == "fixture-legacy":
            message = {"role": "assistant", "content": json.dumps({"itinerary": {"title": "合成一日游",
                       "daily_plans": [{"day": 1, "activities": [{"activity": "参观公园"}]}]}, "planning_complete": True}, ensure_ascii=False)}
        else:
            return JSONResponse({"error": {"message": "unexpected mock completion"}}, status_code=400)
        return {"id": "fixture-model", "model": name, "object": "chat.completion", "created": 1, "choices": [{
            "index": 0, "finish_reason": "tool_calls" if tool else "stop", "message": message,
        }], "usage": {"prompt_tokens": 10, "completion_tokens": 9, "total_tokens": 19}}

    return app


def _actual_app(fixture_url):
    import httpx
    from config import AMAP_CONFIG

    AMAP_CONFIG["base_url"] = fixture_url + "/v3"
    send = httpx.AsyncClient.send

    async def local_send(client, request, **kwargs):
        if request.url.host in {"kyfw.12306.cn", "api.frankfurter.dev"}:
            request.url = httpx.URL(fixture_url + request.url.raw_path.decode("ascii"))
            request.headers["host"] = request.url.netloc.decode("ascii")
        assert request.url.host == "127.0.0.1", f"Disallowed upstream: {request.url.host}"
        return await send(client, request, **kwargs)

    httpx.AsyncClient.send = local_send
    from server.app import app

    return app


def _serve(which, listen, fixture_url):
    _restrict_network()
    sys.path.insert(0, str(Path.cwd()))
    import uvicorn

    app = _provider() if which == "fixture" else _actual_app(fixture_url)
    uvicorn.run(app, host="127.0.0.1", port=listen, log_level="warning", access_log=False)


def _port():
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        return stream.getsockname()[1]


def _check_browser(base, fixture, output, chromium_exe=None):
    import httpx
    from playwright.sync_api import expect, sync_playwright

    def get_calls():
        return httpx.get(fixture + "/fixtures/calls", trust_env=False).json()

    def status(label):
        print("BROWSER " + label, flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=chromium_exe)
        context = browser.new_context(viewport={"width": 1366, "height": 880})
        page = context.new_page()
        page_errors, external = [], []
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        def network(route):
            if urlsplit(route.request.url).hostname != "127.0.0.1":
                external.append(urlsplit(route.request.url).hostname)
                return route.abort()
            return route.continue_()

        page.route("**/*", network)
        page.goto(base, wait_until="networkidle")
        box = page.get_by_role("textbox", name="输入消息")
        chat_send = page.get_by_role("button", name=re.compile(r"^(开始规划|发送消息)$"))
        user_count = lambda: page.locator('[data-message-role="user"]').count()
        assistant = page.locator('[data-message-role="assistant"]')

        def send(text):
            box.fill(text)
            chat_send.click()
            page.wait_for_function("() => !!document.querySelector('button[aria-label=\"发送消息\"]')", timeout=10000)
            return assistant.last

        data = send("请帮我查一下北京的天气和交通")
        note = data.get_by_role("complementary", name="助手的后续提问")
        expect(note).to_contain_text(QUESTION)
        count = user_count()
        note.click()
        expect(page.locator('[data-message-role="user"]')).to_have_count(count)
        assert note.get_by_role("button").count() == 0
        status("助手追问不能变成用户消息")

        expect(send("查去北京的火车票，我想少换乘")).to_contain_text("出发")
        expect(send("上海")).to_contain_text("哪天")
        expect(send("明天")).to_contain_text("G102")
        expect(assistant.last).to_contain_text("上海 → 北京")
        assert any(n["node"] == "rail" and n["from"] == "SHH" and n["to"] == "BJP" for n in get_calls())
        status("铁路三轮填槽后实际查直达余票")

        result = send("上海明天的天气怎么样？")
        expect(result).to_contain_text("-2~7°C")
        expect(result).not_to_contain_text("当前气温")
        status("未来天气不冒充当前气温")

        plan = send("明天从广州去上海出差，大后天下午回来，1人，预算3000元，会议地点是上海世博中心，会议时间后天10:00-12:00")
        expect(plan.get_by_label("差旅方案对比")).to_be_visible()
        plan.get_by_role("button", name="展开行程与费用明细").click()
        expect(plan.get_by_label("差旅方案对比")).to_contain_text("G201")
        expect(plan.get_by_label("差旅方案对比")).to_contain_text("未能确认符合预算")
        count = len(get_calls())
        changed = send("预算改为2500元")
        expect(changed.get_by_label("差旅方案对比")).to_contain_text("2500")
        assert len(get_calls()) == count
        status("去返程、住宿、天气、通勤汇总；改预算不重查")

        receipt = send("记一笔打车30元、午餐50美元")
        expect(receipt).to_contain_text("账本未修改")
        assert not context.request.get(base + "/api/expenses").json()["expenses"]
        receipt.get_by_role("button", name="确认这项费用操作").click()
        expect(assistant.last).to_contain_text("已一次性记录 2 笔费用")
        expenses = context.request.get(base + "/api/expenses").json()["expenses"]
        assert {(float(e["amount"]), e["currency"]) for e in expenses} == {(30, "CNY"), (50, "USD")}
        status("账本前端显式确认、原币与多笔记录")

        box.fill("北京明天的天气怎么样？")
        chat_send.click()
        page.get_by_role("button", name="停止生成").last.click(timeout=5000)
        expect(assistant.last).to_contain_text("已停止生成")
        expect(send("换算100美元为人民币")).to_contain_text("720")
        status("取消后可继续下一条消息")

        expect(send("帮我规划一个新行程")).to_contain_text("什么时候出发")
        assert any(n.get("role") == "fixture-primary" for n in get_calls())
        expect(send("帮我规划从北京去南京旅游3天")).to_contain_text("合成一日游")
        assert any(n.get("role") == "fixture-legacy" for n in get_calls())
        status("主模型与旧行程模型分别走真实兼容客户端")
        assert not page_errors, page_errors
        page.screenshot(path=str(output / "browser-desktop.png"))

        mobile = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark", is_mobile=True, has_touch=True)
        mp = mobile.new_page()
        mp.route("**/*", network)
        mp.goto(base, wait_until="networkidle")
        expect(mp.get_by_role("textbox", name="输入消息")).to_be_visible()
        assert mp.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
        assert mp.evaluate("document.documentElement.classList.contains('dark')")
        assert not mobile.request.get(base + "/api/expenses").json()["expenses"]
        mp.screenshot(path=str(output / "browser-mobile.png"))
        assert not page_errors, page_errors
        status("窄屏可输入；第二个浏览器上下文看不到前者账本")

        delayed = browser.new_context()
        late_page = delayed.new_page()
        late_page.route("**/*", network)
        held = []
        late_page.route("**/api/session/new", lambda route: held.append(route))
        def next_session_request():
            for _ in range(80):
                if held:
                    assert len(held) == 1
                    return held[0]
                late_page.wait_for_timeout(25)
            raise AssertionError("Expected one pending session request")

        late_page.goto(base, wait_until="domcontentloaded")
        late_box = late_page.get_by_role("textbox", name="输入消息")
        expect(late_box).to_be_visible()
        late_box.fill("上海明天的天气怎么样？")
        late_page.get_by_role("button", name=re.compile(r"^(开始规划|发送消息)$")).click()
        late_page.get_by_role("button", name="停止生成").last.click()
        last = late_page.locator('[data-message-role="assistant"]').last
        expect(last).to_contain_text("已停止生成")
        with late_page.expect_response("**/api/session/new") as rejected:
            next_session_request().fulfill(status=503, content_type="application/json", body='{"detail":"fixture delay"}')
        assert rejected.value.status == 503
        late_page.wait_for_timeout(150)
        expect(last).to_contain_text("已停止生成")
        held.clear()
        late_box.fill("上海明天的天气怎么样？")
        late_page.get_by_role("button", name=re.compile(r"^(开始规划|发送消息)$")).click()
        late_page.get_by_role("button", name="停止生成").last.wait_for()
        next_session_request().fulfill(status=503, content_type="application/json", body='{"detail":"fixture failure"}')
        expect(last.get_by_role("alert")).to_contain_text("连接失败")
        late_page.unroute("**/api/session/new")
        last.get_by_role("button", name="重试上一条消息").click()
        expect(last).to_contain_text("-2~7°C")
        status("已取消不被迟到的失败覆盖；未取消仍显示错误并可重试")


def _check_personal_browser(base, fixture, output, chromium_exe=None):
    from playwright.sync_api import expect, sync_playwright

    tomorrow = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=2)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=chromium_exe, args=["--disable-background-networking", "--disable-features=msEdgeSidebarV2"])
        page = browser.new_page(viewport={"width": 1260, "height": 850}, accept_downloads=True)
        blocked = []

        def route(request):
            if urlsplit(request.request.url).hostname != "127.0.0.1":
                blocked.append(urlsplit(request.request.url).hostname)
                return request.abort()
            return request.continue_()

        page.route("**/*", route)
        page.goto(base, wait_until="networkidle")
        page.get_by_role("link", name="个人中心").click()
        expect(page.get_by_role("heading", name="个人中心", exact=True)).to_be_focused()
        expect(page.get_by_role("heading", name="从一份草稿开始")).to_be_visible()

        def manual(where, title):
            page.goto(base + "/#/personal/trips/new")
            page.get_by_label("行程名称").fill(title)
            page.get_by_label("目的城市").fill(where)
            page.get_by_label("出发日期").fill(tomorrow.isoformat())
            page.get_by_role("button", name="添加活动").click()
            page.get_by_label("活动名称").fill(title + "会议")
            page.get_by_label("城市", exact=True).fill(where)
            page.get_by_label("地点或车站").fill("主会场")
            page.get_by_label("开始时间").fill(tomorrow.isoformat() + "T10:00")
            page.get_by_label("结束时间").fill(tomorrow.isoformat() + "T11:00")
            page.get_by_role("button", name="创建草稿").click()
            expect(page).to_have_url(re.compile(r"#/personal/trips/[0-9a-f-]{36}$"))
            expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible()
            return page.url

        a = manual("上海", "项目甲")
        page.get_by_role("button", name="预检加入安排").click()
        confirm = page.get_by_role("button", name="确认加入安排")
        expect(confirm).to_be_visible()
        expect(page.get_by_role("region", name="原安排")).to_contain_text("未占用日历")
        expect(page.get_by_role("region", name="拟变更")).to_contain_text("项目甲会议")
        # Preview must not move the plan out of draft before this press.
        identifier = a.rsplit("/", 1)[-1]
        api = page.request.get(base + "/api/personal/trips/" + identifier).json()
        assert api["plan"]["lifecycle"] == "draft"
        confirm.click()
        expect(page.get_by_text("已安排", exact=True)).to_be_visible()
        with page.expect_download() as ready:
            page.get_by_role("button", name="导出确定时刻（ICS）").click()
        content = ready.value.path().read_text(encoding="utf-8")
        assert "UID:" in content and "项目甲会议" in content and "T020000Z" in content

        b = manual("杭州", "项目乙")
        page.get_by_role("button", name="预检加入安排").click()
        expect(page.get_by_text("确定冲突：")).to_be_visible()
        expect(page.get_by_role("button", name="确认加入安排")).to_have_count(0)
        page.get_by_role("checkbox", name="项目甲 · 第 1 版").check()
        page.get_by_role("button", name="按所选替换重新预检").click()
        page.get_by_role("button", name="确认替换指定旧行程").click()
        expect(page.get_by_text("已安排", exact=True)).to_be_visible()
        page.goto(a)
        expect(page.get_by_text("已被替换", exact=True)).to_be_visible()

        page.goto(b)
        page.get_by_role("link", name="手动调整").click()
        page.get_by_label("备注").fill("第二版新增说明")
        page.get_by_role("button", name="保存为新版本").click()
        expect(page.get_by_text("当前安排使用第 1 版", exact=False)).to_be_visible()
        expect(page.get_by_role("group", name="查看、草稿与安排版本")).to_contain_text("第 2 版")
        page.get_by_role("button", name="预检更新安排").click()
        expect(page.get_by_role("region", name="原安排")).to_contain_text("实际安排：第 1 版")
        expect(page.get_by_role("region", name="拟变更")).to_contain_text("用第 2 版草稿")
        page.keyboard.press("Escape")
        assert page.request.get(base + "/api/personal/trips/" + b.rsplit("/", 1)[-1]).json()["plan"]["scheduled_version"] == 1
        def expired_preview(route):
            response = route.fetch()
            payload = response.json()
            payload["expires_at"] = "2000-01-01T00:00:00+08:00"
            route.fulfill(response=response, json=payload)
        preview_url = "**/api/personal/trips/*/operations/preview"
        page.route(preview_url, expired_preview)
        page.get_by_role("button", name="预检更新安排").click()
        expect(page.get_by_role("button", name="确认更新已安排版本")).to_be_disabled()
        expect(page.get_by_text("本次预检已过有效期，不能确认。")).to_be_visible()
        page.keyboard.press("Escape")
        page.unroute(preview_url, expired_preview)
        page.get_by_role("link", name="查看已安排版本").click()
        version_status = page.get_by_role("group", name="查看、草稿与安排版本")
        expect(version_status).to_contain_text("日历正在使用这一版")
        expect(page.get_by_role("button", name="预检更新安排")).to_have_count(0)
        page.get_by_role("link", name="查看当前草稿").click()
        page.get_by_role("button", name="预检更新安排").click()
        page.get_by_role("button", name="确认更新已安排版本").click()
        expect(page.get_by_text("当前安排使用第 2 版", exact=True)).to_be_visible()
        expect(page.get_by_text("安排操作回执：第 2 版", exact=False)).to_be_visible()
        page.reload()
        expect(page.get_by_text("第二版新增说明", exact=True)).to_be_visible()
        page.get_by_role("link", name="交给助手调整").click()
        expect(page.get_by_text("将基于「项目乙」第 2 版调整。", exact=False)).to_be_visible()
        page.get_by_role("button", name="取消引用").click()
        box = page.get_by_role("textbox", name="输入消息")
        box.fill("明天从广州去上海出差，大后天下午回来，1人，预算3000元，会议地点是上海世博中心，会议时间后天10:00-12:00")
        page.get_by_role("button", name=re.compile(r"^(开始规划|发送消息)$")).click()
        saved = page.get_by_role("button", name="保存为草稿")
        expect(saved).to_be_visible(timeout=15_000)
        saved.click()
        page.get_by_role("link", name="已保存第 1 版草稿，前往查看").click()
        expect(page.get_by_role("heading", name="广州 → 上海差旅")).to_be_visible()
        plan_url = page.url
        page.get_by_role("button", name="收藏此版本").click()
        expect(page.get_by_role("button", name="已收藏行程")).to_be_visible()
        page.get_by_role("link", name="收藏", exact=True).click()
        expect(page.get_by_text("广州 → 上海差旅", exact=True)).to_be_visible()
        page.get_by_role("link", name="查看原版本").click()
        expect(page.get_by_role("heading", name="广州 → 上海差旅")).to_be_visible()
        page.get_by_role("link", name="偏好", exact=True).click()
        page.get_by_label("常用出发城市").fill("广州")
        page.get_by_label("允许用于规划").first.check()
        page.get_by_role("button", name="保存常用出发城市").click()
        expect(page.get_by_text("偏好设置已更新。")).to_be_visible()
        page.get_by_role("button", name="启用已授权的偏好").click()
        expect(page.get_by_text("当前：已启用")).to_be_visible()
        page.get_by_role("link", name="返回对话", exact=True).click()
        box.fill("记一笔地铁费30元")
        page.get_by_role("button", name=re.compile(r"^(开始规划|发送消息)$")).click()
        page.get_by_role("button", name="确认这项费用操作").click()
        expect(page.get_by_text("已记录", exact=False).first).to_be_visible()
        page.goto(base + "/#/personal/expenses")
        expect(page.get_by_role("heading", name="实际支出（原币种）")).to_be_visible()
        page.get_by_role("button", name="查看数据表").first.click()
        expect(page.get_by_role("table", name="CNY 原币统计数据")).to_contain_text("CNY 30.00")
        page.get_by_role("button", name="调整归属").click()
        page.get_by_label("费用归属", exact=True).select_option(label="广州 → 上海差旅")
        page.get_by_role("button", name="预览归属变更").click()
        expect(page.get_by_role("region", name="拟归属")).to_contain_text("广州 → 上海差旅")
        page.get_by_role("button", name="确认更新归属").click()
        expect(page.get_by_role("link", name="广州 → 上海差旅")).to_be_visible()
        page.goto(plan_url)
        expect(page.get_by_role("heading", name="实际支出")).to_be_visible()
        expect(page.locator("#personal-main").get_by_text("CNY 30.00", exact=True)).to_be_visible()
        page.screenshot(path=output / "personal-desktop.png", full_page=True)
        page.set_viewport_size({"width": 390, "height": 850})
        page.screenshot(path=output / "personal-mobile.png", full_page=True)
        assert page.locator("#personal-main").evaluate("(element) => element.scrollWidth <= element.clientWidth + 1")
        page.emulate_media(color_scheme="dark")
        page.get_by_role("link", name="费用", exact=True).click()
        expect(page.get_by_role("heading", name="差旅费用")).to_be_visible()
        assert page.locator("#personal-main").evaluate("(element) => element.scrollWidth <= element.clientWidth + 1")
        page.screenshot(path=output / "personal-mobile-expenses.png", full_page=True)
        assert not blocked
        persisted = {"id": plan_url.rsplit("/", 1)[-1],
                     "cookies": {row["name"]: row["value"] for row in page.context.cookies()}}
        browser.close()
    print("BROWSER 个人中心：草稿、确认、替换、历史版本、会话保存、偏好、收藏、费用和窄屏通过", flush=True)
    return persisted


def _check_conversation_browser(base, output, chromium_exe=None):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=chromium_exe, args=["--disable-background-networking"])
        client = browser.new_context(viewport={"width": 1366, "height": 860})
        page = client.new_page()
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.route("**/*", lambda route: route.continue_() if urlsplit(route.request.url).hostname == "127.0.0.1" else route.abort())
        page.goto(base, wait_until="networkidle")
        history = page.get_by_role("navigation", name="聊天记录")
        log = page.get_by_role("log", name="对话消息")
        assistant = log.locator('[data-message-role="assistant"]')
        editor = page.get_by_role("textbox", name="输入消息")
        send = page.get_by_role("button", name=re.compile(r"^(开始规划|发送消息)$"))
        new_chat = page.get_by_role("button", name="新对话", exact=True)
        a_title = "查去北京的火车票，我想少换乘"
        b_title = "查去杭州的火车票"

        def ask(text, response):
            editor.fill(text)
            send.click()
            expect(assistant.last).to_contain_text(response, timeout=12000)
            expect(send).to_be_visible()

        def session():
            return page.evaluate("localStorage.getItem('aligo_session_id')")

        ask(a_title, "出发")
        a_id = session()
        expect(history.get_by_text(a_title, exact=True)).to_be_visible()
        new_chat.click()
        expect(page.get_by_text("删除当前对话？")).to_have_count(0)
        expect(log.get_by_text(a_title, exact=True)).to_have_count(0)
        expect(editor).to_be_enabled()
        assert (b_id := session()) != a_id
        expect(history.get_by_text(a_title, exact=True)).to_be_visible()

        ask(b_title, "出发")
        expect(history.get_by_text(b_title, exact=True)).to_be_visible()
        ask("记一笔地铁费30元", "账本未修改")
        page.get_by_role("button", name="确认这项费用操作").click()
        expect(assistant.last).to_contain_text("已记录")
        expect(send).to_be_visible()

        search = history.get_by_role("searchbox", name="搜索聊天记录")
        search.fill("北京")
        expect(history.get_by_text(a_title, exact=True)).to_be_visible()
        expect(history.get_by_text(b_title, exact=True)).to_have_count(0)
        history.get_by_text(a_title, exact=True).click()
        expect(log.get_by_text(a_title, exact=True)).to_be_visible()
        expect(assistant.last).to_contain_text("出发")
        expect(log.get_by_text(b_title, exact=True)).to_have_count(0)
        assert session() == a_id
        ask("上海", "哪天")
        ask("明天", "G102")
        expect(assistant.last).to_contain_text("上海 → 北京")
        search.clear()

        page.reload(wait_until="networkidle")
        expect(log.get_by_text(a_title, exact=True)).to_be_visible()
        expect(assistant.last).to_contain_text("G102")
        assert session() == a_id
        for key in (a_id, b_id):
            entries = client.request.get(base + "/api/expenses", params={"session_id": key}).json()["expenses"]
            assert len(entries) == 1 and float(entries[0]["amount"]) == 30

        page.route("**/api/session/new", lambda route: route.fulfill(status=503, json={"detail": "fixture"}))
        new_chat.click()
        expect(page.get_by_text("暂时无法新建对话，当前对话未变更。")).to_be_visible()
        expect(log.get_by_text(a_title, exact=True)).to_be_visible()
        assert session() == a_id
        page.unroute("**/api/session/new")

        # The current user turn is persisted even when switching interrupts tools.
        editor.fill("北京明天的天气怎么样？")
        send.click()
        page.get_by_role("button", name="停止生成").last.wait_for()
        page.wait_for_function("""async (id) => {
            const res = await fetch('/api/conversations/' + id + '/messages');
            return res.ok && (await res.json()).messages.some((row) => row.content === '北京明天的天气怎么样？');
        }""", arg=a_id)
        history.get_by_text(b_title, exact=True).click()
        expect(log.get_by_text(b_title, exact=True)).to_be_visible()
        expect(log.get_by_text(a_title, exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="确认这项费用操作")).to_have_count(0)

        page.screenshot(path=output / "conversation-desktop.png")
        page.set_viewport_size({"width": 320, "height": 800})
        page.emulate_media(color_scheme="dark")
        page.get_by_role("button", name="展开聊天记录").click()
        drawer = page.get_by_role("dialog", name="聊天记录")
        expect(drawer).to_be_visible()
        expect(drawer.get_by_text(a_title, exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.screenshot(path=output / "conversation-mobile.png")
        page.keyboard.press("Escape")
        expect(drawer).to_have_count(0)
        page.get_by_role("button", name="展开聊天记录").click()
        expect(drawer).to_be_visible()
        drawer.get_by_text(a_title, exact=True).click()
        expect(drawer).to_have_count(0)
        expect(log.get_by_text(a_title, exact=True)).to_be_visible()

        stranger = browser.new_context()
        assert stranger.request.post(base + "/api/identity").ok
        assert stranger.request.get(base + f"/api/conversations/{a_id}/messages").status == 404
        assert not stranger.request.get(base + "/api/conversations").json()["items"]
        assert not errors, errors
        cookies = {cookie["name"]: cookie["value"] for cookie in client.cookies()}
        browser.close()

    print("BROWSER 聊天记录：加号不删、搜索、切换续聊、刷新还原、账本共享、用户隔离和窄屏通过", flush=True)
    return a_id, b_id, cookies


def run(assets, output, chromium_exe=None, personal=False, conversations=False):
    import httpx

    output.mkdir(parents=True, exist_ok=True)
    mirror = output / "app"
    assert not mirror.exists(), "Use a new working directory per run"
    mirror.mkdir()
    scopes = (".claude/skills", "agents", "cache", "context", "db", "rag_core", "server", "utils", "tests")
    for scope in scopes:
        shutil.copytree(REPO / scope, mirror / scope, ignore=shutil.ignore_patterns("__pycache__", ".env", ".pytest_cache"))
    for name in ("config.py", "config_agentscope.py", "pytest.ini"):
        shutil.copy2(REPO / name, mirror / name)
    shutil.copytree(assets, mirror / "web/dist")
    ports = [_port(), _port()]
    fixture, app = [f"http://127.0.0.1:{n}" for n in ports]
    prefixes = ("ALIGO_", "NEOHOUSE_", "MIMO_", "NARRATION_", "AMAP_", "DATABASE_", "REDIS_")
    configured = {k: v for k, v in os.environ.items() if not k.startswith(prefixes)}
    configured.update(PYTHON_DOTENV_DISABLED="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
        PYTHONPATH=str(mirror), ALIGO_SESSION_SECRET=secrets.token_hex(32), ALIGO_LLM_PROBE_ON_STARTUP="0",
        ALIGO_MODEL_NAME="fixture-primary", ALIGO_ITINERARY_MODEL_NAME="fixture-legacy",
        ALIGO_BASE_URL=fixture + "/model", ALIGO_API_KEY="model-test-fixture",
        AMAP_API_KEY="map-test-fixture", MIMO_BASE_URL=fixture + "/v1", MIMO_API_KEY="audio-test-fixture",
        NARRATION_BASE_URL=fixture + "/v1", NARRATION_API_KEY="narration-test-fixture",
        ALIGO_TEST_BASE_URL=app, ALIGO_AUDIO_BASE_URL=app)
    if personal:
        configured["ALIGO_PERSONAL_CENTER_ENABLED"] = "1"

    def stop(child):
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(5)

    with ExitStack() as stack:
        def launch(name, port, health, log_name=None):
            handle = stack.enter_context((output / ((log_name or name) + ".log")).open("w", encoding="utf-8"))
            child = subprocess.Popen([sys.executable, str(mirror / "tests/run_isolated_browser_audit.py"),
                                      "--serve", name, "--port", str(port), "--fixture-url", fixture],
                                     cwd=mirror, env=configured, stdout=handle, stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            stack.callback(stop, child)
            for _ in range(100):
                if child.poll() is not None:
                    raise RuntimeError(f"{name} exited; see {output}")
                try:
                    if httpx.get(health, timeout=0.4, trust_env=False).is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError(f"{name} did not start; see {output}")
            return child

        launch("fixture", ports[0], fixture + "/health")
        running_app = launch("app", ports[1], app + "/api/health")
        with httpx.Client(base_url=app, trust_env=False) as caller:
            home = caller.get("/")
            assert home.is_success and "no-store" in home.headers["cache-control"]
            asset = re.search(r'/assets/index-[\w-]+\.js', home.text)
            assert asset, "The built home must reference a versioned entry."
            compressed = caller.get(asset[0], headers={"Accept-Encoding": "gzip"})
            plain = caller.get(asset[0], headers={"Accept-Encoding": "identity"})
            assert compressed.is_success and plain.is_success
            assert compressed.headers.get("content-encoding") == "gzip"
            assert "content-encoding" not in plain.headers and plain.content == compressed.content
            print("BROWSER 应用提供压缩入口，且不缓存旧的首页入口", flush=True)
        if conversations:
            a_id, b_id, cookies = _check_conversation_browser(app, output, chromium_exe)
            stop(running_app)
            launch("app", ports[1], app + "/api/health", "app-restart")
            with httpx.Client(base_url=app, cookies=cookies, trust_env=False) as caller:
                results = caller.get("/api/conversations").json()["items"]
                assert {item["id"] for item in results} == {a_id, b_id}
                a = caller.get(f"/api/conversations/{a_id}/messages").json()
                assert "G102" in json.dumps(a)
                b = caller.get(f"/api/conversations/{b_id}/messages").json()
                assert "确认费用操作" in [row["content"] for row in b["messages"]]
            print("BROWSER 服务重启后仍可读取两条会话、结果卡片和脱敏后的费用确认", flush=True)
        elif personal:
            persisted = _check_personal_browser(app, fixture, output, chromium_exe)
            stop(running_app)
            launch("app", ports[1], app + "/api/health", "app-restart")
            with httpx.Client(base_url=app, cookies=persisted["cookies"], trust_env=False) as caller:
                assert caller.post("/api/session/new", json={}).status_code == 200
                detail = caller.get(f"/api/personal/trips/{persisted['id']}")
                assert detail.status_code == 200
                assert detail.json()["draft"]["snapshot"]["title"] == "广州 → 上海差旅"
                expense = caller.get("/api/personal/expenses/summary", params={"plan_id": persisted["id"]}).json()
                assert expense["totals_by_currency"] == {"CNY": "30.00"}
            print("BROWSER 本地服务重启并新建会话后，仍可读取原草稿与已关联账本", flush=True)
        else:
            subprocess.run([sys.executable, "-m", "pytest", "tests/test_web_contracts.py", "-q", "-rs", "-p", "no:cacheprovider"],
                           cwd=mirror, env=configured, check=True)
            _check_browser(app, fixture, output, chromium_exe)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--serve", choices=("fixture", "app"))
    parser.add_argument("--port", type=int)
    parser.add_argument("--fixture-url")
    parser.add_argument("--chromium-exe", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--personal", action="store_true", help="只运行个人中心工作流")
    modes.add_argument("--conversations", action="store_true", help="只运行新建、查找和恢复聊天记录工作流")
    args = parser.parse_args()
    if args.serve:
        _serve(args.serve, args.port, args.fixture_url)
    else:
        run(args.assets.resolve(), args.output.resolve(), args.chromium_exe, args.personal, args.conversations)
