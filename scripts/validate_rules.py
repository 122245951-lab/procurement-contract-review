# -*- coding: utf-8 -*-
"""
validate_rules.py — F9 规则包自检（--lint）与回归测试（--test）。
--lint：校验 manifest 字段、规则文件 frontmatter 完整性、规则 id 一致、hard_terms.json 合法性。
        缺字段即报错并定位到具体文件（退出码非 0）。
--test：跑 tests/*.json 回归集。
        - 判定方式为 hard_match / value_check 的规则：用 hard_check 真实判定，正例应命中、反例不应命中。
        - 判定方式为 rule_check / semantic 的规则：本脚本不调 LLM，校验样例格式并标记"待 LLM 评审"，
          由 SKILL 编排流程在实际审核时由模型判定（防止无模型环境下假通过）。
"""
import os
import re
import sys
import json
import argparse
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rulekit import resolve_pack, load_manifest, load_hard_terms, list_rules, rule_meta_from_manifest, write_json  # noqa: E402
import hard_check  # noqa: E402

REQUIRED_FRONT = ["规则编码", "规则分类", "判定方式", "严重度", "状态"]
VALID_JUDGE = {"hard_match", "value_check", "rule_check", "semantic"}
VALID_SEV = {"高", "中", "低"}
VALID_STATUS = {"active", "draft"}


def parse_frontmatter(md_text):
    """提取规则 md 头部 '- 字段：值' 形式的元数据。"""
    meta = {}
    for line in md_text.splitlines()[:30]:
        m = re.match(r"^-\s*([^：:]+)[：:]\s*(.*)$", line.strip())
        if m:
            meta[m.group(1).strip()] = m.group(2).strip()
    return meta


def lint(pack_dir):
    errors = []
    warnings = []
    print("=" * 60)
    print("规则包自检：%s" % pack_dir)
    print("=" * 60)

    # 1. manifest
    try:
        man = load_manifest(pack_dir)
    except Exception as e:
        errors.append("manifest.yaml 读取失败：%s" % e)
        man = {"pack": {}, "rules": []}
    pack = man.get("pack", {})
    for k in ("name", "version", "effective_date", "scope"):
        if not pack.get(k):
            errors.append("manifest.yaml 缺少 pack.%s" % k)
    print("[manifest] 包名：%s  版本：%s  生效：%s" %
          (pack.get("name"), pack.get("version"), pack.get("effective_date")))

    rules_meta = rule_meta_from_manifest(man)
    if not rules_meta:
        errors.append("manifest.yaml 未列出任何 rules")

    # 2. hard_terms.json
    terms_path = os.path.join(pack_dir, "hard_terms.json")
    if not os.path.exists(terms_path):
        warnings.append("hard_terms.json 不存在（将无硬规则词表）")
        terms = {}
    else:
        try:
            terms = load_hard_terms(pack_dir)
            json.dumps(terms, ensure_ascii=False)
            print("[hard_terms] 失效法规 %d｜违禁表述 %d｜必备要素 %d｜阈值 %d" % (
                len(terms.get("repealed_laws", [])), len(terms.get("banned_phrases", [])),
                len(terms.get("required_elements", [])), len(terms.get("thresholds", []))))
        except Exception as e:
            errors.append("hard_terms.json 解析失败：%s" % e)
            terms = {}

    # 3. 每条规则文件
    rule_files = list_rules(pack_dir)
    file_ids = set()
    for rf in rule_files:
        rel = os.path.relpath(rf, pack_dir)
        with open(rf, "r", encoding="utf-8") as f:
            txt = f.read()
        meta = parse_frontmatter(txt)
        rid = meta.get("规则编码", "")
        if not rid:
            errors.append("%s 缺少 frontmatter『规则编码』" % rel)
            continue
        file_ids.add(rid)
        for field in REQUIRED_FRONT:
            if field not in meta or not meta[field]:
                errors.append("%s 缺少字段『%s』" % (rel, field))
        # 判定方式取枚举首词（允许 "semantic（LLM 语义理解）" 这类带说明的写法）
        if meta.get("判定方式"):
            meta["判定方式"] = meta["判定方式"].strip()
            for j in VALID_JUDGE:
                if meta["判定方式"].startswith(j):
                    meta["判定方式"] = j
                    break
        if meta.get("严重度"):
            meta["严重度"] = meta["严重度"].strip()[:1]  # 取“高/中/低”首字
        if meta.get("状态"):
            st = meta["状态"].strip()
            meta["状态"] = "active" if st.startswith(("active", "生效", "a")) else ("draft" if st.startswith(("draft", "草稿", "d")) else st)
        if meta.get("判定方式") and meta["判定方式"] not in VALID_JUDGE:
            errors.append("%s 判定方式非法：%s（应为 %s）" % (rel, meta["判定方式"], "/".join(VALID_JUDGE)))
        if meta.get("严重度") and meta["严重度"] not in VALID_SEV:
            errors.append("%s 严重度非法：%s" % (rel, meta["严重度"]))
        if meta.get("状态") and meta["状态"] not in VALID_STATUS:
            errors.append("%s 状态非法：%s（应为 active/draft）" % (rel, meta["状态"]))
        # manifest 一致性
        if rid not in rules_meta:
            warnings.append("%s（%s）在 manifest.yaml 中未登记" % (rel, rid))
        else:
            mm = rules_meta[rid]
            if mm.get("judge") and meta.get("判定方式") and mm["judge"] != meta["判定方式"]:
                errors.append("%s 判定方式不一致：manifest=%s vs 文件=%s" % (rel, mm.get("judge"), meta.get("判定方式")))

    # manifest 登记但文件缺失
    for rid in rules_meta:
        if rid not in file_ids:
            errors.append("manifest 登记了 %s 但 rules/ 下无对应文件" % rid)

    print("[rules] 规则文件 %d 个：%s" % (len(rule_files), "、".join(sorted(file_ids)) or "无"))

    # 4. tests 目录
    tests_dir = os.path.join(pack_dir, "tests")
    test_files = sorted([f for f in os.listdir(tests_dir) if f.endswith(".json")]) if os.path.isdir(tests_dir) else []
    if not test_files:
        warnings.append("tests/ 目录无回归测试文件")
    else:
        print("[tests] 回归测试文件 %d 个：%s" % (len(test_files), "、".join(test_files)))

    # 汇总
    print("-" * 60)
    for w in warnings:
        print("  ⚠️  %s" % w)
    if errors:
        for e in errors:
            print("  ❌ %s" % e)
        print("自检结果：%d 个错误，%d 个警告 —— 请修复错误后再审核。" % (len(errors), len(warnings)))
        return 1
    print("自检结果：通过 ✅（%d 个警告）" % len(warnings))
    return 0


def _synth_contract(text, tmpdir):
    """把一段测试文本包装成 contract.json，供 hard_check 使用。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import parse_contract as pc
    sections = pc.split_sections(text)
    contract = {"file": "test-case", "kind": "txt", "title": "测试用例",
                "full_text": text, "char_count": len(text),
                "section_count": len(sections), "sections": sections}
    p = os.path.join(tmpdir, "contract.json")
    write_json(p, contract)
    return p


def run_tests(pack_dir):
    tests_dir = os.path.join(pack_dir, "tests")
    if not os.path.isdir(tests_dir):
        print("tests/ 目录不存在，跳过回归。")
        return 0
    test_files = sorted(os.path.join(tests_dir, f) for f in os.listdir(tests_dir) if f.endswith(".json"))
    man = load_manifest(pack_dir)
    rules_meta = rule_meta_from_manifest(man)

    total = passn = failn = skipn = 0
    failures = []
    tmpdir = tempfile.mkdtemp(prefix="pcr_test_")

    for tf in test_files:
        with open(tf, "r", encoding="utf-8") as f:
            data = json.load(f)
        for case in data.get("cases", []):
            total += 1
            rid = case.get("rule_id", data.get("rule_id", ""))
            judge = (rules_meta.get(rid, {}) or {}).get("judge", "")
            expect = bool(case.get("expect_hit"))
            name = case.get("name", "")
            text = case.get("text", "")
            # 显式声明走代码轨道（违禁词/必备要素/阈值等 hard_check 可判定项），即使该规则主判定方式为语义
            force_hard = (case.get("track") == "hard") or (data.get("track") == "hard")

            if judge in ("hard_match", "value_check") or force_hard:
                cpath = _synth_contract(text, tmpdir)
                hits, _, _ = hard_check.run(cpath, pack_dir)
                hit_rule_ids = {h["rule_id"] for h in hits}
                actual = rid in hit_rule_ids
                ok = (actual == expect)
                if ok:
                    passn += 1
                    print("  ✅ [%s/%s] %s（期望%s/实际%s）" % (rid, judge, name, "命中" if expect else "不误报", "命中" if actual else "未命中"))
                else:
                    failn += 1
                    failures.append((rid, name, expect, actual))
                    print("  ❌ [%s] %s（期望%s/实际%s）" % (rid, name, "命中" if expect else "不误报", "命中" if actual else "未命中"))
            else:
                # 语义规则：无模型环境不自动判定
                skipn += 1
                print("  ⏭️  [%s/%s] %s —— 待 LLM 评审（语义规则不在无模型环境自动判定）" % (rid, judge or "?", name))

    print("-" * 60)
    print("回归结果：共 %d 例｜自动判定通过 %d｜失败 %d｜待LLM %d" % (total, passn, failn, skipn))
    if failures:
        for rid, name, exp, act in failures:
            print("  失败：%s %s（期望命中=%s 实际=%s）" % (rid, name, exp, act))
        return 1
    print("硬规则回归：全部通过 ✅" if failn == 0 else "存在失败 ❌")
    return 0


def main():
    ap = argparse.ArgumentParser(description="规则包自检与回归测试")
    ap.add_argument("--pack", default=None, help="规则包目录")
    ap.add_argument("--lint", action="store_true", help="格式自检")
    ap.add_argument("--test", action="store_true", help="回归测试")
    args = ap.parse_args()

    pack_dir = resolve_pack(args.pack)
    rc = 0
    if args.lint or (not args.test):
        rc = lint(pack_dir) or rc
    if args.test:
        rc = run_tests(pack_dir) or rc
    sys.exit(rc)


if __name__ == "__main__":
    main()
