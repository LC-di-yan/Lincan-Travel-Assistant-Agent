"""Replay one controlled public event stream against the production web bundle."""
import argparse
from collections import Counter
import json
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from playwright.sync_api import expect, sync_playwright

from run_flightdeck_visual_audit import assert_no_overflow, guarded_page, preview, save_recording


def node(key, agent, label, *parents):
    return {"node_id": key, "agent_name": agent, "label": label, "depends_on": list(parents)}


OUT = node("outbound", "train_ticket", "去程交通")
BACK = node("inbound", "train_ticket", "返程交通")
HOTEL = node("hotels", "hotel_search", "住宿候选")
WEATHER = node("weather", "information_query", "目的地天气")
WALK = node("commute", "trip_commute", "会场通勤", "hotels")
PLAN = node("proposal", "itinerary_planning", "时间与预算", "outbound", "inbound", "hotels", "commute")
SCHEDULE = [OUT, BACK, HOTEL, WEATHER, WALK, PLAN]


def result(n, status, answer, **extra):
    return {**n, "status": "success" if status in {"partial", "success"} else "error", "node_status": status,
            "data": {"answer": answer}, **extra}


def scenario(browser, assets, output, mode, record=False):
    arrived, finish = Event(), Event()
    early = result(OUT, "partial", "去程只核对到部分班次。")
    early["data"]["results"] = {"from":"北京南","to":"上海虹桥","summary":early["data"]["answer"]}
    back = result(BACK, "success", "使用已核验的返程班次。", cached=True)
    back["data"]["results"] = {"from":"上海虹桥","to":"北京南","summary":back["data"]["answer"]}
    def stream(emit, payload):
        if payload["message"] == "下一轮":
            return emit("complete", {"results": [{"agent_name":"memory_query", "status":"success",
                        "data":{"answer":"这是新回合。"}}], "status":"completed"})
        emit("intention", {"intents":[], "key_entities":{}, "trip_request":{"origin":"北京"}, "agent_schedule":SCHEDULE,
                           "reasoning":"PRIVATE_TEST_REASON", "rewritten_query":"PRIVATE_TEST_REASON"})
        emit("dispatching", {"agents":SCHEDULE})
        for n in [OUT, HOTEL, WEATHER]:
            emit("agent_start", n)
        emit("agent_result", early)
        emit("agent_result", back)  # before any start event for the return leg
        if not arrived.wait(45):
            return
        emit("agent_result", {**result(HOTEL, "success", "住宿候选已核对。"),
              "data":{"results":{"city":"上海","count":1,"summary":"已返回一处住宿候选，价格仍需核实。",
                                 "hotels":[{"name":"会场附近的示例酒店","address":"上海"}]}}})
        emit("agent_start", WALK)
        if not finish.wait(45):
            return
        emit("agent_result", result(WALK, "timeout", "通勤查询超时。"))
        emit("agent_start", PLAN)
        emit("agent_result", result(WEATHER, "unavailable", "暂无可核验天气。"))
        emit("agent_result", result(PLAN, "partial", "尚缺通勤证据，暂不能确认完整费用。"))
        # Abbreviated/reordered snapshot; previously visible evidence must survive.
        final = {"results":[{**back, "data":{"answer":"返程复核完毕。"}}, early], "status":"partial_failure"}
        emit("complete", final)
        emit("agent_result", result(WEATHER, "success", "LATE_AFTER_TERMINAL"))
        emit("complete", final)

    def history(path):
        if path.startswith("/api/conversations/") and path.endswith("/messages"):
            return {"id":"audit-2", "readonly":False, "next_before":None, "messages":[
                {"id":"1","role":"user","content":"历史差旅","timestamp":None},
                {"id":"2","role":"assistant","content":"当时未收齐结果。","timestamp":None,
                 "status":"interrupted","results":[early, back]}]}

    with preview(assets, chat_script=stream, get_fixture=history) as (base, posted, _), TemporaryDirectory() as clips:
        mobile = mode == "mobile"
        ctx = browser.new_context(viewport={"width":390 if mobile else 1366,"height":844 if mobile else 850},
                                  has_touch=mobile,is_mobile=mobile,device_scale_factor=1,
                                  record_video_dir=clips if record else None, record_video_size={"width":1366,"height":850} if record else None,
                                  color_scheme="dark" if mobile else "light", reduced_motion="reduce" if mobile else "no-preference")
        ctx.add_init_script("""localStorage.setItem('aligo-tts-prefs-v3',JSON.stringify({autoPlay:true,personaId:'fixture'}))""")
        errors = []
        page = guarded_page(ctx, errors)
        page.goto(base, wait_until="networkidle")
        editor = page.get_by_role("textbox", name="输入消息")
        editor.fill("周三从北京去上海出差三天，请核对往返交通、酒店和到会场的通勤。")
        page.get_by_role("button", name="开始规划").click()
        strip = page.get_by_role("region",name="处理进度")
        expect(strip).to_contain_text("已返回 2 项")
        if not mobile:
            page.get_by_role("button",name="收起聊天记录").click()
        if mode == "list":
            strip.get_by_role("button",name="查看文字清单").click()
        if mobile:
            expect(strip.locator("svg.task-map")).to_have_count(0)
            strip.scroll_into_view_if_needed()
            page.screenshot(path=output / "mobile-summary.png")
            strip.get_by_role("button", name="展开详情").click()
        if mode == "graph":
            expect(strip.locator(".task-map .map-station")).to_have_count(6)
            expect(strip.locator(".task-wire")).to_have_count(5)
        else:
            expect(strip.locator(".task-map")).to_have_count(0)
        rows = strip.locator(".activity-nodes li")
        expected = ["去程交通部分完成","返程交通已复用","住宿候选进行中","目的地天气进行中","会场通勤待开始","时间与预算待开始"]
        expect(rows).to_have_text(expected)
        expect(strip.get_by_label("任务依赖")).to_contain_text("会场通勤依赖：住宿候选")
        page.get_by_role("button",name="展开行程档案").click()
        expect(page.locator(".activity-detail .activity-nodes li")).to_have_text(expected)
        if mobile:
            page.keyboard.press("Escape")
        strip.scroll_into_view_if_needed()
        if mobile or mode == "graph":
            page.screenshot(path=output / (mode+"-working.png"))
        evidence = page.locator("[data-result-stack] > div.space-y-3 > div")
        expect(evidence).to_have_count(2)
        first = evidence.first.element_handle()
        receipt = strip.element_handle()
        if mode == "graph":
            page.evaluate("""window.__handoffs=[];document.addEventListener('animationstart',e=>{
              if(e.animationName==='route-handoff')window.__handoffs.push(e.target.dataset.from+'>'+e.target.dataset.to)})""")
        if record:
            page.wait_for_timeout(900)  # Viewer pacing only; not event timing in the application.
        arrived.set()
        expect(rows.nth(4)).to_have_text("会场通勤进行中")
        if mode == "graph":
            page.wait_for_function("window.__handoffs.includes('hotels>commute')")
            assert page.evaluate("window.__handoffs.filter(v=>v==='hotels>commute').length") == 1
        if record:
            page.wait_for_timeout(950)
        strip.scroll_into_view_if_needed()
        before_top = strip.bounding_box()["y"]
        finish.set()
        done = page.get_by_role("region", name="协作回执")
        expect(done).to_contain_text("本轮结束，有待核验项")
        expect(done).to_contain_text("已返回 6 项")
        expect(done.locator(".activity-nodes li")).to_have_text([
            "去程交通部分完成","返程交通已复用","住宿候选已完成","目的地天气无可核验数据","会场通勤超时","时间与预算部分完成"])
        expect(evidence).to_have_count(6)
        assert abs(done.bounding_box()["y"] - before_top) < 12, (mode, before_top, done.bounding_box())
        assert first.evaluate("e=>e.isConnected") and receipt.evaluate("e=>e.isConnected")
        body = page.locator("body").inner_text()
        assert "LATE_AFTER_TERMINAL" not in body and "PRIVATE_TEST_REASON" not in body
        expect(evidence.nth(1)).to_contain_text("返程复核完毕")
        done.scroll_into_view_if_needed()
        if mode == "graph":
            page.screenshot(path=output/"terminal.png")
        page.wait_for_function("performance.getEntriesByType('resource').some(e=>e.name.endsWith('/api/tts'))")
        calls = Counter(path for path,_ in posted if path in {"/api/chat","/api/narrate","/api/tts","/api/narrate/progress"})
        assert calls == {"/api/chat":1,"/api/narrate":1,"/api/tts":1}, calls
        bodies = [(path,{k:v for k,v in body.items() if k!="request_id"}) for path,body in posted if path in calls]
        signature = hashlib.sha256(json.dumps(bodies,sort_keys=True).encode()).hexdigest()
        # Narration in this fixture has no valid stream; the request must contain the actual fallback text.
        spoken = next(body for path, body in posted if path == "/api/tts")
        assert "返程" in spoken["text"] and "PRIVATE_TEST_REASON" not in spoken["text"]
        if record:
            page.wait_for_timeout(950)
        editor.fill("下一轮")
        editor.press("Enter")
        expect(page.locator("[data-message-role=assistant]").last).to_contain_text("这是新回合。")
        expect(page.locator(".activity-strip").first).to_contain_text("已返回 6 项")
        expect(page.locator(".activity-strip").last).to_contain_text("已返回 1 项")
        expect(page.locator(".activity-strip").last.locator(".task-map")).to_have_count(0)
        page.wait_for_function("performance.getEntriesByType('resource').filter(e=>e.name.endsWith('/api/tts')).length===2")
        counts_before = sum(p=="/api/tts" for p,_ in posted)
        page.reload(wait_until="networkidle")
        saved = page.get_by_role("region",name="协作回执")
        expect(saved).to_contain_text("历史回合未完整结束")
        saved.get_by_role("button",name="展开详情").click()
        expect(saved.locator(".activity-nodes li")).to_have_text(["去程交通部分完成","返程交通已复用"])
        expect(saved.locator(".task-map")).to_have_count(0)
        assert saved.evaluate("e=>getComputedStyle(e).animationName") == "none"
        assert sum(p=="/api/tts" for p,_ in posted) == counts_before
        if mobile:
            page.set_viewport_size({"width":320,"height":650})
            expect(saved.get_by_role("button",name="收起详情")).to_be_visible()
            assert saved.evaluate("e=>e.scrollWidth <= e.clientWidth+1")
        assert_no_overflow(page)
        assert not errors, errors
        clip = page.video
        ctx.close()
        if record:
            save_recording(clip, output / "activity-replay")
        return {"业务请求次数":dict(calls), "业务请求内容校验":signature}


def verify_selection(browser, assets):
    confirm = Event()
    def stream(emit, body):
        if body["message"] == "选择方案2":
            if confirm.wait(20):
                emit("complete", {"status":"completed", "results":[], "selected_proposal":"opt-B"})
            return
        plan={"request":{"origin":"北京","destination":"上海"},"alternatives":[
            {"id":"opt-A","status":"validated"},{"id":"opt-B","status":"validated"}]}
        emit("complete", {"status":"completed","trip_plan":plan,"candidate_ref":"fixture-ref",
             "candidate_session_id":body["session_id"],"results":[{"agent_name":"itinerary_planning","status":"success",
             "data":{"answer":"有两份可供核对的方案。","trip_plan":plan}}]})
    def caps(path):
        return {"enabled":True, "csrf_token":"local-test-only"} if path == "/api/personal/capabilities" else None
    with preview(assets,chat_script=stream,get_fixture=caps) as (base,_,_):
        errors, writes = [], []
        ctx=browser.new_context(viewport={"width":1280,"height":800})
        page=guarded_page(ctx,errors)
        def save(route):
            writes.append(route.request.post_data_json)
            route.fulfill(json={"plan_id":"fixture-plan","version":1})
        page.route("**/api/personal/trips",save)
        page.goto(base,wait_until="networkidle")
        page.get_by_role("textbox",name="输入消息").fill("准备两份候选")
        page.get_by_role("button",name="开始规划").click()
        default=page.get_by_label("保存时采用")
        expect(default).to_have_value("")
        page.get_by_role("button",name="预览方案 B").click()
        page.get_by_role("button",name="选择方案 2").click()
        expect(page.get_by_role("button",name="停止生成")).to_be_visible()
        expect(default).to_have_value("")
        confirm.set()
        expect(page.get_by_role("region",name="协作回执").last).to_contain_text("已确认选择方案 2，未执行预订")
        expect(default).to_have_value("opt-B")
        assert not writes
        page.get_by_role("button",name="保存为草稿").click()
        expect(page.get_by_role("link",name="已保存第 1 版草稿，前往查看")).to_be_visible()
        assert len(writes)==1 and writes[0]["option_id"]=="opt-B" and writes[0]["candidate_ref"]=="fixture-ref"
        assert not errors
        ctx.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--chromium-exe",type=Path)
    parser.add_argument("--record",action="store_true")
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as driver:
        browser=driver.chromium.launch(executable_path=args.chromium_exe,args=["--disable-background-networking"])
        report={m:scenario(browser,args.assets.resolve(),args.output,m,args.record and m=="graph") for m in ("graph","list","mobile")}
        assert report["graph"] == report["list"] == report["mobile"]
        verify_selection(browser,args.assets.resolve())
        report["选择与保存"]="确认前不标记；确认后默认采用该候选；仅主动保存才写入"
        report["浏览器"]=browser.version
        browser.close()
    (args.output/"replay.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),"utf-8")
    print("协作图、文字清单、手机与历史回执通过")


if __name__ == "__main__":
    main()
