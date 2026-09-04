# -*- coding: utf-8 -*-
"""
rulekit.py — 采购合同审核引擎公共库（纯 Python 标准库）。
负责：定位规则包、加载 manifest / hard_terms / 规则元数据、文本归一化、防幻觉检索。
引擎与规则包解耦：本文件不包含任何具体业务规则，全部规则来自规则包目录。
"""
import os
import re
import json
import glob

DEFAULT_PACK_NAME = "rules-pack-企业采购合同"


def skill_root():
    """skill 根目录（scripts 的上一级）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_pack(pack_arg=None):
    """把传入的规则包路径/名称解析为绝对目录。默认用 skill 自带首发包。"""
    if pack_arg:
        p = pack_arg
        if not os.path.isabs(p):
            # 相对路径：先相对 cwd，再相对 skill 根
            if os.path.isdir(p):
                p = os.path.abspath(p)
            else:
                cand = os.path.join(skill_root(), p)
                p = cand if os.path.isdir(cand) else os.path.abspath(pack_arg)
        return p
    return os.path.join(skill_root(), DEFAULT_PACK_NAME)


def _parse_scalar(v):
    v = v.strip()
    if v == "":
        return ""
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d*\.\d+", v):
        return float(v)
    return v.strip('"').strip("'")


def load_manifest(pack_dir):
    """极简 YAML 读取：仅解析本包 manifest 使用的结构（pack 标量 + rules 列表 + changelog 跳过）。
    不引入 PyYAML 依赖。rules 列表项为 dict。"""
    path = os.path.join(pack_dir, "manifest.yaml")
    data = {"pack": {}, "rules": []}
    if not os.path.exists(path):
        raise FileNotFoundError("manifest.yaml 不存在：%s" % path)
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    section = None  # 'pack' | 'rules' | 'changelog' | other
    current = None
    for raw in lines:
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        # 顶层键
        m_top = re.match(r"^([a-zA-Z_]+):\s*(.*)$", line)
        if m_top and not line.startswith(" "):
            key = m_top.group(1)
            val = m_top.group(2)
            # 切换 section 前，先把 rules 列表最后一项落盘（否则最后一条规则会丢）
            if section == "rules" and current:
                data["rules"].append(current)
                current = None
            if key == "rules":
                section = "rules"
                continue
            elif key == "changelog":
                section = "changelog"
                current = None
                continue
            else:
                section = "pack"
                if val:
                    data["pack"][key] = _parse_scalar(val)
                else:
                    data["pack"][key] = {}
                continue

        if section == "pack":
            m = re.match(r"^\s+([a-zA-Z_]+):\s*(.*)$", line)
            if m and isinstance(data["pack"], dict):
                data["pack"][m.group(1)] = _parse_scalar(m.group(2))
        elif section == "rules":
            # 列表项起始
            if re.match(r"^\s*-\s+", line):
                if current:
                    data["rules"].append(current)
                current = {}
                kv = re.sub(r"^\s*-\s+", "", line)
                m = re.match(r"^([a-zA-Z_]+):\s*(.*)$", kv)
                if m:
                    current[m.group(1)] = _parse_scalar(m.group(2))
            else:
                m = re.match(r"^\s+([a-zA-Z_]+):\s*(.*)$", line)
                if m and current is not None:
                    current[m.group(1)] = _parse_scalar(m.group(2))
    if current:
        data["rules"].append(current)
    return data


def load_hard_terms(pack_dir):
    path = os.path.join(pack_dir, "hard_terms.json")
    if not os.path.exists(path):
        return {"repealed_laws": [], "banned_phrases": [], "required_elements": [], "thresholds": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_rules(pack_dir):
    """返回 rules/ 目录下所有规则文件路径。"""
    return sorted(glob.glob(os.path.join(pack_dir, "rules", "R-*.md")))


def rule_meta_from_manifest(manifest):
    """以 manifest.rules 为准，返回 {rule_id: meta}。"""
    out = {}
    for r in manifest.get("rules", []):
        rid = r.get("id")
        if rid:
            out[rid] = r
    return out


def normalize(s):
    """归一化文本用于检索：去除所有空白字符，便于 quote 子串匹配（防幻觉）。"""
    if s is None:
        return ""
    return re.sub(r"\s+", "", str(s))


def quote_in_text(quote, full_text_norm):
    """判断 quote 是否能在原文中检索到（去空白子串匹配）。返回 bool。"""
    q = normalize(quote)
    if not q:
        return False
    return q in full_text_norm


def locate_quote(quote, sections):
    """在切块中定位 quote 所在章节，返回章节标题（找不到返回空串）。"""
    q = normalize(quote)
    for sec in sections:
        if q and q in normalize(sec.get("text", "")):
            return sec.get("title", "")
    return ""


def read_text_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
