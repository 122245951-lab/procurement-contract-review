# 语义/要件规则 LLM 评审提示词规范（F5）

本文件规定助手（LLM）如何评审判定方式为 `rule_check` / `semantic` 的规则。硬规则（hard_match/value_check）已由脚本完成，LLM 不重复判定失效法规、违禁表述、必备要素缺失、阈值验算。

## 一、输入准备

1. 运行 `parse_contract.py` 得到 `contract.json`（含 `sections` 切块与 `full_text`）。
2. 从规则包 `manifest.yaml` 读取所有 `judge ∈ {rule_check, semantic}` 且 `status=active` 的规则。
3. 逐条读取 `rules/R-*.md` 中的「审核维度」与「审核提示词」。

## 二、系统提示词（System）

```
你是一名资深企业法务/合规专家，正在对一份采购合同做签约前风险审查。
铁律：
1. 只能依据【合同原文】判定，不得编造合同中不存在的条款、金额、主体名称或事实。
2. 每条结论必须给出可在原文中逐字检索到的摘录（quote）；若属"要件缺失"，quote 留空并在 problem 注明"未约定"。
3. 只审当前分配给你的这一条规则，不要扩展到其他规则范围。
4. 超出本规则范围、或信息不足无法判定的，输出 hit=false 且 need_human=true（建议人工复核），不要强行下结论。
5. 你只给意见，不改写合同；建议要具体、可执行。
严格输出 JSON，不要输出 JSON 以外的任何文字。
```

## 三、单条规则用户提示词（User）模板

```
【规则】{rule_id} {规则名称}（判定方式：{judge}，严重度：{severity}）
【审核维度】
{rules/R-*.md 中"审核维度"全文}

【合同相关原文】
{与该规则相关的切块文本；若难以预判相关切块，给全文或按章节分批}

请按审核维度逐项核验，输出 JSON：
{
  "rule_id": "{rule_id}",
  "hit": true/false,
  "severity": "高/中/低",
  "location": "章节/条款号或标题",
  "quote": "合同原文逐字摘录（要件缺失时留空字符串）",
  "problem": "命中的具体问题（一句话说清风险）；未命中留空",
  "suggestion": "可执行的修改建议；未命中留空",
  "need_human": true/false
}
```

## 四、出参强制与防幻觉校验（助手必须执行）

1. **JSON 解析**：模型返回必须是合法 JSON；解析失败重试一次（提示"仅输出 JSON"），仍失败则该规则记为"评审失败-建议人工"，不阻断整体。
2. **quote 检索校验（防幻觉，硬性）**：
   - 对每条 `hit=true` 且 `quote` 非空的结果，去除所有空白字符后，判断 quote 是否为 `full_text`（同样去空白）的子串。
   - 检索不到 → 丢弃该条（或退回让模型重新提供原文摘录，重试一次仍失败则丢弃）。
   - 可调用 `rulekit.quote_in_text(quote, normalize(full_text))` 与 `rulekit.locate_quote(quote, sections)` 自动校验并回填章节。
3. **要件缺失类**：`quote` 为空但 `problem` 明确写"未约定/缺失"的，保留（这类无原文可引）。
4. **低温稳定**：调用模型时用低温度（如 0.1）、关闭思考链，保证可重复。
5. **单规则容错**：一条规则超时/异常不影响其他规则；失败规则在报告中归入"建议人工复核"。

## 五、输出文件

LLM 评审结果汇总为 `llm_hits.json`：

```json
{
  "pack": "rules-pack-企业采购合同",
  "track": "llm",
  "hits": [
    {
      "rule_id": "R-BREACH-01",
      "track": "llm",
      "judge": "semantic",
      "severity": "高",
      "location": "第十条 违约责任",
      "quote": "……如违约，违约方承担相应责任……",
      "problem": "违约责任仅笼统表述"承担相应责任"，未针对逾期交付/质量不合格等情形约定可执行救济。",
      "suggestion": "按主要违约情形分别约定违约金计算方式或损失赔偿口径，并设定合理责任上限。",
      "quote_verified": true,
      "need_human": false
    }
  ]
}
```

随后用 `render_report.py --llm llm_hits.json` 或 `contract_review.py --llm llm_hits.json` 合并进 HTML 报告。

## 六、批处理建议

长合同可按 `sections` 切块，把与某规则最相关的切块喂给模型（如 R-DATA-01 优先找含"保密/数据"的切块）；但"要件缺失"类规则（如全文无不可抗力条款）需基于全文判断，不能只看单块。
