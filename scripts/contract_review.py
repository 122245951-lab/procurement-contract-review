# -*- coding: utf-8 -*-
"""
contract_review.py — 一键编排（F1/F2 解析 → F4 硬规则 → F7 报告）。
F5 语义规则由 LLM（助手）按 references/LLM_SEMANTIC_PROMPT.md 完成，结果存为 llm_hits.json，
用 --llm 传入即合并进报告；不传则报告只含硬规则 + 必备要素/阈值结果（语义规则列为"待评审/未发现"）。

用法：
  python contract_review.py <合同文件> [--pack 规则包] [--llm llm_hits.json] [--outdir 输出目录]
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rulekit import resolve_pack, write_json  # noqa: E402
import parse_contract as pc  # noqa: E402
import hard_check as hc  # noqa: E402
import render_report as rr  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="采购合同审核一键编排")
    ap.add_argument("contract", help="合同文件（.docx/.pdf/.txt）")
    ap.add_argument("--pack", default=None, help="规则包目录（默认首发包）")
    ap.add_argument("--llm", default=None, help="LLM 语义命中 JSON（可选）")
    ap.add_argument("--outdir", default=None, help="输出目录（默认 ./review_output）")
    args = ap.parse_args()

    pack_dir = resolve_pack(args.pack)
    outdir = args.outdir or os.path.join(os.getcwd(), "review_output")
    os.makedirs(outdir, exist_ok=True)

    # F1/F2 解析切块
    contract = pc.parse(args.contract)
    cpath = os.path.join(outdir, "contract.json")
    write_json(cpath, contract)
    print("[1/3] 解析完成：%s｜%d 字｜%d 块" % (contract["title"], contract["char_count"], contract["section_count"]))

    # F4 硬规则
    hits, _, _ = hc.run(cpath, pack_dir)
    hpath = os.path.join(outdir, "hard_hits.json")
    write_json(hpath, {"pack": os.path.basename(pack_dir), "track": "hard", "hits": hits})
    print("[2/3] 硬规则审核：命中 %d 项" % len(hits))

    # F7 报告（合并可选 LLM 结果）
    llm_hits = rr.load_hits(args.llm) if args.llm else []
    if args.llm:
        print("       载入 LLM 语义命中 %d 项" % len(llm_hits))
    out_html = os.path.join(outdir, "合同审核报告.html")
    info = rr.build_report(contract, hits, llm_hits, pack_dir, out_html)
    print("[3/3] 报告已生成：%s" % info["out"])
    print("      命中 %d（高%d/中%d/低%d）｜未发现问题 %d 项" %
          (info["hits"], info["high"], info["mid"], info["low"], info["unchecked"]))
    print("\n提示：语义规则（rule_check/semantic）需由 LLM 评审后经 --llm 合并；")
    print("      规则包自检：python scripts/validate_rules.py --pack \"%s\" --lint --test" % pack_dir)


if __name__ == "__main__":
    main()
