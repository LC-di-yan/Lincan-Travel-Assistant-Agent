# -*- coding: utf-8 -*-
"""
RAG 检索技术离线对比实验（experiments/rag_lab）

目的：用项目真实知识库（.claude/skills/ask-question/data/documents/*.txt）
对比不同检索技术的召回质量，为 docs/rag-upgrade-research-2026.md 的结论提供实测证据。

  A naive+dense         现状基线（现有切块 + bge-small-zh 纯向量）
  B naive+dense+instr   仅加 bge 官方 query 指令前缀（零成本改动）
  C naive+bm25          jieba + BM25 纯词面检索
  D naive+hybrid_rrf    dense + BM25 倒数排名融合
  E/F struct+hybrid     结构化切块（标题路径）+ hybrid，并评测 parent 上下文覆盖

全部离线运行，不改动主程序，不写 Milvus。依赖本机已装的
sentence-transformers / jieba / rank-bm25 / numpy。
"""
import json
import re
import time
from pathlib import Path

DOC_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "ask-question" / "data" / "documents"
MODEL_ID = "BAAI/bge-small-zh-v1.5"

H1 = re.compile(r"^[一二三四五六七八九十]+、")
H2 = re.compile(r"^\s*(\d+)\.\s*\S+")
QA = re.compile(r"^Q\d+\s*[:：]")
BULLET = re.compile(r"^\s*(?:[-•]|\(?[a-h]\)|\d+\))")


def _clean(s):
    return re.sub(r"\s+", "", s)


def _no_ws(t):
    return re.sub(r"\s+", " ", t)


def chunk_naive(text, max_chars=600):
    """复刻 init_knowledge_base.py 的 split_text（段落累加，无标题上下文）。"""
    paragraphs, cur = [], []
    for line in text.split("\n"):
        if line.strip() == "":
            if cur:
                paragraphs.append("\n".join(cur))
                cur = []
        else:
            cur.append(line)
    if cur:
        paragraphs.append("\n".join(cur))
    chunks, buf = [], ""
    for p in paragraphs:
        if len(buf) + len(p) <= max_chars:
            buf += ("\n\n" + p) if buf else p
        else:
            if buf:
                chunks.append(buf.strip())
            if len(p) > max_chars:
                rem = p
                while len(rem) > max_chars:
                    chunks.append(rem[:max_chars])
                    rem = rem[max_chars - 100:]
                buf = rem
            else:
                buf = p
    if buf:
        chunks.append(buf.strip())
    return [c for c in chunks if c]


def chunk_struct(text, max_chars=420, fine=260):
    """结构化切块：单元文本自带「文档标题｜章节｜小节」路径；parent = 所属小节全文。"""
    lines = [l.rstrip() for l in text.split("\n")]
    title = next((l.strip() for l in lines if l.strip()), "")
    blocks, cur = [], []
    h1, h2 = "", ""

    def flush():
        if not cur:
            return
        body = "\n".join(cur).strip()
        if body:
            path = "｜".join([p for p in (title, h1, h2) if p])
            blocks.append({"path": path, "body": body})
        cur.clear()

    for l in lines:
        s = l.strip()
        if not s:
            continue
        if H1.match(s):
            flush(); h1, h2 = s, ""; cur.append(s)
        elif H2.match(s) and not BULLET.match(l):
            flush(); h2 = s; cur.append(s)
        elif QA.match(s):
            flush(); cur.append(s)
        else:
            cur.append(l)
            if sum(len(x) for x in cur) > (fine if not h2 else max_chars):
                flush()
    flush()

    order, section_buf = [], {}
    for b in blocks:
        if b["path"] not in section_buf:
            section_buf[b["path"]] = []
            order.append(b["path"])
        section_buf[b["path"]].append(b["body"])

    out = []
    for key in order:
        section = "\n\n".join(section_buf[key])
        for b in blocks:
            if b["path"] != key:
                continue
            unit = b["path"] + "\n" + b["body"]
            if len(unit) > max_chars:
                piece = ""
                for ln in unit.split("\n"):
                    if len(piece) + len(ln) > max_chars and piece:
                        out.append({"text": piece.strip(), "parent": section}); piece = ""
                    piece += ln + "\n"
                if piece.strip():
                    out.append({"text": piece.strip(), "parent": section})
            else:
                out.append({"text": unit, "parent": section})
    return out


def build_corpus():
    naive, struct = [], []
    for p in sorted(DOC_DIR.glob("*.txt")):
        text = p.read_text(encoding="utf-8")
        for i, c in enumerate(chunk_naive(text)):
            naive.append({"id": p.stem + "#n" + str(i), "file": p.name, "text": c})
        for i, c in enumerate(chunk_struct(text)):
            struct.append({"id": p.stem + "#s" + str(i), "file": p.name, "text": c["text"], "parent": c["parent"]})
    return naive, struct


def load_embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_ID, local_files_only=True)


BGE_INSTR = "为这个句子生成表示以用于检索相关文章："


def embed(model, texts, batch_size=64):
    import numpy as np
    v = model.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(v, dtype="float32")


def bm25_index(texts):
    import jieba
    jieba.setLogLevel(60)
    for t in texts:
        jieba.lcut(t[:20])
    tok = [list(jieba.lcut(_no_ws(t))) for t in texts]
    from rank_bm25 import BM25Okapi
    return BM25Okapi(tok), jieba


def rank_dense(qv, cv):
    sims = cv @ qv
    return sorted(range(len(sims)), key=lambda i: -sims[i])


def rank_bm25(q, bm, jb, n):
    s = bm.get_scores(list(jb.lcut(_no_ws(q))))
    return sorted(range(n), key=lambda i: -s[i])


def rrf(rank_lists, k=60):
    score = {}
    for ranks in rank_lists:
        for r, idx in enumerate(ranks):
            score[idx] = score.get(idx, 0.0) + 1.0 / (k + r + 1)
    return sorted(score, key=lambda i: -score[i])


QUERIES = [
    ("一线城市出差住宿标准是多少", "不超过500元/晚", "01_travel_standards.txt"),
    ("杭州住宿费上限是多少", "不超过400元/晚", "01_travel_standards.txt"),
    ("三线城市住宿标准", "不超过300元/晚", "01_travel_standards.txt"),
    ("高铁可以坐商务座吗", "可申请商务座", "01_travel_standards.txt"),
    ("国际长途航班能坐什么舱位", "高端经济舱", "01_travel_standards.txt"),
    ("出差申请要提前几天提交", "至少3个工作日", "01_travel_standards.txt"),
    ("机票提前多久订比较便宜", "建议提前7-14天预订", "03_booking_guide.txt"),
    ("国际机票建议提前多久订", "建议提前21-30天预订", "03_booking_guide.txt"),
    ("商旅平台客服电话是多少", "400-800-8888", "03_booking_guide.txt"),
    ("在线值机什么时候开放", "起飞前24小时开放", "03_booking_guide.txt"),
    ("报销要在多长时间内提交", "30个自然日内提交报销申请", "02_reimbursement_policy.txt"),
    ("12月出差最晚什么时候报销", "次年1月15日", "02_reimbursement_policy.txt"),
    ("发票抬头要开成什么", "阿里巴巴（中国）有限公司", "02_reimbursement_policy.txt"),
    ("火车票丢了怎么报销", "报销凭证", "02_reimbursement_policy.txt"),
    ("住宿发票需要什么类型", "增值税发票", "02_reimbursement_policy.txt"),
    ("航班延误多久可以考虑改签", "超过4小时", "05_emergency_procedures.txt"),
    ("航班取消了该怎么处理", "了解取消原因和退改方案", "05_emergency_procedures.txt"),
    ("延误证明向谁索取", "向航空公司或机场索取", "05_emergency_procedures.txt"),
    ("出差申请被驳回了怎么办", "查看驳回原因", "04_faq.txt"),
    ("临时要延长出差时间怎么办", "行程变更申请", "04_faq.txt"),
    ("可以自己开私家车出差吗", "油费、过路费、停车费", "04_faq.txt"),
    ("出差打车有什么规定", "允许打车的场景", "04_faq.txt"),
    ("首都机场离市中心多远", "距市中心约25公里", "07_city_specific_tips.txt"),
    ("北京出租车起步价是多少", "起步价14元", "07_city_specific_tips.txt"),
    ("大兴机场线到草桥要几分钟", "20分钟到草桥", "07_city_specific_tips.txt"),
    ("多少公里以内优先坐高铁", "优先选择高铁", "08_environmental_initiatives.txt"),
    ("高铁比飞机碳排放低多少", "碳排放量降低约90%", "08_environmental_initiatives.txt"),
    ("阿里商旅平台网址是什么", "travel.alibaba.com", "06_platform_guide.txt"),
]


def evaluate(orders, corpus, key="text"):
    n = len(QUERIES)
    hits = {1: 0, 3: 0, 5: 0}
    rr, detail = 0.0, []
    for (q, ev, f), order in zip(QUERIES, orders):
        clean_ev = _clean(ev)
        first = None
        for r, idx in enumerate(order[:10]):
            if clean_ev in _clean(corpus[idx].get(key, "")):
                first = r
                break
        for k in hits:
            if first is not None and first < k:
                hits[k] += 1
        rr += (1.0 / (first + 1)) if first is not None else 0.0
        detail.append({"query": q, "gold": f, "rank": (first + 1) if first is not None else None})
    return {"hit@1": round(hits[1] / n, 3), "hit@3": round(hits[3] / n, 3), "hit@5": round(hits[5] / n, 3),
            "mrr": round(rr / n, 3), "misses": [d["query"] for d in detail if d["rank"] is None]}, detail


def main():
    naive, struct = build_corpus()
    def avg(xs): return sum(xs) // max(len(xs), 1)
    print("corpus naive=%d units avg=%d chars | struct=%d units avg=%d chars parent avg=%d chars" % (
        len(naive), avg([len(c["text"]) for c in naive]), len(struct),
        avg([len(c["text"]) for c in struct]), avg([len(c["parent"]) for c in struct])))

    t0 = time.time(); model = load_embedder(); load_s = round(time.time() - t0, 1)
    results = {}
    for name, corpus in (("naive", naive), ("struct", struct)):
        texts = [c["text"] for c in corpus]
        cv = embed(model, texts)
        bm, jb = bm25_index(texts)
        dense, dense_instr, bm25, hyb = [], [], [], []
        qms = 0.0
        for q, ev, f in QUERIES:
            t1 = time.time()
            qv = embed(model, [q]); qd = embed(model, [BGE_INSTR + q])
            qms += (time.time() - t1) * 1000 / 2
            do = rank_dense(qv[0], cv); di = rank_dense(qd[0], cv); bo = rank_bm25(q, bm, jb, len(corpus))
            dense.append(do); dense_instr.append(di); bm25.append(bo); hyb.append(rrf([do, bo]))
        for tag, orders in (("A_dense", dense), ("B_dense_instr", dense_instr), ("C_bm25", bm25), ("D_hybrid_rrf", hyb)):
            m, detail = evaluate(orders, corpus)
            m["query_encode_ms"] = round(qms, 1)
            results[tag + "|" + name] = m
            if m["hit@3"] < 1.0:
                results["misses|" + tag + "|" + name] = m["misses"]
        m, _ = evaluate(hyb, corpus, "parent")
        m["query_encode_ms"] = round(qms, 1)
        results["E_hybrid_parentctx|" + name] = m
        if m["hit@3"] < 1.0:
            results["misses|E_parent|" + name] = m["misses"]
    print("model_load_s=", load_s)
    print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
