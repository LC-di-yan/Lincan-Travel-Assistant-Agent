"""Check assets and mobile startup in a fresh guest session, without submitting a turn."""

import argparse
import json
from pathlib import Path
from statistics import median
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from run_flightdeck_p4 import INIT


PROFILE = {"latency": 150, "downloadThroughput": 200000, "uploadThroughput": 93750}
ENCODINGS = {"gzip", "br", "zstd"}


def origin(url):
    parts = urlsplit(url)
    return parts.scheme, parts.netloc


def visit(browser, url, expected_entry, expected_css):
    with browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True,
                             has_touch=True, device_scale_factor=1) as context:
        page = context.new_page()
        page.add_init_script(INIT)
        cdp = context.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        cdp.send("Network.emulateNetworkConditions", {"offline": False, **PROFILE})
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
        errors, responses = [], {}
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("response", lambda response: responses.update({response.url: response}))
        page.goto(url, wait_until="networkidle", timeout=25000)
        assert origin(page.url) == origin(url), "Unexpected redirect away from the checked environment."
        expect(page.get_by_role("heading", name="下一程，去哪里？")).to_be_visible()
        expect(page.get_by_role("figure", name="北京至上海的示例航图，非实时路线")).to_be_visible()
        expect(page.get_by_role("textbox", name="输入消息")).to_be_editable()
        expect(page.get_by_role("button", name="开始规划")).to_be_enabled()
        page.wait_for_function("window.p4Lab?.lcp != null")
        lab = page.evaluate("""() => ({
            ...p4Lab,
            assets: performance.getEntriesByType('resource')
              .filter(e => /\\.(js|css)$/.test(new URL(e.name).pathname))
              .map(e => ({name:e.name, actualBytes:e.encodedBodySize, decodedBytes:e.decodedBodySize}))
        })""")
        for asset in lab["assets"]:
            response = responses.get(asset["name"])
            asset["encoding"] = response.header_value("content-encoding") if response else None
            asset["status"] = response.status if response else None
        names = {Path(urlsplit(asset["name"]).path).name: asset for asset in lab["assets"]}
        for name in (expected_entry, expected_css):
            assert name in names, f"Unexpected release build: could not find {name}."
            asset = names[name]
            assert asset["status"] == 200 and asset["encoding"] in ENCODINGS, asset
            assert 0 < asset["actualBytes"] < asset["decodedBytes"], asset
        assert not errors, errors
        return lab


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--entry", default="index-Cv57qtnP.js")
    parser.add_argument("--css", default="index-CKH1SqUb.css")
    parser.add_argument("--chromium-exe", type=Path, required=True)
    parser.add_argument("--direct", action="store_true", help="Do not inherit the host browser's proxy settings.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if parsed.username or parsed.password or not parsed.hostname or parsed.scheme not in {"https", "http"}:
        parser.error("Provide a site URL without embedded credentials.")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Use HTTPS for remotely hosted sites.")

    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=args.chromium_exe,
                                         args=["--no-proxy-server"] if args.direct else [])
        samples = [visit(browser, args.url, args.entry, args.css) for _ in range(5)]
        version = browser.version
        browser.close()
    lcp = [row["lcp"] for row in samples]
    result = {"浏览器": version, "档位": "390×844；DPR 1；空缓存；150 ms RTT；下行 200000 B/s；"
              "上行 93750 B/s；CPU 4 倍降速",
              "首屏中位毫秒": median(lcp), "首屏范围毫秒": [min(lcp), max(lcp)],
              "最大布局偏移": max(row["shift"] for row in samples), "样本": samples}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "样本"}, ensure_ascii=False))
    assert result["首屏中位毫秒"] <= 2500 and result["最大布局偏移"] <= .10


if __name__ == "__main__":
    main()
