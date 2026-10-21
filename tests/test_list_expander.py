"""「列出来 / 全部 / 展开」追问的回归测试（不联网）。

背景：用户先查「明早北京去上海的高铁」，卡片只有前 3 趟；接着说「列出来」，
系统又跑了一次查询，仍然只有 3 趟。现在改成：记住上一轮列表结果，
「列出来」直接展开完整清单，不再调模型。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.utils.list_expander import (  # noqa: E402
    build_expand_payload,
    is_expand_request,
    remember_list_result,
)

TRAIN_DATA = {
    "query_type": "余票查询",
    "query_success": True,
    "answer": "北京→上海 (2026-10-22)；共15趟列车；G547 …",
    "results": {
        "summary": "北京→上海 (2026-10-22)；共15趟列车",
        "date": "2026-10-22",
        "from": "北京",
        "to": "上海",
        "total": 15,
        "trains": [
            {
                "train_no": f"G{547 + i}", "train_type": "高铁",
                "from_station": "北京南", "to_station": "上海虹桥",
                "depart_time": f"{6 + i:02d}:18", "arrive_time": f"{12 + i:02d}:11",
                "duration": "05:53", "second_class": "有", "first_class": "有", "business": "无",
            }
            for i in range(15)
        ],
    },
}


class _Focus:
    def __init__(self):
        self.last_list_result = None


class _Session:
    def __init__(self):
        self.focus_state = _Focus()


def test_expand_words_detected():
    for text in ("列出来", "列一下", "全部", "展开", "还有哪些车次", "全部列出来。"):
        assert is_expand_request(text), text
    for text in ("明早从北京去上海的高铁票有哪些", "查一下酒店", ""):
        assert not is_expand_request(text), text


def test_remember_keeps_latest_list_result():
    session = _Session()
    result_data = {"results": [{"agent_name": "train_ticket", "status": "success", "data": TRAIN_DATA}]}
    remember_list_result(session, result_data)
    assert session.focus_state.last_list_result["agent"] == "train_ticket"
    assert session.focus_state.last_list_result["data"]["results"]["total"] == 15


def test_remember_ignores_non_list_agents():
    session = _Session()
    remember_list_result(session, {"results": [{"agent_name": "translation", "status": "success", "data": {}}]})
    assert session.focus_state.last_list_result is None


def test_expand_payload_lists_every_train():
    session = _Session()
    remember_list_result(session, {"results": [{"agent_name": "train_ticket", "status": "success", "data": TRAIN_DATA}]})
    payload = build_expand_payload(session.focus_state.last_list_result)

    assert payload and payload["agent_name"] == "train_ticket"
    text = payload["data"]["answer"]
    assert "共 15 趟" in text
    for no in ("G547", "G561"):
        assert no in text, f"{no} 应该出现在完整清单里"
    # 结构化数据要保留，前端卡片才能渲染列表
    assert len(payload["data"]["results"]["trains"]) == 15
    assert payload["data"]["results"]["summary"] == text


def test_expand_payload_expires():
    item = {"agent": "train_ticket", "data": TRAIN_DATA, "ts": time.time() - 3600}
    assert build_expand_payload(item) is None


def test_expand_payload_none_when_empty():
    assert build_expand_payload(None) is None


def test_places_expand():
    data = {
        "results": {
            "hotels": [
                {"name": "一间森林青年旅舍", "rating": "4.9", "address": "天宝路888号"},
                {"name": "伍豪商务宾馆", "rating": "4.8", "address": "南奉公路343号"},
            ]
        }
    }
    payload = build_expand_payload({"agent": "hotel_search", "data": data, "ts": time.time()})
    text = payload["data"]["answer"]
    assert "共 2 个酒店" in text and "一间森林青年旅舍" in text
