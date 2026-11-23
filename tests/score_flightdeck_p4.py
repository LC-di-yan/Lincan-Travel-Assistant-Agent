"""Apply the predeclared P4 gate to real, anonymized study exports."""
import argparse
import json
from pathlib import Path
from statistics import median


def evaluate(rows):
    arms = {"a": [], "b": []}
    seen = set()
    for row in rows:
        trial, arm = row["trial"], row["arm"]
        if not isinstance(trial, str) or not trial or trial in seen or arm not in arms:
            raise ValueError("结果编号应唯一，且分组必须为 a 或 b。")
        seen.add(trial)
        if not row.get("motion_eligible"):
            continue
        start, understand, score = row["first_submit_ms"], row["understood_ms"], row["quiz_correct"]
        if type(start) is not int or start <= 0 or type(score) is not int or not 0 <= score <= 2:
            raise ValueError("请求时间或答题分数不合法。")
        # Keep non-exposed B participants: choosing to hover is itself part of normal use.
        arms[arm].append((start, understand if type(understand) is int and 0 <= understand <= start else None,
                          score == 2, row["motion_exposed"] is True))
    summaries = {}
    for arm, group in arms.items():
        understood = [row[1] for row in group if row[1] is not None]
        summaries[arm] = {
            "人数": len(group),
            "第一条提交中位_ms": median(row[0] for row in group) if group else None,
            "理解标记中位_ms": median(understood) if understood else None,
            "有有效理解标记人数": len(understood),
            "两题均对人数": sum(row[2] for row in group),
            "实际见到视差人数": sum(row[3] for row in group),
        }
    a, b = summaries["a"], summaries["b"]
    sufficient = all(group["人数"] >= 5 and group["人数"] == group["有有效理解标记人数"] for group in (a, b))
    gate = False
    if sufficient:
        score_a, score_b = (group["两题均对人数"] / group["人数"] for group in (a, b))
        gate = max(.8, score_a) <= score_b and b["实际见到视差人数"] > 0 and all(
            a[key] > 0 and b[key] <= .85 * a[key] for key in ("第一条提交中位_ms", "理解标记中位_ms")
        )
    return {"样本齐全": sufficient, "分组": summaries,
            "结论": "通过小样本定量门，仍需复核误触与性能，不自动启用" if gate else "未通过启用门：保留静态"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path, nargs="*", help="参与者主动导出的 JSON，不接受机器演练数据")
    args = parser.parse_args()
    rows = [json.loads(file.read_text("utf-8-sig")) for file in args.files]
    print(json.dumps(evaluate(rows), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
