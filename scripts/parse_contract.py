# -*- coding: utf-8 -*-
"""
parse_contract.py — F1/F2 合同解析与智能切块（纯标准库）。
支持 .docx（标准库 zipfile+xml 解析，无需第三方包）/.txt/.md；.pdf 尽力抽取（无第三方库时给出提示）。
文件类型读内容首段判断，不靠后缀。
输出 contract.json：{file, title, full_text, sections:[{index,title,text,char_count}]}
切块规则：按"第X章/条/节/附件/一、二、"等标题切分并保留章节路径；单块超阈值按行二次切分。
"""
import os
import re
import sys
import json
import zipfile
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rulekit import write_json  # noqa: E402

MAX_BLOCK = 800  # 单块最大字符数，超出按行二次切分

# 章节标题模式
CHAPTER_PATTERNS = [
    r"^\s*第\s*[0-9０-９一二三四五六七八九十百]+\s*章[\s、．.].*$",
    r"^\s*第\s*[0-9０-９一二三四五六七八九十百]+\s*条[\s、．.].*$",
    r"^\s*第\s*[0-9０-９一二三四五六七八九十百]+\s*节[\s、．.].*$",
    r"^\s*附件\s*[0-9０-９一二三四五六七八九十]*.*$",
    r"^\s*[0-9]+[.、．]\s*.*$",          # 1. / 1、 数字编号
    r"^\s*[一二三四五六七八九十]+[、．.]\s*.*$",  # 一、 二、
]
CHAPTER_RE = re.compile("|".join("(%s)" % p for p in CHAPTER_PATTERNS))


def detect_kind(path, head_bytes):
    """读内容首段判断类型，不靠后缀。"""
    if head_bytes[:2] == b"PK":
        return "docx"
    if head_bytes[:4] == b"%PDF":
        return "pdf"
    # 文本类
    try:
        head_bytes.decode("utf-8")
        return "txt"
    except UnicodeDecodeError:
        try:
            head_bytes.decode("gbk")
            return "txt"
        except UnicodeDecodeError:
            return "unknown"


def extract_docx(path):
    """用标准库 zipfile 读取 word/document.xml，按段落提取文本。"""
    import xml.etree.ElementTree as ET
    paras = []
    with zipfile.ZipFile(path) as z:
        with z.open("word/document.xml") as f:
            tree = ET.parse(f)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    root = tree.getroot()
    for p in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        texts = [t.text or "" for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
        line = "".join(texts).strip()
        if line:
            paras.append(line)
    return "\n".join(paras)


def extract_pdf(path):
    """无第三方库时的尽力抽取：解压 FlateDecode 流，抓取 Tj/TJ 中的文本。
    中文嵌入字体可能为 CID 编码导致乱码；若抽取字符过少则返回空并提示。"""
    import zlib
    text_parts = []
    try:
        with open(path, "rb") as f:
            data = f.read()
        # 找所有 stream...endstream
        for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
            raw = m.group(1)
            dec = None
            try:
                dec = zlib.decompress(raw)
            except Exception:
                continue
            # 提取 ( ) Tj 与 [...] TJ 内的字符串
            for tm in re.finditer(rb"\((?:[^()\\]|\\.)*\)", dec):
                s = tm.group(0)[1:-1]
                try:
                    text_parts.append(s.decode("utf-8", "ignore"))
                except Exception:
                    pass
    except Exception:
        return ""
    txt = "".join(text_parts)
    # 中文字符占比过低视为抽取失败
    cjk = len(re.findall(r"[\u4e00-\u9fff]", txt))
    if cjk < 20:
        return ""
    return txt


def extract_txt(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def split_sections(full_text):
    """按章节标题切块，保留标题；超大块按行二次切分。"""
    lines = [l.rstrip() for l in full_text.splitlines()]
    sections = []
    cur_title = "（开头）"
    cur_buf = []

    def flush():
        body = "\n".join([b for b in cur_buf if b.strip()]).strip()
        if body or cur_title != "（开头）":
            sections.append({"title": cur_title, "text": body})

    for line in lines:
        if CHAPTER_RE.match(line) and len(line.strip()) <= 40:
            # 命中章节标题：结束上一块
            flush()
            cur_title = line.strip()
            cur_buf = []
        else:
            cur_buf.append(line)
    flush()

    # 二次切分超大块
    result = []
    idx = 1
    for sec in sections:
        body = sec["text"]
        if len(body) <= MAX_BLOCK:
            result.append({"index": idx, "title": sec["title"], "text": body, "char_count": len(body)})
            idx += 1
        else:
            # 按行累积到 MAX_BLOCK
            buf = []
            cur_len = 0
            sub = 1
            for ln in body.splitlines():
                buf.append(ln)
                cur_len += len(ln)
                if cur_len >= MAX_BLOCK:
                    txt = "\n".join(buf).strip()
                    result.append({"index": idx, "title": "%s（续%d）" % (sec["title"], sub),
                                   "text": txt, "char_count": len(txt)})
                    idx += 1
                    sub += 1
                    buf = []
                    cur_len = 0
            if buf:
                txt = "\n".join(buf).strip()
                result.append({"index": idx, "title": "%s（续%d）" % (sec["title"], sub),
                               "text": txt, "char_count": len(txt)})
                idx += 1
    # 过滤空块
    result = [r for r in result if r["text"].strip()]
    for i, r in enumerate(result, 1):
        r["index"] = i
    return result


def guess_title(full_text, path):
    for line in full_text.splitlines()[:8]:
        line = line.strip()
        if 6 <= len(line) <= 40 and ("合同" in line or "协议" in line or "协议" in line):
            return line
    return os.path.splitext(os.path.basename(path))[0]


def parse(path):
    with open(path, "rb") as f:
        head = f.read(8)
    kind = detect_kind(path, head)
    if kind == "docx":
        text = extract_docx(path)
    elif kind == "pdf":
        text = extract_pdf(path)
        if not text:
            raise RuntimeError("PDF 文本抽取失败（可能为扫描件/嵌入字体）。请先另存为 .docx 或 .txt 后重试，或安装 pypdf：pip install pypdf。")
    elif kind == "txt":
        text = extract_txt(path)
    else:
        raise RuntimeError("无法识别的文件类型，请提供 .docx / .pdf / .txt。")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    sections = split_sections(text)
    return {
        "file": os.path.abspath(path),
        "kind": kind,
        "title": guess_title(text, path),
        "full_text": text,
        "char_count": len(text),
        "section_count": len(sections),
        "sections": sections,
    }


def main():
    ap = argparse.ArgumentParser(description="合同解析与智能切块")
    ap.add_argument("contract", help="合同文件路径（.docx/.pdf/.txt）")
    ap.add_argument("--out", default="contract.json", help="输出 JSON 路径")
    args = ap.parse_args()

    data = parse(args.contract)
    write_json(args.out, data)
    print("解析完成：%s" % data["file"])
    print("类型：%s｜标题：%s｜总字数：%d｜切块数：%d" %
          (data["kind"], data["title"], data["char_count"], data["section_count"]))
    print("输出：%s" % os.path.abspath(args.out))


if __name__ == "__main__":
    main()
