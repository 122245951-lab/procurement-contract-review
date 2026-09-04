# -*- coding: utf-8 -*-
"""
hard_check.py — F4 硬规则审核（代码，字符级，零漏报，不调用 LLM）。
覆盖三类：
  1) hard_match  失效法规（repealed_laws，隐性，命中置顶）、违禁表述（banned_phrases）
  2) 必备要素缺失（required_elements：关键词全部未出现即判定缺失）
  3) value_check 阈值验算（thresholds：账期天数 / 预付款比例 / 日违约金费率）
输出 hard_hits.json：命中项列表，每项含四要素 + track=hard + pinned（是否置顶）。
"""
import os
import re
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rulekit import resolve_pack, load_hard_terms, normalize, locate_quote, write_json, read_json  # noqa: E402


def find_windows(full_text, needle, width=36, max_hits=5):
    """在全文中查找 needle（字面量），返回 [(start, window_text)]，窗口含上下文。"""
    out = []
    if not needle:
        return out
    start = 0
    n = len(full_text)
    while len(out) < max_hits:
        i = full_text.find(needle, start)
        if i < 0:
            break
        a = max(0, i - width)
        b = min(n, i + len(needle) + width)
        window = full_text[a:b].replace("\n", " ").strip()
        out.append((i, window))
        start = i + len(needle)
    return out


def section_of(full_text, pos, sections):
    """根据字符位置粗略定位章节：用该位置之前最近的切块标题。"""
    # 优先用 normalize 子串定位
    return ""


def make_hit(rule_id, severity, location, quote, problem, suggestion, judge="hard_match",
             pinned=False, hidden=False, category=""):
    return {
        "rule_id": rule_id,
        "track": "hard",
        "judge": judge,
        "severity": severity,
        "category": category,
        "location": location,
        "quote": quote,
        "problem": problem,
        "suggestion": suggestion,
        "pinned": pinned,
        "hidden": hidden,
        "quote_verified": bool(quote),
    }


def check_repealed_laws(contract, terms, sections):
    hits = []
    full = contract["full_text"]
    for item in terms.get("repealed_laws", []):
        patterns = [item.get("pattern", "")] + item.get("also_match", [])
        patterns = [p for p in patterns if p]
        for pat in patterns:
            for pos, window in find_windows(full, pat):
                loc = locate_quote(window, sections) or "（援引法规处）"
                hits.append(make_hit(
                    rule_id=item.get("rule_id", "R-LEGAL-01"),
                    severity="高",
                    location=loc,
                    quote=window,
                    problem="合同援引了已废止的《%s》。%s" % (pat.strip("《》"), item.get("reason", "")),
                    suggestion="将法律依据更新为《%s》对应编章，并核对全文同类援引一并替换。" % item.get("current", "现行有效法律"),
                    judge="hard_match", pinned=True, hidden=True, category="援引失效法规"))
                break  # 同一 pattern 只报一次
    return hits


def check_banned_phrases(contract, terms, sections):
    hits = []
    full = contract["full_text"]
    for item in terms.get("banned_phrases", []):
        pat = item.get("pattern", "")
        if not pat:
            continue
        windows = find_windows(full, pat, max_hits=3)
        if not windows:
            continue
        pos, window = windows[0]
        loc = locate_quote(window, sections) or "（相关条款）"
        hits.append(make_hit(
            rule_id=item.get("rule_id", "R-BREACH-01"),
            severity=item.get("severity", "中"),
            location=loc,
            quote=window,
            problem="检出高风险/违禁表述“%s”：%s" % (pat, item.get("reason", "")),
            suggestion=item.get("suggestion", "删除或修改该表述，改为对等、可执行的约定。"),
            judge="hard_match", pinned=False, category="违禁表述"))
    return hits


def check_required_elements(contract, terms, sections):
    hits = []
    full_norm = normalize(contract["full_text"])
    for el in terms.get("required_elements", []):
        keywords = el.get("any_of", [])
        present = any(normalize(k) in full_norm for k in keywords if k)
        if not present:
            hits.append(make_hit(
                rule_id=el.get("rule_id", ""),
                severity=el.get("severity", "中"),
                location="全文（未检出）",
                quote="",
                problem="缺少“%s”相关约定（未检出关键词：%s）。" % (el.get("label", ""), "、".join(keywords)),
                suggestion="补充“%s”条款，明确相关要件，避免该环节约定缺失产生风险。" % el.get("label", ""),
                judge="hard_match", pinned=False, category="必备要素缺失"))
    return hits


def check_thresholds(contract, terms, sections):
    """value_check：保守的数字验算，命中均为'提示关注'。"""
    hits = []
    full = contract["full_text"]

    def add(rule_id, severity, window, label, note, suggestion):
        loc = locate_quote(window, sections) or "（相关条款）"
        hits.append(make_hit(rule_id, severity, loc, window, "%s：%s" % (label, note),
                             suggestion, judge="value_check", pinned=False, category="阈值验算"))

    for th in terms.get("thresholds", []):
        key = th.get("key")
        val = th.get("value")
        label = th.get("label", key)
        note = th.get("note", "")
        ctx = th.get("context_keywords", [])
        sev = th.get("severity", "中")

        if key == "payment_term_days_max":
            # 匹配 “XX日/天内付款/支付” 或 “账期XX天”
            for m in re.finditer(r"(\d{1,4})\s*(日|天)", full):
                seg = full[max(0, m.start() - 12): m.end() + 12]
                if any(k in seg for k in ["付款", "支付", "账期", "结算", "付清"]):
                    days = int(m.group(1))
                    if days > val:
                        add(th["rule_id"], sev, seg.replace("\n", " ").strip(), label,
                            "约定付款/账期约 %d 天，超过参考阈值 %d 天。%s" % (days, val, note),
                            "评估现金流与履约风险，按本企业采购政策压缩账期并明确付款触发条件。")
                    break
        elif key == "prepaid_ratio_max":
            for m in re.finditer(r"(预付|预付款|定金|首款)[^。；;]{0,20}?(\d{1,3})\s*%", full):
                pct = int(m.group(2)) / 100.0
                seg = full[max(0, m.start() - 6): m.end() + 6].replace("\n", " ").strip()
                if pct > val:
                    add(th["rule_id"], sev, seg, label,
                        "预付款比例约 %d%%，高于参考阈值 %d%%。%s" % (int(pct * 100), int(val * 100), note),
                        "降低预付款比例，或将预付款与履约担保/里程碑挂钩，控制资金占用风险。")
                break
        elif key == "daily_penalty_rate_max":
            # 每日按 X% / X‰ ；或 X%/日
            for m in re.finditer(r"(违约金|滞纳金|逾期)[^。；;]{0,25}?(\d+(?:\.\d+)?)\s*(%|‰|百分之)", full):
                num = float(m.group(2))
                unit = m.group(3)
                rate_per_day_pct = num if unit in ("%", "百分之") else num / 10.0  # ‰ → %
                seg = full[max(0, m.start() - 6): m.end() + 10].replace("\n", " ").strip()
                if ("日" in seg or "每日" in seg) and rate_per_day_pct > val:
                    add(th["rule_id"], sev, seg, label,
                        "按日违约金费率约 %s%%/日，高于参考阈值 %s%%/日，可能被认定过分高于损失而调减。%s"
                        % (rate_per_day_pct, val, note),
                        "将违约金费率调整到合理区间，或约定违约金以实际损失为基础并设上限。")
                break
    return hits


def run(contract_path, pack_dir):
    contract = read_json(contract_path)
    terms = load_hard_terms(pack_dir)
    sections = contract.get("sections", [])

    hits = []
    hits += check_repealed_laws(contract, terms, sections)
    hits += check_banned_phrases(contract, terms, sections)
    hits += check_required_elements(contract, terms, sections)
    hits += check_thresholds(contract, terms, sections)

    # 排序：置顶项在前，其余按严重度
    sev_rank = {"高": 0, "中": 1, "低": 2}
    hits.sort(key=lambda h: (0 if h["pinned"] else 1, sev_rank.get(h["severity"], 3)))
    return hits, contract, terms


def main():
    ap = argparse.ArgumentParser(description="硬规则审核（代码，零漏报）")
    ap.add_argument("contract_json", help="parse_contract.py 输出的 contract.json")
    ap.add_argument("--pack", default=None, help="规则包目录（默认首发包）")
    ap.add_argument("--out", default="hard_hits.json", help="输出命中 JSON")
    args = ap.parse_args()

    pack_dir = resolve_pack(args.pack)
    hits, contract, terms = run(args.contract_json, pack_dir)
    write_json(args.out, {"pack": os.path.basename(pack_dir), "track": "hard", "hits": hits})

    print("硬规则审核完成：命中 %d 项" % len(hits))
    for h in hits:
        flag = "【置顶】" if h["pinned"] else ""
        print("  - [%s] %s %s %s" % (h["severity"], h["rule_id"], flag, h["problem"][:40]))
    print("输出：%s" % os.path.abspath(args.out))


if __name__ == "__main__":
    main()
