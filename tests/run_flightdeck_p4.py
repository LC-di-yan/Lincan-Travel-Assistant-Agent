"""Compare the built home page with a disposable, opt-in parallax prototype."""
import argparse
from contextlib import contextmanager
import gzip
import hashlib
import json
import shutil
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import sleep
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from run_flightdeck_visual_audit import guarded_page, preview


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "flightdeck-p4"
PROMPT = "周三从北京去上海出差三天，总预算 2400 元，请开始规划。"
MODULE = "/p4-parallax.mjs"
LAYER = ".plate-map g[clip-path] > g"
INIT = """
window.p4Lab={lcp:null,shift:0}
new PerformanceObserver(list => {
  for(const item of list.getEntries()) window.p4Lab.lcp=item.startTime
}).observe({type:'largest-contentful-paint',buffered:true})
new PerformanceObserver(list => {
  for(const item of list.getEntries()) if(!item.hadRecentInput) window.p4Lab.shift+=item.value
}).observe({type:'layout-shift',buffered:true})
"""


def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


@contextmanager
def study_copy(assets):
    fingerprint = {file.relative_to(assets): digest(file) for file in assets.rglob("*") if file.is_file()}
    with TemporaryDirectory(prefix="flightdeck-p4-") as path:
        mirror = Path(path) / "site"
        shutil.copytree(assets, mirror)
        original = (mirror / "index.html").read_text("utf-8")
        boot = (FIXTURES / "boot.js").read_text("utf-8")
        assert "</body>" in original
        (mirror / "index.html").write_text(original.replace("</body>", f"<script>{boot}</script></body>"), "utf-8")
        shutil.copyfile(FIXTURES / "parallax.mjs", mirror / MODULE[1:])
        shutil.copyfile(FIXTURES / "study.html", mirror / "p4-study.html")
        yield mirror
    assert all(digest(assets / name) == sha for name, sha in fingerprint.items()), "Do not modify the production bundle."


def stream(emit, _):
    sleep(.25)
    emit("thinking", {"status": "analyzing_intent"})
    emit("complete", {"status": "completed", "results": [
        {"agent_name": "memory_query", "status": "success", "data": {"answer": "演练已收到规划请求；没有查询、出票或保存。"}}
    ]})


def startup_assets(page, mirror):
    paths = page.evaluate("""performance.getEntriesByType('resource')
      .map(e=>new URL(e.name).pathname).filter(p=>p.startsWith('/assets/')).sort()""")
    assert not any("three" in path.lower() or "rive" in path.lower() for path in paths)
    return {
        "文件": paths,
        "JS_gzip_B": sum(len(gzip.compress((mirror / path[1:]).read_bytes(), compresslevel=6, mtime=0))
                         for path in set(paths) if path.endswith(".js")),
        "CSS_gzip_B": sum(len(gzip.compress((mirror / path[1:]).read_bytes(), compresslevel=6, mtime=0))
                          for path in set(paths) if path.endswith(".css")),
    }


def sample(browser, base, mirror, posted, arm, mobile):
    ctx = browser.new_context(viewport={"width": 390 if mobile else 1366, "height": 844 if mobile else 900},
                              is_mobile=mobile, has_touch=mobile, device_scale_factor=1)
    errors = []
    page = guarded_page(ctx, errors)
    page.add_init_script(INIT)
    if mobile:
        cdp = ctx.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 150,
                 "downloadThroughput": 200000, "uploadThroughput": 93750})
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
    requests = []
    page.on("request", lambda req: requests.append(urlsplit(req.url).path))
    page.goto(f"{base}/?p4={arm}", wait_until="networkidle")
    page.wait_for_function("window.p4?.ready != null && window.p4Lab?.lcp != null")
    common = startup_assets(page, mirror)
    assert MODULE not in requests
    assert common["JS_gzip_B"] <= 125 * 1024 and common["CSS_gzip_B"] <= 12 * 1024
    entry = next(path for path in common["文件"] if Path(path).name.startswith("index-") and path.endswith(".js"))
    assert len(gzip.compress((mirror / entry[1:]).read_bytes(), compresslevel=6, mtime=0)) <= 110 * 1024
    lab = page.evaluate("({...window.p4Lab, ready:window.p4.ready})")
    map_heading = page.get_by_role("figure", name="北京至上海的示例航图，非实时路线")
    expect(map_heading).to_be_visible()
    button = page.get_by_role("button", name="开始规划")
    placement = button.bounding_box()
    copy = page.locator(".brief-heading").inner_text()
    if mobile:
        page.get_by_role("figure").tap()
        assert MODULE not in requests
    before = len(posted)
    page.get_by_role("button", name="规划行程", exact=False).click()
    assert not any(path == "/api/chat" for path, _ in posted[before:]), "An example can prefill, not send."
    page.get_by_role("textbox", name="输入消息").fill(PROMPT)
    page.evaluate("""() => {
      document.querySelector('.deck-action').addEventListener('click', () => {
        window.p4Click = performance.now()
        const observe = new MutationObserver(() => {
          if (document.querySelector('[aria-label="停止生成"]')) {
            window.p4Ack = performance.now()
            observe.disconnect()
          }
        })
        observe.observe(document.getElementById('root'), {childList:true,subtree:true,attributes:true})
      }, {once:true,capture:true})
    }""")
    button.click()
    expect(page.get_by_text("演练已收到规划请求", exact=False)).to_be_visible()
    page.wait_for_function("window.p4.submit != null && window.p4Ack != null")
    assert [payload["message"] for path, payload in posted[before:] if path == "/api/chat"] == [PROMPT]
    timing = page.evaluate("({send: p4.submit-p4Click, ack:p4Ack-p4Click})")
    assert timing["send"] >= 0 and timing["ack"] >= 0
    assert MODULE not in requests and not errors, errors
    ctx.close()
    return common, placement, copy, {**lab, **timing}


def move_on_map(page):
    box = page.locator(".plate-map").bounding_box()
    start = (box["x"] + box["width"] * .13, box["y"] + box["height"] * .22)
    end = (box["x"] + box["width"] * .83, box["y"] + box["height"] * .58)
    page.mouse.move(*start)
    return start, end


def visual_gate(browser, base, output, mode):
    ctx = browser.new_context(viewport={"width": 1366, "height": 900}, reduced_motion="reduce" if mode == "reduced" else "no-preference")
    errors, requests = [], []
    page = guarded_page(ctx, errors)
    if mode == "missing":
        page.route("**" + MODULE, lambda route: route.abort())
    if mode == "static":
        ctx.add_init_script("localStorage.setItem('aligo-motion','static')")
    # Deliberately force slow frames to exercise the fallback, not to report device FPS.
    if mode == "slow":
        ctx.add_init_script("""window.p4Delay=false; const raf=requestAnimationFrame;
            window.requestAnimationFrame=cb=>p4Delay ? setTimeout(()=>cb(performance.now()),42) : raf(cb);
            const cancel=cancelAnimationFrame; window.cancelAnimationFrame=id=>{clearTimeout(id);cancel(id)};
        """)
    page.on("request", lambda req: requests.append(urlsplit(req.url).path))
    arm = "a" if mode == "control" else "b"
    page.goto(f"{base}/?p4={arm}", wait_until="networkidle")
    page.wait_for_function("window.p4?.ready != null")
    assert MODULE not in requests
    path = page.locator(".plate-route")
    labels = page.locator(".plate-map-label").first
    before = (path.bounding_box(), labels.bounding_box(), page.get_by_role("button", name="开始规划").bounding_box())
    map_part = page.locator(".atlas-plate")
    start, end = move_on_map(page)
    if mode in ("control", "reduced", "static"):
        page.mouse.move(*end, steps=18)
        assert MODULE not in requests
        assert page.locator(LAYER).evaluate("e=>e.style.transform") == ""
        if mode == "control":
            map_part.screenshot(path=output / "static-map.png")
    elif mode == "missing":
        page.wait_for_function("window.p4.state==='unavailable'")
        assert page.locator(LAYER).evaluate("e=>e.style.transform") == ""
    else:
        page.wait_for_function("window.p4.state==='armed'")
        page.mouse.move(*end, steps=20)
        page.wait_for_function("window.p4.samples.length > 0")
        assert path.bounding_box() == before[0] and labels.bounding_box() == before[1]
        assert page.get_by_role("button", name="开始规划").bounding_box() == before[2]
        move = page.locator(LAYER).evaluate("""e=>{const m=new DOMMatrix(e.style.transform);return [m.e,m.f]}""")
        assert 0 < (move[0]**2 + move[1]**2)**.5 <= 5.01
        if mode == "slow":
            page.evaluate("window.p4Delay=true")
            for _ in range(36):
                page.mouse.move(*start)
                page.wait_for_timeout(15)
                page.mouse.move(*end)
                page.wait_for_timeout(16)
            page.wait_for_function("window.p4.state==='slow-fallback'")
            assert page.locator(LAYER).evaluate("e=>e.style.transform") == ""
        else:
            map_part.screenshot(path=output / "parallax-map.png")
            page.mouse.move(10, 10)
            assert page.locator(LAYER).evaluate("e=>e.style.transform") == ""
            page.mouse.move(*end, steps=6)
            page.wait_for_function(f"document.querySelector('{LAYER}').style.transform !== ''")
            page.locator(LAYER).evaluate("e=>window.p4PreviousLayer=e")
    error_count = len(errors)
    editor = page.get_by_role("textbox", name="输入消息")
    editor.fill(PROMPT)
    editor.press("Enter")
    expect(page.get_by_text("演练已收到规划请求", exact=False)).to_be_visible()
    assert not page.locator(".atlas-plate").count()
    if mode == "motion":
        page.wait_for_function("p4PreviousLayer.style.transform === ''")
        count = page.evaluate("p4.samples.length")
        page.mouse.move(*start, steps=5)
        assert page.evaluate("p4.samples.length") == count
        assert requests.count(MODULE) == 1
    assert len(errors) == error_count == 0, errors
    samples = page.evaluate("p4.samples")
    assert all(row["latency"] >= 0 for row in samples), samples
    ctx.close()
    return {"模块请求": requests.count(MODULE), "采样帧数": len(samples),
            "输入到样式更新中位_ms": round(median(row["latency"] for row in samples), 1) if samples else None}


def rehearse_study(browser, base):
    ctx = browser.new_context(viewport={"width": 1366, "height": 940}, accept_downloads=True)
    errors = []
    page = guarded_page(ctx, errors)
    page.goto(f"{base}/p4-study.html?arm=a")
    page.get_by_role("button", name="开始练习").click()
    ready = page.get_by_role("button", name="我知道这个页面要怎么用")
    expect(ready).to_be_enabled()
    ready.click()
    home = page.frame_locator("iframe")
    home.get_by_role("textbox", name="输入消息").fill(PROMPT)
    home.get_by_role("button", name="开始规划").click()
    page.get_by_label("说明用途的示例航图").check()
    page.get_by_label("只是把内容填进输入框").check()
    with page.expect_download() as completed:
        page.get_by_role("button", name="下载匿名结果").click()
    row = json.loads(completed.value.path().read_text("utf-8"))
    assert set(row) == {"trial", "arm", "understood_ms", "first_submit_ms", "quiz_correct", "motion_exposed", "motion_eligible"}
    assert row["quiz_correct"] == 2 and not row["motion_exposed"] and not errors
    assert 0 <= row["understood_ms"] <= row["first_submit_ms"]
    ctx.close()
    return "机器跑通匿名问卷及下载；不是一份参与者数据。"


def window(rows, key):
    values = [row[key] for row in rows]
    return {"中位": round(median(values), 1), "范围": [round(min(values), 1), round(max(values), 1)]}


def measure(base, mirror, posted, args):
    report = {}
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=args.chromium_exe, args=["--disable-background-networking"])
        report["浏览器"] = browser.version
        for mobile in (False, True):
            records = {"a": [], "b": []}
            shared = None
            for i in range(args.repeats):
                for arm in (("a", "b") if i % 2 == 0 else ("b", "a")):
                    resources, layout, copy, row = sample(browser, base, mirror, posted, arm, mobile)
                    if shared is None:
                        shared = (resources, layout, copy)
                    else:
                        assert (resources, layout, copy) == shared, "Both variants must share the same first screen."
                    records[arm].append(row)
            report["手机慢网与4倍CPU" if mobile else "桌面"] = {
                "共同首屏资源": shared[0], "每版样本数": args.repeats,
                "各版": {arm: {key: window(rows, key) for key in ("ready", "lcp", "shift", "ack", "send")}
                        for arm, rows in records.items()}, "样本": records,
            }
        report["行为与回退"] = {mode: visual_gate(browser, base, args.output, mode)
                           for mode in ("control", "motion", "reduced", "static", "slow", "missing")}
        report["问卷演练"] = rehearse_study(browser, base)
        browser.close()
    report["原型模块_gzip_B"] = len(gzip.compress((mirror / MODULE[1:]).read_bytes(), compresslevel=6, mtime=0))
    report["限制"] = "机器启动与固定操作回放，不是人类可用性测试。"
    (args.output / "p4-measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print("静态与轻视差的首屏、业务路径、动效边界和回退验证通过。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("output/flightdeck-p4"))
    parser.add_argument("--chromium-exe", type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with study_copy(args.assets.resolve()) as mirror, preview(mirror, chat_script=stream,
                                                             get_fixture=lambda path: {"enabled": False}
                                                             if path == "/api/personal/capabilities" else None) as (base, posted, _):
        if args.serve:
            print(f"组织者分发地址：{base}/p4-study.html?arm=a 或 {base}/p4-study.html?arm=b", flush=True)
            try:
                while True:
                    sleep(2)
            except KeyboardInterrupt:
                pass
        else:
            measure(base, mirror, posted, args)


if __name__ == "__main__":
    main()
