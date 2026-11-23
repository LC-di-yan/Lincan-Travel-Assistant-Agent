"""Capture the built flight deck with loopback-only, synthetic responses (no accounts or model calls)."""

import argparse
from contextlib import contextmanager
from functools import partial
import gzip
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import time
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from threading import Event, Thread
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


SCHEDULE = [
    {"node_id": "outbound", "agent_name": "train_ticket", "label": "去程交通", "expected_output": "NON_PUBLIC_FIXTURE"},
    {"node_id": "inbound", "agent_name": "train_ticket", "label": "返程交通"},
    {"node_id": "hotels", "agent_name": "hotel_search", "label": "住宿候选"},
    {"node_id": "commute", "agent_name": "trip_commute", "label": "会场通勤", "depends_on": ["hotels"]},
]


@contextmanager
def preview(assets, *, chat_script=None, get_fixture=None, get_asset=None, identity_release=None):
    posted = []
    release = Event()

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, body):
            wire = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(wire)))
            self.end_headers()
            self.wfile.write(wire)

        def do_GET(self):
            path = urlsplit(self.path).path
            if get_asset is not None and path.startswith("/assets/"):
                status, headers, body = get_asset(path, self.headers.get("Accept-Encoding", "identity"))
                self.send_response(status)
                for name, value in headers:
                    if name.lower() not in {"content-length", "connection", "transfer-encoding"}:
                        self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not path.startswith("/api/"):
                return super().do_GET()
            fixtures = {
                "/api/conversations": {"items": [], "next_before": None},
                "/api/personal/capabilities": {"enabled": True},
                "/api/personal/overview": {"today": "2026-11-21", "counts": {"draft": 0, "scheduled": 0},
                    "upcoming": [], "recent_drafts": [], "frequent_destinations": []},
                "/api/personal/expenses/summary": {"items": [], "totals_by_currency": {}, "count": 0},
                "/api/plugins": {"plugins": []}, "/api/tts/personas": {"personas": []},
            }
            override = get_fixture(path) if get_fixture else None
            return self.reply(fixtures.get(path, {}) if override is None else override)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            posted.append((self.path, payload))
            if self.path == "/api/identity":
                if identity_release is not None:
                    identity_release.wait(20)
                return self.reply({"user_id": "flightdeck-fixture"})
            if self.path == "/api/session/new":
                return self.reply({"user_id": "flightdeck-fixture", "session_id": "audit-" + str(len(posted))})
            if self.path != "/api/chat":
                return self.reply({})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.end_headers()

            def emit(event, data):
                self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()

            try:
                if chat_script is not None:
                    return chat_script(emit, payload)
                if payload.get("message") == "快路径：只问日期":
                    return emit("clarification", {"question": "你准备哪天出发？"})
                if payload.get("message") == "中断演练":
                    emit("thinking", {"status": "analyzing_intent"})
                    return
                # Delay only the fixture: the local acknowledgement must precede any server facts.
                time.sleep(.40)
                emit("thinking", {"status": "analyzing_intent"})
                emit("intention", {"reasoning": "NON_PUBLIC_FIXTURE", "rewritten_query": "NON_PUBLIC_FIXTURE", "intents": [], "key_entities": {},
                                    "agent_schedule": SCHEDULE, "trip_request": {}})
                emit("dispatching", {"agents": SCHEDULE})
                for node in SCHEDULE[:3]:
                    emit("agent_start", node)
                results = [{**SCHEDULE[0], "node_status": "partial", "status": "success", "data": {"results": {"from": "北京南", "to": "上海虹桥", "summary": "只核对到部分班次，余票和价格仍待确认。"}}},
                           {**SCHEDULE[1], "node_status": "success", "cached": True, "status": "success",
                            "data": {"results": {"from": "上海虹桥", "to": "北京南", "summary": "沿用本次查询已有的返程信息。"}}}]
                time.sleep(.25)
                for result in results:
                    emit("agent_result", result)
                if release.wait(45):
                    emit("complete", {"status": "partial_failure", "agents_executed": 3, "results": results})
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                pass

    with ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(assets))) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", posted, release
        finally:
            release.set()
            if identity_release is not None:
                identity_release.set()
            server.shutdown()
            worker.join()


def capture(browser, base, assets, output, name, width, height, scheme):
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme,
                              is_mobile=width < 600, has_touch=width < 600, device_scale_factor=1)
    page = ctx.new_page()
    requested = []
    def local_only(route):
        assert urlsplit(route.request.url).hostname == "127.0.0.1"
        requested.append((route.request.method, urlsplit(route.request.url).path))
        route.continue_()
    page.route("**/*", local_only)
    page.goto(base, wait_until="networkidle")
    expect(page.get_by_role("textbox", name="输入消息")).to_be_visible()
    page.screenshot(path=output / f"{name}.png")
    paths = {path for _, path in requested}
    sizes = {suffix: sum(len(gzip.compress((assets / path[1:]).read_bytes(), compresslevel=6, mtime=0))
                         for path in paths if path.endswith(suffix)) for suffix in (".js", ".css")}
    entry_path = next(path for path in paths if Path(path).name.startswith("index-") and path.endswith(".js"))
    entry_bytes = len(gzip.compress((assets / entry_path[1:]).read_bytes(), compresslevel=6, mtime=0))
    colors = contrast(page) if page.locator(".brief-mode").count() else {}
    ctx.close()
    return {"contrast": colors, "entry_js_gzip_bytes": entry_bytes, "viewport": [width, height], "theme": scheme, "requests": requested, "gzip_bytes": sizes}


def contrast(page):
    """Read the rendered colors, including placeholder ink and both primary-action colors."""
    values = page.evaluate("""() => {
      const css = (selector, prop, pseudo=null) => getComputedStyle(document.querySelector(selector), pseudo)[prop];
      const surface = css('body','backgroundColor'), paper = css('.flight-composer','backgroundColor');
      const pairs = {
        '正文':[css('.brief-description','color'),surface],
        '次级说明':[css('.example-tile small','color'),css('.example-tile','backgroundColor')],
        '输入占位':[css('textarea','color','::placeholder'),paper],
        '主要操作':[css('.deck-action','color'),css('.deck-action','backgroundColor')],
        '地图地名':[css('.plate-map-label','fill'),css('.plate-map-label','stroke')],
        '输入边界':[css('.flight-composer','borderColor'),paper],
      };
      const swatch = document.createElement('span'); swatch.style.color='var(--focus)';
      document.body.append(swatch); pairs['焦点环']=[getComputedStyle(swatch).color,paper];
      for(const [name,fg,bg] of [['协作标签','--route','--route-tint'],['警示','--warn','--warning-light'],['错误','--err','--error-light']]){
        swatch.style.color='var('+fg+')';swatch.style.backgroundColor='var('+bg+')';
        pairs[name]=[getComputedStyle(swatch).color,getComputedStyle(swatch).backgroundColor];
      }
      swatch.remove();
      function lum(value) {
        const rgb = value.match(/[.\\d]+/g).slice(0,3).map(v => {let n=Number(v)/255;return n<=.04045?n/12.92:((n+.055)/1.055)**2.4});
        return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
      }
      return Object.fromEntries(Object.entries(pairs).map(([k,p])=>{
        const a=lum(p[0]),b=lum(p[1]);return [k,(Math.max(a,b)+.05)/(Math.min(a,b)+.05)];
      }));
    }""")
    for name, value in values.items():
        assert value >= (3 if name in {"输入边界", "焦点环"} else 4.5), (name, value)
    return {key: round(value, 2) for key, value in values.items()}


def assert_no_overflow(page):
    dimensions = page.evaluate("""() => [document.documentElement, ...document.querySelectorAll('.flight-shell,.brief-mode,.composer-tools')]
        .filter(e=>e.getClientRects().length).map(e=>[e.tagName,e.className,e.scrollWidth,e.clientWidth])""")
    assert all(row[2] <= row[3] + 1 for row in dimensions), dimensions


def guarded_page(ctx, errors):
    page = ctx.new_page()
    page.set_default_timeout(6500)
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route("**/*", lambda r: r.continue_() if urlsplit(r.request.url).hostname == "127.0.0.1" else r.abort())
    return page


def verify_interaction(browser, assets, output, mobile):
    with preview(assets) as (base, posted, release):
        errors = []
        ctx = browser.new_context(viewport={"width": 390 if mobile else 1280, "height": 844 if mobile else 720},
                                  has_touch=mobile, is_mobile=mobile, device_scale_factor=1,
                                  color_scheme="dark" if mobile else "light", reduced_motion="reduce" if mobile else "no-preference")
        # A synthetic recognition adapter, never a live microphone.
        ctx.add_init_script("""window.__recordings=0;window.SpeechRecognition=class{
          constructor(){window.__mic=this} start(){window.__recordings++} stop(){this.onend?.()}
        }""")
        page = guarded_page(ctx, errors)
        page.goto(base, wait_until="networkidle")
        button = lambda name: page.get_by_role("button", name=name, exact=True)
        editor = page.get_by_role("textbox", name="输入消息")
        original = editor.element_handle()
        chat_posts = lambda: [body for path, body in posted if path == "/api/chat"]
        changes = lambda: [path for path, _ in posted if path not in {"/api/identity", "/api/session/new"}]
        expect(page.get_by_role("navigation", name="聊天记录")).to_have_count(0)
        expect(page.locator("#trip-archive")).to_have_count(0)
        button("开始规划").click()
        expect(editor).to_be_focused()
        expect(editor).to_have_attribute("aria-invalid", "true")
        expect(page.get_by_text("先写下差旅需求，或从下方选一个示例。")).to_be_visible()
        editor.fill("已有但未提交的草稿")
        page.get_by_role("button", name=re.compile("^记一笔费用")).click()
        expect(editor).to_have_value("记一笔打车费 50 元。")
        button("撤销替换").click()
        expect(editor).to_have_value("已有但未提交的草稿")
        button("更多示例").click()
        expect(page.get_by_role("button", name=re.compile("^换算汇率"))).to_be_visible()
        button("收起").click()
        editor.evaluate("""e=>{e.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
          e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,keyCode:229,bubbles:true,cancelable:true}));
          e.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));
          e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',repeat:true,bubbles:true,cancelable:true}));}""")
        editor.press("End")
        editor.press("Shift+Enter")
        expect(editor).to_have_value("已有但未提交的草稿\n")
        expect(button("开始规划")).to_be_visible()
        assert not changes(), changes()
        ctx.set_offline(True)
        expect(button("开始规划")).to_be_disabled()
        expect(page.get_by_text("当前离线，联网后可手动发送。")).to_be_visible()
        editor.press("Enter")
        ctx.set_offline(False)
        expect(button("开始规划")).to_be_enabled()
        assert not changes()
        assert page.evaluate("window.__recordings") == 0
        button("语音输入").click()
        expect(button("停止语音输入")).to_have_attribute("aria-pressed", "true")
        page.evaluate("""window.__mic.onresult({resultIndex:0,results:[{0:{transcript:'语音草稿'},isFinal:true}]})""")
        button("停止语音输入").click()
        expect(editor).to_have_value(re.compile("语音草稿$"))
        assert not changes()
        button("语音输入").click()
        page.evaluate("window.__mic.onerror({error:'not-allowed'})")
        expect(page.get_by_text("未获得麦克风权限。", exact=False)).to_be_visible()
        expect(editor).to_have_value(re.compile("语音草稿$"))
        for name in ["行程档案", "聊天记录"]:
            opener = button("展开" + name)
            opener.click()
            if mobile:
                modal = page.get_by_role("dialog", name=name)
                expect(modal).to_be_visible()
                assert modal.evaluate("e=>e.contains(document.activeElement) && e.matches(':modal')")
                if name == "行程档案":
                    page.keyboard.press("Escape")
                else:
                    page.mouse.click(385, 150)
                expect(modal).to_have_count(0)
                expect(opener).to_be_focused()
            else:
                expect(page.get_by_role("dialog")).to_have_count(0)
                button("收起" + name).click()
        if mobile:
            expect(page.locator("html")).to_have_attribute("data-motion", "reduced")
            settings = button("显示与语音设置")
            settings.click()
            page.get_by_role("combobox", name="动态效果").select_option("static")
            expect(page.locator("html")).to_have_attribute("data-motion", "static")
            button("关闭设置").click()
            expect(settings).to_be_focused()
            assert page.evaluate("localStorage.getItem('aligo-motion')") == "static"
        page.get_by_role("link", name="个人中心", exact=True).click()
        expect(page.get_by_role("heading", name="个人中心", exact=True)).to_be_visible()
        expect(editor).to_have_count(0)
        page.get_by_role("link", name="返回对话", exact=True).click()
        expect(editor).to_have_value(re.compile("语音草稿$"))
        assert original.evaluate("e=>e.isConnected")

        page.get_by_role("button", name=re.compile("^规划行程")).click()
        prompt = editor.input_value()
        assert not changes()
        cta = button("开始规划")
        bounds = cta.bounding_box()
        assert bounds["height"] >= 44 and bounds["width"] >= 44, bounds
        # Inspect the first rendered frame rather than waiting on an animation or network reply.
        page.evaluate("""() => {window.__ack = new Promise(resolve=>document.addEventListener('submit',()=>{
          const t=performance.now(); requestAnimationFrame(()=>resolve({ms:performance.now()-t,
            stop:!!document.querySelector('.composer-tools [aria-label="停止生成"]'),
            summary:document.querySelector('.activity-strip .activity-summary')?.textContent}));
        },{once:true,capture:true}));}""")
        if mobile:
            cta.focus()
            cta.press("Space")
        else:
            cta.hover()
            page.mouse.down()
            page.wait_for_function("getComputedStyle(document.querySelector('.action-inner')).transform!=='none'")
            assert cta.bounding_box() == bounds
            page.mouse.up()
        ack = page.evaluate("window.__ack")
        assert ack["stop"] and ack["summary"] == "已提交，等待响应" and ack["ms"] < 100, ack
        # A rapid second activation (or held Enter) must not send again or cancel the first.
        page.locator(".composer-tools button[aria-label='停止生成']").dispatch_event("click", {"detail": 2})
        editor.evaluate("e=>e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',repeat:true,bubbles:true,cancelable:true}))")
        strip = page.get_by_role("region", name="处理进度")
        if mobile:
            expect(strip.get_by_role("button", name="展开详情")).to_be_visible()
            strip.get_by_role("button", name="展开详情").click()
        rows = strip.locator(".activity-nodes li")
        expected = ["去程交通部分完成", "返程交通已复用", "住宿候选进行中", "会场通勤待开始"]
        expect(rows).to_have_text(expected)
        assert len(chat_posts()) == 1 and chat_posts()[0]["message"] == prompt
        assert original.evaluate("e=>e===document.querySelector('textarea[aria-label=输入消息]')")
        if mobile:
            assert strip.evaluate("e=>getComputedStyle(e).animationName") == "none"
            page.screenshot(path=output / "mobile-working.png")
        else:
            expect(page.get_by_role("navigation", name="聊天记录")).to_be_visible()
        button("展开行程档案").click()
        details = page.locator(".activity-detail")
        expect(details.locator(".activity-nodes li")).to_have_text(expected)
        expect(page.get_by_role("navigation", name="聊天记录")).to_have_count(0)
        assert "NON_PUBLIC_FIXTURE" not in page.locator("body").inner_text()
        if mobile:
            page.keyboard.press("Escape")
            expect(button("展开行程档案")).to_be_focused()
            page.get_by_role("link", name="个人中心", exact=True).click()
            expect(page.get_by_text("助手仍在生成回复", exact=False)).to_be_visible()
            expect(page.get_by_role("region", name="处理进度")).to_have_count(0)
            page.go_back(wait_until="commit")
            expect(rows).to_have_text(expected)
            editor.fill("下一条先留在输入框里")
            page.locator(".composer-tools").get_by_role("button", name="停止生成").click()
            release.set()
            expect(page.get_by_text("本轮查询已取消", exact=False)).to_be_visible()
            button("展开行程档案").click()
            expect(details.locator(".activity-nodes li")).to_have_text(
                ["去程交通部分完成", "返程交通已复用", "住宿候选已停止", "会场通勤已停止"])
            page.keyboard.press("Escape")
            expect(editor).to_have_value("下一条先留在输入框里")
        else:
            strip.scroll_into_view_if_needed()
            page.locator(".masthead").evaluate("e=>Promise.allSettled(e.getAnimations({subtree:true}).map(a=>a.finished))")
            page.screenshot(path=output / "desktop-working.png")
            # Showing another archive tab must not reset it when a new event arrives.
            page.get_by_role("tab", name="协作").focus()
            page.keyboard.press("ArrowRight")
            expect(page.get_by_role("tab", name="偏好")).to_be_focused()
            release.set()
            expect(button("发送消息")).to_be_visible()
            expect(page.get_by_role("tab", name="偏好")).to_have_attribute("aria-selected", "true")
            page.get_by_role("tab", name="协作").click()
            expect(details).to_contain_text("本轮结束，有待核验项")
            expect(details.locator(".activity-nodes li")).to_have_text(
                ["去程交通部分完成", "返程交通已复用", "住宿候选未收到结果", "会场通勤未收到结果"])
            for prompt, message, status in [("快路径：只问日期","你准备哪天出发？","等待你补充信息"),
                                          ("中断演练","连接提前结束","连接中断，未收到完整回复")]:
                editor.fill(prompt)
                editor.press("Enter")
                expect(page.locator("[data-message-role=assistant]").last).to_contain_text(message)
                expect(details).to_contain_text(status)
                expect(details.locator(".activity-nodes li")).to_have_count(0)
        assert_no_overflow(page)
        assert not errors, errors
        ctx.close()
        return {"提交到下一帧毫秒": round(ack["ms"], 1), "下一帧反馈": ack["summary"],
                "本轮请求无重复": True, "模式": "手动静态与系统减弱" if mobile else "标准", "页面脚本异常": errors}


def verify_widths(browser, base):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(base, wait_until="networkidle")
    checked = []
    for w, h in [(320, 568), (390, 432), (640, 360), (844, 390), (768, 1024), (1024, 768), (1100, 720),
                 (1279, 720), (1280, 720), (1440, 900)]:
        page.set_viewport_size({"width": w, "height": h})
        page.get_by_role("button", name="开始规划").scroll_into_view_if_needed()
        assert_no_overflow(page)
        boxes = page.locator(".flight-composer button, .masthead button, .masthead a, .example-tile").evaluate_all(
            """list=>list.filter(e=>e.getClientRects().length).map(e=>[e.getAttribute('aria-label')||e.textContent,
               e.getBoundingClientRect().width,e.getBoundingClientRect().height])""")
        assert all(b[1] >= 44 and b[2] >= 44 for b in boxes), (w, boxes)
        checked.append([w,h])
    ctx.close()
    return checked


def record_demo(browser, assets, output):
    """Record actual browser frames, including the button press, SSE changes, and final receipt."""
    with preview(assets) as (base, posted, release), TemporaryDirectory() as clips:
        dims = {"width": 1280, "height": 720}
        ctx = browser.new_context(viewport=dims, device_scale_factor=1, color_scheme="light",
                                  record_video_dir=clips, record_video_size=dims)
        errors = []
        page = guarded_page(ctx, errors)
        page.goto(base, wait_until="networkidle")
        page.wait_for_timeout(750)  # Pacing for viewers, not readiness assertions.
        page.get_by_role("button", name=re.compile("^规划行程")).click()
        page.wait_for_timeout(900)
        cta = page.get_by_role("button", name="开始规划")
        cta.hover()
        page.mouse.down()
        page.wait_for_timeout(140)
        page.mouse.up()
        strip = page.locator(".activity-strip")
        expect(strip).to_contain_text("正在处理：住宿候选")
        page.wait_for_timeout(900)
        page.get_by_role("button", name="展开行程档案").click()
        expect(page.locator(".activity-detail")).to_contain_text("部分完成")
        page.wait_for_timeout(1250)
        release.set()
        expect(page.locator(".activity-detail")).to_contain_text("本轮结束，有待核验项")
        page.wait_for_timeout(1300)
        assert len([p for p, _ in posted if p == "/api/chat"]) == 1 and not errors
        clip = page.video
        ctx.close()
        return save_recording(clip, output / "planning-feedback")


def save_recording(clip, target_stem):
    # MP4 when a local encoder exists; Playwright's native WebM otherwise.
    encoder = shutil.which("ffmpeg")
    if not encoder:
        try:
            from imageio_ffmpeg import get_ffmpeg_exe
            encoder = get_ffmpeg_exe()
        except ImportError:
            pass
    if encoder:
        target = target_stem.with_suffix(".mp4")
        subprocess.run([encoder, "-v", "error", "-y", "-i", str(clip.path()), "-an", "-c:v", "libx264",
                        "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)], check=True)
    else:
        target = target_stem.with_suffix(".webm")
        clip.save_as(target)
    return target.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chromium-exe", type=Path)
    parser.add_argument("--baseline", action="store_true", help="仅记录改版前截图和首屏请求")
    parser.add_argument("--compare", type=Path, help="改版前的 initial-requests.json，用于首屏资源增幅门禁")
    parser.add_argument("--record", action="store_true", help="录制一次真实操作；需 Playwright 的本地视频支持")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with preview(args.assets.resolve()) as (base, _, _), sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=args.chromium_exe, args=["--disable-background-networking"])
        report = {name: capture(browser, base, args.assets, args.output, name, w, h, theme) for name, w, h, theme in [
            ("desktop", 1280, 720, "light"), ("desktop-dark", 1280, 720, "dark"),
            ("mobile", 390, 844, "light"), ("mobile-dark", 390, 844, "dark")]}
        if not args.baseline:
            checks = {"浏览器": browser.version, "视口": verify_widths(browser, base),
                      "桌面": verify_interaction(browser, args.assets.resolve(), args.output, False),
                      "手机视口": verify_interaction(browser, args.assets.resolve(), args.output, True)}
            baseline = json.loads(args.compare.read_text("utf-8")) if args.compare else {}
            budgets = {}
            for name, row in report.items():
                assert row["entry_js_gzip_bytes"] <= 110 * 1024 and row["gzip_bytes"][".css"] <= 12 * 1024, name
                if baseline:
                    delta = row["gzip_bytes"][".js"] - baseline[name]["gzip_bytes"][".js"]
                    assert delta <= 15 * 1024, (name, delta)
                    budgets[name] = delta
            checks["相对基线首屏 JS 增量（字节）"] = budgets
            if args.record:
                checks["操作录屏"] = record_demo(browser, args.assets.resolve(), args.output)
            (args.output / "interaction-report.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), "utf-8")
        browser.close()
    (args.output / "initial-requests.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print({name: row["gzip_bytes"] for name, row in report.items()})


if __name__ == "__main__":
    main()
