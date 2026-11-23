"""Exercise the remaining P3 surfaces without collecting media."""
import argparse
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from run_flightdeck_visual_audit import assert_no_overflow, guarded_page, preview


def result(agent, data):
    return {"agent_name": agent, "status": "success", "data": data}


RESULTS = [
    result("event_collection", {"origin": "北京", "destination": "上海", "missing_info": ["出发日期"]}),
    result("currency_converter", {"from": "USD", "to": "CNY", "amount": 10, "rate": 7.2, "result": 72,
                                  "rate_date": "2026-11-21", "sources": [{"title": "参考汇率", "url": "https://example.test/fx"}]}),
    result("translation", {"source_text": "Depart from the north gate.", "translated_text": "从北门出发。"}),
    result("rag_knowledge", {"answer": "查看会议中心的说明。", "sources": [
        {"document": "展会手册", "content": "请携带证件，通过北门安检。", "similarity": .92}]}),
    result("preference", {"preferences": [{"type": "seat_preference", "value": "靠窗", "action": "set"}]}),
]


def stream(emit, _):
    emit("complete", {"status": "completed", "results": RESULTS})


def run(browser, assets):
    with preview(assets, chat_script=stream, get_fixture=lambda path: {"enabled": False}
                 if path == "/api/personal/capabilities" else None) as (base, posted, _):
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        errors = []
        page = guarded_page(ctx, errors)
        page.add_init_script("""Object.defineProperty(navigator,'clipboard',{value:{
            writeText: v => window.allowClipboard ? (window.copiedText=v,Promise.resolve()) : Promise.reject(new Error('denied'))
        }});""")
        plugin_reads, plugin_writes = [], []
        def plugin(route):
            if route.request.method == "GET":
                plugin_reads.append(1)
                if len(plugin_reads) == 1:
                    return route.fulfill(status=503, json={"error": "temporary"})
                return route.fulfill(json={"plugins": [{"name": "plan-trip", "enabled": True, "loaded": True}]})
            plugin_writes.append(route.request.post_data_json)
            return route.fulfill(status=503, json={"error": "temporary"})
        page.route("**/api/plugins", plugin)
        page.goto(base, wait_until="networkidle")
        page.get_by_role("textbox", name="输入消息").fill("核对差旅资料")
        page.get_by_role("button", name="开始规划").click()
        expect(page.get_by_role("region", name="事项简报")).to_contain_text("缺少信息：出发日期")
        fx = page.get_by_role("region", name="汇率回执")
        expect(fx).to_contain_text("汇率日期 2026-11-21")
        expect(fx).to_contain_text("72.00 CNY")
        expect(fx.get_by_role("link", name="参考汇率")).to_have_attribute("href", "https://example.test/fx")
        translation = page.get_by_role("region", name="翻译回执")
        expect(translation).to_contain_text("从北门出发。")
        translation.get_by_role("button", name="复制译文").click()
        expect(translation.get_by_role("status")).to_contain_text("未能复制")
        page.evaluate("window.allowClipboard=true")
        translation.get_by_role("button", name="复制译文").click()
        expect(translation.get_by_role("status")).to_have_text("已复制译文")
        assert page.evaluate("window.copiedText") == "从北门出发。"
        knowledge = page.get_by_role("region", name="KNOWLEDGE")
        expect(knowledge.get_by_text("展会手册", exact=True).first).to_be_visible()
        expect(knowledge).not_to_contain_text("相似度")
        knowledge.get_by_role("button", name="来源文档", exact=False).click()
        expect(knowledge).to_contain_text("通过北门安检")
        expect(page.get_by_role("region", name="偏好回执")).to_contain_text("保存不等于授权")
        page.get_by_role("button", name="展开行程档案").click()
        page.get_by_role("tab", name="插件").click()
        expect(page.get_by_role("alert")).to_contain_text("暂时无法读取插件状态")
        page.get_by_role("button", name="重新读取插件状态").click()
        toggle = page.get_by_role("switch", name="禁用 行程规划")
        expect(toggle).to_have_attribute("aria-checked", "true")
        toggle.click()
        expect(page.get_by_role("alert")).to_contain_text("保持上次已知状态")
        expect(toggle).to_have_attribute("aria-checked", "true")
        page.get_by_role("tab", name="费用").click()
        expect(page.get_by_role("link", name="查看完整账本")).to_have_count(0)
        assert len(plugin_writes) == 1
        assert [path for path, _ in posted if path.startswith("/api/chat")] == ["/api/chat"]
        assert_no_overflow(page)
        assert not errors, errors
        ctx.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--chromium-exe", type=Path)
    args = parser.parse_args()
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=args.chromium_exe, args=["--disable-background-networking"])
        run(browser, args.assets.resolve())
        browser.close()
    print("事项、汇率、翻译、知识、偏好与档案故障状态回归通过。")


if __name__ == "__main__":
    main()
