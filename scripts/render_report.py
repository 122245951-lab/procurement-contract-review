# -*- coding: utf-8 -*-
"""
render_report.py — F6 汇总去重 + F7 交互式 HTML 报告。
输入：contract.json + hard_hits.json + [llm_hits.json] + 规则包目录。
输出：单文件、内联 CSS/JS、无外部依赖的 HTML 审核报告。
特性：硬规则置顶、按严重度排序、四要素卡片、原文高亮、接受/拒绝/编辑、未命中折叠、
      规则包版本水印、一键导出 Markdown 审核意见。
使用 string.Template 注入数据，CSS 花括号无需转义。
"""
import os
import sys
import json
import html
import argparse
import datetime
from string import Template

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rulekit import resolve_pack, load_manifest, rule_meta_from_manifest, normalize, read_json  # noqa: E402

SEV_RANK = {"高": 0, "中": 1, "低": 2}
SEV_CLASS = {"高": "sev-high", "中": "sev-mid", "低": "sev-low"}


def load_hits(path):
    if not path or not os.path.exists(path):
        return []
    try:
        data = read_json(path)
        return data.get("hits", []) if isinstance(data, dict) else data
    except Exception:
        return []


def dedupe_llm(hits):
    seen = set()
    out = []
    for h in hits:
        key = (h.get("rule_id", ""), normalize(h.get("quote", ""))[:20])
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def merge_hits(hard_hits, llm_hits):
    merged = []
    for h in hard_hits:
        h["_source"] = "代码硬规则"
        merged.append(h)
    for h in dedupe_llm(llm_hits):
        if h.get("quote") and not h.get("quote_verified", True):
            continue  # 防幻觉兜底：quote 校验失败丢弃
        h["_source"] = "AI 语义审核"
        h.setdefault("pinned", False)
        merged.append(h)

    def sk(h):
        return (0 if h.get("pinned") else 1, SEV_RANK.get(h.get("severity", "低"), 3), h.get("rule_id", ""))
    merged.sort(key=sk)
    return merged


def esc(s):
    return html.escape(str("" if s is None else s))


def build_cards(hits, rules_meta):
    cards = []
    for h in hits:
        rid = h.get("rule_id", "")
        sev = h.get("severity", "中")
        rname = (rules_meta.get(rid, {}) or {}).get("name", "")
        loc = h.get("location", "") or "—"
        quote = h.get("quote", "")
        problem = h.get("problem", "")
        suggestion = h.get("suggestion", "")
        judge = h.get("judge", "")
        src = h.get("_source", "")
        pin = '<span class="pin-badge">置顶</span>' if h.get("pinned") else ""
        if quote:
            quote_html = ('<div class="quote"><span class="quote-label">原文摘录</span><mark>%s</mark></div>'
                          % esc(quote))
        else:
            quote_html = ('<div class="quote noquote"><span class="quote-label">原文摘录</span>'
                          '（全文未检出相关内容，属要件缺失）</div>')
        card = Template(CARD_TPL).safe_substitute(
            rid=esc(rid), sev=esc(sev), sevcls=SEV_CLASS.get(sev, "sev-mid"),
            rname=esc(rname), pin=pin, src=esc(src), judge=esc(judge),
            loc=esc(loc), quote_html=quote_html,
            problem=esc(problem), sugg=esc(suggestion))
        cards.append(card)
    return "\n".join(cards)


CARD_TPL = """
    <div class="card" data-rid="$rid" data-sev="$sev">
      <div class="card-head">
        <span class="sev $sevcls">$sev</span>
        <span class="rule-id">$rid</span>
        <span class="rule-name">$rname</span>
        $pin
        <span class="src">$src · $judge</span>
      </div>
      <div class="loc"><span class="k">定位</span>$loc</div>
      $quote_html
      <div class="problem"><span class="k">问题</span><div class="editable" contenteditable="true">$problem</div></div>
      <div class="suggestion"><span class="k">建议</span><div class="editable sugg" contenteditable="true">$sugg</div>
        <button class="copy-btn" onclick="copySugg(this)">复制建议</button>
      </div>
      <div class="actions">
        <label class="acc"><input type="checkbox" class="accept" onchange="markCard(this)"> 接受</label>
        <label class="rej"><input type="checkbox" class="reject" onchange="markCard(this)"> 拒绝</label>
        <span class="status-tag"></span>
      </div>
    </div>"""

PAGE_TPL = Template("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>采购合同智能审核报告 · $contract</title>
<style>
  :root {
    --bg:#f5f6f8; --panel:#ffffff; --ink:#1f2329; --sub:#646a73; --line:#e5e6eb;
    --brand:#1a5fb4; --brand-bg:#eaf2fc;
    --high:#d83b3b; --high-bg:#fdecec; --mid:#c77b18; --mid-bg:#fdf3e3; --low:#3a7d44; --low-bg:#eaf6ec;
    --mark:#fff2a8;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; line-height:1.7; }
  .wrap { max-width:920px; margin:0 auto; padding:24px 16px 80px; }
  header.top { background:linear-gradient(135deg,#1a5fb4,#2f7fd1); color:#fff; border-radius:14px;
    padding:22px 26px; box-shadow:0 6px 20px rgba(26,95,180,.18); }
  header.top h1 { margin:0 0 6px; font-size:21px; }
  header.top .meta { font-size:13px; opacity:.92; }
  .watermark { margin-top:10px; font-size:12px; opacity:.85; border-top:1px solid rgba(255,255,255,.25); padding-top:8px; }
  .summary { display:flex; gap:12px; margin:18px 0; flex-wrap:wrap; }
  .stat { flex:1; min-width:120px; background:var(--panel); border:1px solid var(--line); border-radius:10px;
    padding:14px 16px; text-align:center; }
  .stat .num { font-size:26px; font-weight:700; }
  .stat .lbl { font-size:12px; color:var(--sub); }
  .stat.high .num { color:var(--high); } .stat.mid .num { color:var(--mid); }
  .stat.low .num { color:var(--low); } .stat.ok .num { color:var(--brand); }
  .toolbar { display:flex; gap:10px; margin:6px 0 18px; flex-wrap:wrap; }
  button.btn { background:var(--brand); color:#fff; border:none; border-radius:8px; padding:9px 16px; font-size:13px; cursor:pointer; }
  button.btn.ghost { background:#fff; color:var(--brand); border:1px solid var(--brand); }
  .card { background:var(--panel); border:1px solid var(--line); border-left:4px solid var(--mid);
    border-radius:10px; padding:16px 18px; margin-bottom:14px; box-shadow:0 1px 3px rgba(0,0,0,.04); }
  .card[data-sev="高"] { border-left-color:var(--high); }
  .card[data-sev="低"] { border-left-color:var(--low); }
  .card.accepted { background:#f4faf5; border-color:#bfe3c7; }
  .card.rejected { opacity:.55; }
  .card-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:8px; }
  .sev { font-size:12px; font-weight:700; padding:2px 9px; border-radius:20px; }
  .sev-high { background:var(--high-bg); color:var(--high); }
  .sev-mid { background:var(--mid-bg); color:var(--mid); }
  .sev-low { background:var(--low-bg); color:var(--low); }
  .rule-id { font-weight:700; font-size:13px; color:var(--brand); font-family:monospace; }
  .rule-name { font-weight:600; font-size:14px; }
  .pin-badge { background:var(--high); color:#fff; font-size:11px; padding:1px 8px; border-radius:4px; }
  .src { margin-left:auto; font-size:11px; color:var(--sub); }
  .k { display:inline-block; min-width:42px; font-size:12px; color:var(--sub); font-weight:600; vertical-align:top; }
  .loc { font-size:13px; margin-bottom:6px; }
  .quote { background:#fafbfc; border:1px dashed var(--line); border-radius:6px; padding:8px 10px; font-size:13px; margin:6px 0; }
  .quote.noquote { color:var(--mid); }
  .quote-label { font-size:11px; color:var(--sub); margin-right:6px; }
  mark { background:var(--mark); padding:0 2px; border-radius:2px; }
  .problem, .suggestion { font-size:13.5px; margin:6px 0; }
  .editable { display:inline-block; min-width:80%; }
  .editable:focus { outline:2px solid var(--brand-bg); background:#fff; border-radius:4px; }
  .sugg { color:#0f5132; }
  .copy-btn { margin-left:44px; margin-top:4px; background:#fff; border:1px solid var(--line);
    border-radius:6px; font-size:11px; padding:3px 10px; cursor:pointer; color:var(--sub); }
  .actions { margin-top:10px; border-top:1px solid var(--line); padding-top:8px; display:flex; gap:18px; align-items:center; font-size:13px; }
  .acc input,.rej input { margin-right:4px; }
  .acc { color:var(--low); } .rej { color:var(--high); }
  .status-tag { font-size:12px; color:var(--sub); }
  details.unchecked { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px 18px; margin-top:8px; }
  details.unchecked summary { cursor:pointer; font-weight:600; color:var(--brand); }
  details.unchecked ul { margin:10px 0 0; padding-left:0; list-style:none; }
  details.unchecked li { font-size:13px; padding:4px 0; border-bottom:1px dashed var(--line); color:var(--sub); }
  .judge-tag { font-size:11px; color:var(--sub); background:#f0f1f3; padding:0 6px; border-radius:4px; margin-left:6px; }
  .disclaimer { margin-top:24px; font-size:12px; color:var(--sub); background:#fff; border:1px solid var(--line);
    border-radius:8px; padding:12px 16px; }
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>📋 采购合同智能审核报告</h1>
    <div class="meta">合同：$contract　｜　审核时间：$time</div>
    <div class="watermark">规则包：$pack_name　版本 v$pack_ver　生效日期 $pack_eff　｜　AI 意见仅供参考，采纳前请法务复核，不构成法律意见</div>
  </header>

  <div class="summary">
    <div class="stat high"><div class="num">$n_high</div><div class="lbl">高风险</div></div>
    <div class="stat mid"><div class="num">$n_mid</div><div class="lbl">中风险</div></div>
    <div class="stat low"><div class="num">$n_low</div><div class="lbl">低风险</div></div>
    <div class="stat ok"><div class="num">$n_hit</div><div class="lbl">命中项</div></div>
    <div class="stat ok"><div class="num">$n_unchecked</div><div class="lbl">已检查未发现问题</div></div>
  </div>

  <div class="toolbar">
    <button class="btn" onclick="exportMd()">⬇ 导出审核意见 (Markdown)</button>
    <button class="btn ghost" onclick="window.print()">🖨 打印 / 存 PDF</button>
  </div>

  <h3>⚠ 命中问题（按风险排序，硬规则置顶）</h3>
  $cards

  <details class="unchecked">
    <summary>✅ 已检查 $n_unchecked 项规则，未发现问题（点击展开）</summary>
    <ul>
$unchecked_html
    </ul>
  </details>

  <div class="disclaimer">
    免责声明：本报告由 AI 依据「$pack_name v$pack_ver」自动生成，仅为风险提示与修改建议，<b>不构成法律意见</b>，
    不替代律师/法务最终判断。硬规则（失效法规、违禁表述）为字符级判定，语义规则由模型理解可能存在波动；
    请结合合同全文与专业意见决策。报告水印记录规则包版本，便于追溯“当时按哪版规则审核”。
  </div>
</div>

<script>
const PAYLOAD = $payload;

function markCard(cb){
  const card = cb.closest('.card');
  const tag = card.querySelector('.status-tag');
  const acc = card.querySelector('.accept');
  const rej = card.querySelector('.reject');
  if(cb.classList.contains('accept') && cb.checked){ rej.checked=false; }
  if(cb.classList.contains('reject') && cb.checked){ acc.checked=false; }
  card.classList.toggle('accepted', acc.checked);
  card.classList.toggle('rejected', rej.checked);
  tag.textContent = acc.checked ? '已接受 ✓' : (rej.checked ? '已拒绝 ✗' : '');
}
function copySugg(btn){
  const txt = btn.parentElement.querySelector('.sugg').innerText;
  navigator.clipboard.writeText(txt).then(()=>{
    const o=btn.textContent; btn.textContent='已复制 ✓'; setTimeout(()=>btn.textContent=o,1500);
  });
}
function exportMd(){
  const p = PAYLOAD;
  let md = '# 采购合同审核意见\\n\\n';
  md += '- 合同：' + p.contract + '\\n- 审核时间：' + p.time + '\\n';
  md += '- 规则包：' + p.pack + ' v' + p.version + '（生效 ' + p.effective_date + '）\\n\\n';
  md += '## 命中问题（' + p.hits.length + ' 项）\\n\\n';
  p.hits.forEach((h,i)=>{
    md += '### ' + (i+1) + '. [' + h.severity + '] ' + h.rule_id + '\\n';
    md += '- 定位：' + (h.location||'—') + '\\n';
    if(h.quote) md += '- 原文：' + h.quote + '\\n';
    md += '- 问题：' + h.problem + '\\n';
    md += '- 建议：' + h.suggestion + '\\n\\n';
  });
  md += '## 已检查未发现问题\\n\\n' + p.unchecked.join('、') + '\\n\\n';
  md += '> 本意见由 AI 生成，不构成法律意见，采纳前请法务复核。\\n';
  const blob = new Blob([md], {type:'text/markdown;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = '合同审核意见.md';
  a.click();
}
</script>
</body>
</html>
""")


def build_report(contract, hard_hits, llm_hits, pack_dir, out_path):
    man = load_manifest(pack_dir)
    pack = man.get("pack", {})
    rules_meta = rule_meta_from_manifest(man)

    hits = merge_hits(hard_hits, llm_hits)
    hit_ids = {h.get("rule_id") for h in hits if h.get("rule_id")}

    unchecked = []
    for rid, meta in rules_meta.items():
        if meta.get("status") == "draft":
            continue
        if rid not in hit_ids:
            unchecked.append({"rule_id": rid, "name": meta.get("name", ""), "judge": meta.get("judge", "")})
    unchecked.sort(key=lambda x: x["rule_id"])

    sev_count = {"高": 0, "中": 0, "低": 0}
    for h in hits:
        sev_count[h.get("severity", "低")] = sev_count.get(h.get("severity", "低"), 0) + 1

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    contract_name = os.path.basename(contract.get("file", "合同")) if contract else "合同"

    cards_html = build_cards(hits, rules_meta)
    unchecked_items = "\n".join(
        '      <li><span class="rule-id">%s</span> %s <span class="judge-tag">%s</span></li>'
        % (esc(u["rule_id"]), esc(u["name"]), esc(u["judge"])) for u in unchecked)

    payload = json.dumps({
        "contract": contract_name, "pack": pack.get("name", ""),
        "version": pack.get("version", ""), "effective_date": pack.get("effective_date", ""),
        "time": now,
        "hits": [{"rule_id": h.get("rule_id"), "severity": h.get("severity"),
                  "location": h.get("location"), "quote": h.get("quote"),
                  "problem": h.get("problem"), "suggestion": h.get("suggestion")} for h in hits],
        "unchecked": [u["rule_id"] for u in unchecked],
    }, ensure_ascii=False)

    page = PAGE_TPL.safe_substitute(
        contract=esc(contract_name), time=esc(now),
        pack_name=esc(pack.get("name", "")), pack_ver=esc(pack.get("version", "")),
        pack_eff=esc(pack.get("effective_date", "")),
        n_high=sev_count["高"], n_mid=sev_count["中"], n_low=sev_count["低"],
        n_hit=len(hits), n_unchecked=len(unchecked),
        cards=cards_html, unchecked_html=unchecked_items, payload=payload)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    return {
        "out": os.path.abspath(out_path), "hits": len(hits),
        "high": sev_count["高"], "mid": sev_count["中"], "low": sev_count["低"],
        "unchecked": len(unchecked),
    }


def main():
    ap = argparse.ArgumentParser(description="生成交互式 HTML 审核报告")
    ap.add_argument("contract_json", help="contract.json")
    ap.add_argument("--hard", default="hard_hits.json", help="硬规则命中 JSON")
    ap.add_argument("--llm", default=None, help="LLM 语义命中 JSON（可选）")
    ap.add_argument("--pack", default=None, help="规则包目录")
    ap.add_argument("--out", default="合同审核报告.html", help="输出 HTML 路径")
    args = ap.parse_args()

    pack_dir = resolve_pack(args.pack)
    contract = read_json(args.contract_json)
    hard_hits = load_hits(args.hard)
    llm_hits = load_hits(args.llm) if args.llm else []
    info = build_report(contract, hard_hits, llm_hits, pack_dir, args.out)
    print("报告已生成：%s" % info["out"])
    print("命中 %d 项（高%d/中%d/低%d）｜已检查未发现问题 %d 项" %
          (info["hits"], info["high"], info["mid"], info["low"], info["unchecked"]))


if __name__ == "__main__":
    main()