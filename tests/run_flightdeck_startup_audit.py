"""Verify identity ordering, optional assets, focus and navigation on a built app."""

import argparse
import json
from pathlib import Path
import re
from threading import Event
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from run_flightdeck_p4 import PROMPT, stream
from run_flightdeck_visual_audit import assert_no_overflow, guarded_page, preview


def identity_gate(browser, base, posted, identity_release):
    with browser.new_context() as ctx:
        ctx.add_init_script("""localStorage.setItem('aligo_user_id','fixture-other-owner');
          localStorage.setItem('aligo_session_id','foreign-history');""")
        errors, paths = [], []
        page = guarded_page(ctx, errors)
        page.on("request", lambda request: paths.append(urlsplit(request.url).path))
        page.goto(f"{base}/#/personal", wait_until="domcontentloaded")
        expect(page.get_by_text("正在建立安全会话…")).to_be_visible()
        assert [path for path in paths if path.startswith("/api/")] == ["/api/identity"]
        expect(page.get_by_role("textbox", name="输入消息")).to_have_count(0)
        identity_release.set()
        expect(page.get_by_role("link", name="个人中心")).to_be_visible()
        page.goto(f"{base}/#/")
        expect(page.get_by_role("figure", name="北京至上海的示例航图，非实时路线")).to_be_visible()
        page.get_by_role("textbox", name="输入消息").fill(PROMPT)
        page.get_by_role("button", name="开始规划").click()
        expect(page.get_by_text("演练已收到规划请求", exact=False)).to_be_visible()
        assert paths.count("/api/identity") == 1 and "foreign-history" not in " ".join(paths)
        chat = [body for path, body in posted if path == "/api/chat"]
        assert len(chat) == 1 and chat[0]["user_id"] == "flightdeck-fixture" and chat[0]["session_id"].startswith("audit-"), chat
        assert not errors, errors


def identity_retry(browser, base):
    with browser.new_context() as ctx:
        errors, attempts = [], []
        page = guarded_page(ctx, errors)

        def deny_first(route):
            attempts.append(route.request.method)
            if len(attempts) == 1:
                route.fulfill(status=503, body="fixture: handshake unavailable")
            else:
                route.continue_()

        page.route("**/api/identity", deny_first)
        page.goto(base)
        expect(page.get_by_role("status")).to_contain_text("未能建立安全会话")
        page.get_by_role("button", name="重新连接").press("Enter")
        expect(page.get_by_role("textbox", name="输入消息")).to_be_visible()
        assert attempts == ["POST", "POST"] and not errors, (attempts, errors)


def optional_chunk_failure(browser, base):
    with browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True) as ctx:
        errors = []
        page = guarded_page(ctx, errors)
        page.route("**/assets/TTSSettings-*.js", lambda route: route.abort())
        page.goto(base)
        trigger = page.get_by_role("button", name="显示与语音设置")
        trigger.press("Space")
        dialog = page.get_by_role("dialog", name="显示与语音设置")
        expect(dialog.get_by_role("alert")).to_contain_text("暂时无法加载")
        page.keyboard.press("Escape")
        expect(trigger).to_be_focused()
        expect(dialog).to_have_count(0)
        expect(page.get_by_role("figure", name="北京至上海的示例航图，非实时路线")).to_be_visible()
        page.get_by_role("textbox", name="输入消息").fill("设置模块失败不影响草稿")
        expect(page.get_by_role("button", name="开始规划")).to_be_enabled()
        assert not errors, errors


def memory_sample(page, cdp, turn):
    # Chromium's transient parser/automation documents can survive a single collection.
    for _ in range(3):
        cdp.send("HeapProfiler.collectGarbage")
        counters = cdp.send("Memory.getDOMCounters")
        if counters["documents"] == 1:
            break
        page.wait_for_timeout(100)
    return {"往返": turn, "JS堆字节": cdp.send("Runtime.getHeapUsage")["usedSize"], **counters}


def keyboard_and_navigation(browser, base, output, forced_colors, engine):
    with browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True,
                             reduced_motion="reduce", forced_colors=forced_colors) as ctx:
        errors, paths = [], []
        page = guarded_page(ctx, errors)
        page.add_init_script("""(() => {
          const original = HTMLCanvasElement.prototype.getContext;
          window.webglAttempts = 0;
          HTMLCanvasElement.prototype.getContext = function (name, ...rest) {
            if (/webgl/i.test(name)) { window.webglAttempts++; return null; }
            return original.call(this, name, ...rest);
          };
          const raf = window.requestAnimationFrame;
          window.activeRaf = new Set();
          window.requestAnimationFrame = fn => {
            const id = raf.call(window, t => { activeRaf.delete(id); fn(t); });
            activeRaf.add(id);
            return id;
          };
          const cancel = window.cancelAnimationFrame;
          window.cancelAnimationFrame = id => { activeRaf.delete(id); cancel.call(window,id); };
        })();""")
        page.on("request", lambda request: paths.append(urlsplit(request.url).path))
        page.goto(base, wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("data-motion", "reduced")
        assert not any(re.match(r"/assets/(TTSSettings|ConversationSidebar|Sidebar|PersonalCenter)-", path) for path in paths)
        assert_no_overflow(page)
        page.screenshot(path=output / ("p5-forced-colors.png" if forced_colors == "active" else "p5-mobile-reduced.png"))
        trigger = page.get_by_role("button", name="显示与语音设置")
        trigger.press("Enter")
        modal = page.get_by_role("dialog", name="显示与语音设置")
        expect(modal.get_by_role("button", name="关闭设置")).to_be_focused()
        for key in ("Tab", "Tab", "Shift+Tab"):
            page.keyboard.press(key)
            assert page.evaluate("document.querySelector('dialog[open]').contains(document.activeElement)")
        modal.get_by_label("动态效果").press("End")
        expect(page.locator("html")).to_have_attribute("data-motion", "static")
        page.keyboard.press("Escape")
        expect(trigger).to_be_focused()
        for label, title in (("展开聊天记录", "聊天记录"), ("展开行程档案", "行程档案")):
            opener = page.get_by_role("button", name=label)
            opener.press("Enter")
            expect(page.get_by_role("dialog", name=title)).to_be_visible()
            expect(page.get_by_role("button", name="关闭" + title)).to_be_focused()
            page.keyboard.press("Escape")
            expect(opener).to_be_focused()
        memory_samples = []
        if forced_colors == "none":
            cdp = ctx.new_cdp_session(page) if engine == "chromium" else None
            # The first navigation warms the lazy personal module; measure steady-state thereafter.
            for turn in range(21):
                page.get_by_role("link", name="个人中心").press("Enter")
                expect(page.get_by_role("heading", name="个人中心", exact=True)).to_be_visible()
                expect(page.get_by_text("暂无有日期的本月记录。")).to_be_visible()
                page.get_by_role("link", name="ALIGO，返回航图台").press("Enter")
                expect(page.get_by_role("figure", name="北京至上海的示例航图，非实时路线")).to_be_visible()
                if cdp and turn % 5 == 0:
                    page.wait_for_function("activeRaf.size === 0")
                    memory_samples.append(memory_sample(page, cdp, turn))
            page.wait_for_function("activeRaf.size === 0")
            expect(page.locator("dialog[open]")).to_have_count(0)
            if memory_samples:
                first, last = memory_samples[0], memory_samples[-1]
                assert last["documents"] == first["documents"], memory_samples
                assert last["nodes"] <= first["nodes"] + 16, memory_samples
                assert last["jsEventListeners"] <= first["jsEventListeners"] + 6, memory_samples
                assert last["JS堆字节"] - first["JS堆字节"] < 512 * 1024, memory_samples
        assert paths.count("/api/identity") == 1 and "/api/chat" not in paths
        assert page.evaluate("webglAttempts") == 0
        assert not errors, errors
        return memory_samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chromium-exe", type=Path)
    parser.add_argument("--engine", choices=("chromium", "firefox", "webkit"), default="chromium")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.engine == "webkit":
        expect.set_options(timeout=15000)
    identity_release = Event()
    with preview(args.assets.resolve(), chat_script=stream, identity_release=identity_release) as (base, posted, _), sync_playwright() as driver:
        browser = getattr(driver, args.engine).launch(executable_path=args.chromium_exe)
        identity_gate(browser, base, posted, identity_release)
        identity_retry(browser, base)
        optional_chunk_failure(browser, base)
        memory_samples = keyboard_and_navigation(browser, base, args.output, "none", args.engine)
        if args.engine == "chromium":
            keyboard_and_navigation(browser, base, args.output, "active", args.engine)
        results = {"引擎": args.engine, "版本": browser.version, "独立身份请求与越权提示丢弃": True,
                   "握手失败后可重连": True, "设置资源失败不阻断首页": True, "键盘与焦点": True,
                   "20 次个人区往返后无活动帧、无 WebGL 请求": True, "强制颜色": args.engine == "chromium",
                   "内存抽样": memory_samples}
        (args.output / "startup-audit.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps(results, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()
