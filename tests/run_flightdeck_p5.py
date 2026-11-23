"""Measure the static flight deck before/after under the identical P4 mobile profile."""

import argparse
import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
from statistics import median
import sys
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from run_flightdeck_p4 import INIT, PROMPT, startup_assets, stream, study_copy
from run_flightdeck_visual_audit import guarded_page, preview


TRACE = INIT + """
window.p4Lab.lcpCandidates = []
new PerformanceObserver(list => {
  for (const e of list.getEntries()) window.p4Lab.lcpCandidates.push({
    time:e.startTime, size:e.size, tag:e.element?.tagName ?? null,
    text:e.element?.textContent?.trim().slice(0, 80) ?? null
  })
}).observe({type:'largest-contentful-paint',buffered:true})
const originalFetch = window.fetch
window.fetch = async (...args) => {
  const res = await originalFetch.apply(window, args)
  if (typeof args[0] === 'string' && new URL(args[0], location.href).pathname === '/api/chat') {
    const reader = res.clone().body?.getReader()
    void (async () => {
      if (!reader) return
      const decoder = new TextDecoder()
      let text = ''
      try {
        for (;;) {
          const {value,done} = await reader.read()
          if (done) return
          text += decoder.decode(value, {stream:true})
          if (/^event: thinking\\r?\\ndata: [^\\n]*\\r?\\n\\r?\\n/m.test(text)) {
            window.p5FirstEvent = performance.now()
            return
          }
        }
      } finally {
        void reader.cancel().catch(() => {})
      }
    })().catch(() => {})
  }
  return res
}
"""


def visit(browser, base, mirror, posted):
    with browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True,
                             has_touch=True, device_scale_factor=1) as ctx:
        errors, requests = [], []
        page = guarded_page(ctx, errors)
        page.add_init_script(TRACE)
        cdp = ctx.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 150,
                 "downloadThroughput": 200000, "uploadThroughput": 93750})
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
        page.on("request", lambda req: requests.append(urlsplit(req.url).path))
        page.goto(f"{base}/?p4=a", wait_until="networkidle")
        page.wait_for_function("window.p4?.ready != null && window.p4Lab?.lcp != null")
        assert requests.count("/api/identity") == 1
        assert not any("parallax" in path for path in requests)
        expect(page.get_by_role("figure", name="北京至上海的示例航图，非实时路线")).to_be_visible()
        lab = page.evaluate("""() => ({
          ...p4Lab, ready: p4.ready,
          resources: performance.getEntriesByType('resource').map(e=>({
            path:new URL(e.name).pathname, start:e.startTime, headers:e.responseStart, end:e.responseEnd,
            body_B:e.encodedBodySize
          }))
        })""")
        lab.update(startup_assets(page, mirror))
        before = len(posted)
        page.get_by_role("button", name="规划行程", exact=False).click()
        assert not any(path == "/api/chat" for path, _ in posted[before:])
        page.get_by_role("textbox", name="输入消息").fill(PROMPT)
        button = page.get_by_role("button", name="开始规划")
        response = "演练已收到规划请求"
        page.evaluate("""response => {
          document.querySelector('.deck-action').addEventListener('click', () => {
            const measure = window.p5Click = {start:performance.now()}
            const observe = new MutationObserver(() => {
              if (measure.ack == null && document.querySelector('[aria-label="停止生成"]'))
                measure.ack = performance.now() - measure.start
              if (document.querySelector('#root').textContent.includes(response)) {
                measure.result = performance.now() - measure.start
                observe.disconnect()
              }
            })
            observe.observe(document.getElementById('root'), {subtree:true,childList:true,attributes:true,characterData:true})
          }, {capture:true,once:true})
        }""", response)
        with page.expect_response(lambda res: urlsplit(res.url).path == "/api/chat") as reply:
            button.click()
        assert reply.value.ok
        expect(page.get_by_text(response, exact=False)).to_be_visible()
        page.wait_for_function("window.p4?.submit != null && window.p5Click?.result != null && window.p5FirstEvent != null")
        assert [body.get("message") for path, body in posted[before:] if path == "/api/chat"] == [PROMPT]
        assert not errors, errors
        lab.update(page.evaluate("""() => {
          const resource = performance.getEntriesByType('resource').find(e=>new URL(e.name).pathname==='/api/chat')
          return {
            send:p4.submit-p5Click.start, ack:p5Click.ack,
            streamStart:resource.responseStart-p5Click.start,
            firstEvent:p5FirstEvent-p5Click.start, result:p5Click.result
          }
        }"""))
        return lab


def metrics(rows):
    return {key: [round(min(values), 3), round(median(values), 3), round(max(values), 3)]
            for key in ("lcp", "ready", "shift", "ack", "send", "streamStart", "firstEvent", "result")
            if (values := [row[key] for row in rows if row[key] is not None])}


def static_app(mirror, compressed):
    """Use the same static ASGI serving code as the respective before/after builds."""
    import httpx
    from fastapi.staticfiles import StaticFiles
    from starlette.routing import Mount, Router

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from server.frontend_assets import frontend_assets

    assets = mirror / "assets"
    app = Router(routes=[Mount("/assets", app=frontend_assets(assets) if compressed else StaticFiles(directory=assets))])

    async def read(path, accept_encoding):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://assets") as client:
            async with client.stream("GET", path, headers={"Accept-Encoding": accept_encoding}) as result:
                return result.status_code, result.headers.multi_items(), b"".join([part async for part in result.aiter_raw()])

    return lambda path, accept_encoding: asyncio.run(read(path, accept_encoding))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chromium-exe", required=True)
    parser.add_argument("--samples", type=int, default=5, choices=range(5, 16))
    parser.add_argument("--served-assets", action="store_true", help="Exercise the respective application asset-serving stacks")
    args = parser.parse_args()
    builds = {"before": args.before.resolve()}
    if args.after:
        builds["after"] = args.after.resolve()
    rows = {arm: [] for arm in builds}
    with ExitStack() as stack:
        active = {}
        for arm, assets in builds.items():
            mirror = stack.enter_context(study_copy(assets))
            get_asset = static_app(mirror, compressed=arm == "after") if args.served_assets else None
            base, posts, _ = stack.enter_context(preview(mirror, chat_script=stream, get_asset=get_asset))
            active[arm] = base, mirror, posts
        driver = stack.enter_context(sync_playwright())
        browser = driver.chromium.launch(executable_path=args.chromium_exe)
        for index in range(args.samples):
            order = list(active) if index % 2 == 0 else list(reversed(active))
            for arm in order:
                row = visit(browser, *active[arm])
                rows[arm].append(row)
                print(f"{arm} {index+1}: LCP {row['lcp']}ms, ready {row['ready']:.1f}ms", flush=True)
        version = browser.version
        browser.close()
    output = {"browser": version, "mobile": "390×844; DPR 1; cache off; RTT 150 ms; "
              "down 200000 B/s; up 93750 B/s; CPU 4×; loopback fixture",
              "serving": "ASGI StaticFiles → compiled-asset gzip" if args.served_assets else "P4 server, always uncompressed",
              "metric_order": ["min", "median", "max"], "summaries": {arm: metrics(samples) for arm, samples in rows.items()},
              "samples": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(output["summaries"], ensure_ascii=False))
    if args.served_assets and "after" in rows:
        for row in rows["after"]:
            delivered = sum(res["body_B"] for res in row["resources"] if res["path"] in row["文件"])
            assert 0 < delivered < 125 * 1024, delivered
        assert output["summaries"]["after"]["lcp"][1] <= 2500, "Mobile lab LCP target missed"
        assert output["summaries"]["after"]["shift"][2] <= .10, "Layout-shift budget missed"


if __name__ == "__main__":
    main()
