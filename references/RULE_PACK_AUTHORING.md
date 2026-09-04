# 规则包编写与热更新指南

规则与引擎解耦：**改规则不碰引擎、不重启**。引擎每次审核前重新扫描规则包目录。

## 一、规则包结构

```
规则包-XXX/
├── manifest.yaml     # 包元信息 + 规则清单
├── hard_terms.json   # 硬规则词表（代码判定）
├── rules/R-*.md      # 一条规则一个文件
└── tests/*.json      # 回归测试集
```

## 二、新增/修改一条规则

1. 在 `rules/` 新建或编辑 `R-<组>-<序号>.md`，frontmatter 必须含：规则编码、规则分类、判定方式（hard_match/value_check/rule_check/semantic）、严重度（高/中/低）、状态（active/draft）、是否隐性。
2. 在 `manifest.yaml` 的 `rules:` 列表登记（id/name/judge/severity/status/hidden/file）。
3. 若是字符级可判定的（法规名、违禁词、必备关键词、阈值），写进 `hard_terms.json`，走代码零漏报；否则在 md 里写「审核维度」和「审核提示词」，走 LLM。
4. 在 `tests/` 加正例（应命中）与反例（不应误报）。
5. 跑自检与回归：
   ```
   python scripts/validate_rules.py --pack "规则包-XXX" --lint --test
   ```

`draft` 状态：规则已写但灰度中，报告里不计入正式问题、也不计入"未发现问题"，用于先观察不误伤。

## 三、hard_terms.json 编写

- `repealed_laws`：失效法规。`pattern` 为全称，`also_match` 为简称（如《合同法》），`current` 为应替换的现行法，`reason` 为说明。隐性、命中置顶。
- `banned_phrases`：违禁/高风险表述。`pattern` 精确匹配，`severity`/`reason`/`suggestion` 齐全。
- `required_elements`：必备要素。`any_of` 关键词在全文**全部未出现**才判缺失（降低误报）。
- `thresholds`：阈值验算。`key` 决定验算逻辑（账期天数/预付款比例/日违约金费率），`value` 为阈值，`context_keywords` 限定上下文，`note` 说明。阈值是行业参考、可由企业调整，不是法律硬标准。

## 四、回归测试文件格式（tests/*.json）

```json
{
  "rule_id": "R-LEGAL-01",
  "cases": [
    { "name": "正例-援引旧合同法应命中", "expect_hit": true,
      "text": "本合同依据《中华人民共和国合同法》订立……" },
    { "name": "反例-援引民法典不应误报", "expect_hit": false,
      "text": "本合同依据《中华人民共和国民法典》订立……" }
  ]
}
```

- hard_match/value_check 规则：`validate_rules.py --test` 用真实 hard_check 判定，正例必须命中、反例必须不误报，否则失败。
- rule_check/semantic 规则：无模型环境不自动判定，脚本标记"待 LLM 评审"；接入模型后按 `LLM_SEMANTIC_PROMPT.md` 跑，人工/模型核对样例。

## 五、热更新与版本

- 改完规则文件即生效（下一份合同按新规则审）；无需重新发布。
- 每次实质修改在 `manifest.yaml` 的 `changelog` 追加版本号、日期、说明；报告水印带版本，实现"当时按哪版规则审的"可追溯。
- 回滚 = 把规则包文件恢复到旧版本（建议规则包纳入 git 或定期备份）。

## 六、复制到新合同类型（换规则包）

1. 复制整个规则包目录为 `规则包-劳动合同/`（或租赁/保密/SaaS/营销合规）。
2. 改 `manifest.yaml` 的 pack 信息与 rules 清单；替换 `rules/`、`hard_terms.json`、`tests/`。
3. 引擎脚本**完全不动**；审核时 `--pack "规则包-劳动合同"` 指定即可。
