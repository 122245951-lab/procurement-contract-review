# 采购合同审核助手 · Procurement Contract Review

> 签约前最后一关：代码抓死规则，LLM 读透语义，每一条风险都可溯源、可接受、可拒绝。

采购合同动辄几十页，人工审核容易漏掉失效法规援引、必备要素缺失、权责不对等。本 Skill 采用**规则驱动的双轨审核**：字符级硬规则交给代码（零漏报），语义规则交给 LLM（理解权责/归属），产出带【章节定位 + 原文摘录 + 命中规则 + 修改建议 + 接受/拒绝复选框】的单页交互式 HTML 审核报告。

---

## ✨ 核心亮点

| 亮点 | 解决的问题 |
|------|-----------|
| **双轨审核架构** | 确定性规则走代码（失效法规/违禁表述/必备要素/阈值验算，字符级精确、零漏报）；语义规则走 LLM（权责对等/归属/约定有效性） |
| **规则即数据、可插拔** | 规则是 md/json 文本而非代码，每次审核热加载——**改规则不碰引擎**；同一引擎换规则包即可复用于劳动/租赁/保密/SaaS/营销合规等场景 |
| **防幻觉、可溯源** | 每条问题必须给出【章节定位 + 原文摘录 + 命中规则 + 修改建议】；`quote` 在合同原文检索不到一律丢弃，原文无依据不输出 |
| **未命中也透明** | 每条规则在报告中体现"已检查 / 未发现问题"，你知道 AI 到底看了什么 |
| **单页交互式 HTML 报告** | 每条建议可一键 **接受 / 拒绝 / 编辑**，采纳权永远在人，适合走审批流 |
| **规则可运营** | 规则包带版本号、生效日期、来源依据；内置 lint 校验 + 回归测试（正例应命中 / 反例不误报），改完能自检、能回滚 |
| **零第三方依赖** | 全部脚本纯 Python 标准库，`.docx` 用标准库解析 zip 内 XML，装好 Python 就能跑 |

## 🚀 快速开始

```bash
# 0. 规则包自检（每次审核前）
python scripts/validate_rules.py --pack "rules-pack-企业采购合同" --lint

# 1. 解析合同（支持 docx / pdf / txt，自动按"第X章/条"切块）
python scripts/parse_contract.py examples/demo-contract.txt --out contract.json

# 2. 硬规则审核（代码，字符级零漏报）
python scripts/hard_check.py contract.json --pack "rules-pack-企业采购合同" --out hard_hits.json

# 3. 一键跑完整审核闭环（parse → hard → [LLM 语义] → HTML 报告）
python scripts/contract_review.py examples/demo-contract.txt --pack "rules-pack-企业采购合同" --out examples/demo-report.html
```

## 📦 首发规则包：企业采购合同（12 条）

| 分类 | 规则 | 说明 |
|------|------|------|
| 违约 | R-BREACH-01/02 | 违约金比例上限、违约责任对等 |
| 数据 | R-DATA-01 | 数据归属与使用边界 |
| 交付 | R-DELIV-01 | 交付标准与验收期限 |
| 争议 | R-DISP-01 | 争议解决条款完备性 |
| 知识产权 | R-IP-01 | IP 归属与侵权责任 |
| 法规 | R-LEGAL-01 | 失效法规援引（如旧《合同法》） |
| 主体 | R-PARTY-01 | 签约主体与授权完备 |
| 付款 | R-PAY-01/02 | 付款节奏、尾款比例、发票义务 |
| 期限 | R-TERM-01 | 合同期限与续约机制 |
| 质保 | R-WARR-01 | 质保期与售后责任 |

> 每条规则一个 md 文件，含判定方式（`hard_match` 硬规则 / `rule_check` 语义 / `semantic` LLM）、严重级、命中条件、修改建议模板与来源依据。

## 📁 目录结构

```
procurement-contract-review/
├── SKILL.md                          # 定位 + F1→F7 编排 + 硬性不变量
├── package.json
├── skill-card.md
├── references/
│   ├── LLM_SEMANTIC_PROMPT.md        # 语义规则 LLM 评审提示词与 JSON 出参规范
│   ├── OPS_REPORT_SPEC.md            # 命中项 Ops JSON 标准 + HTML 报告字段约定
│   └── RULE_PACK_AUTHORING.md        # 新增/修改规则、回归测试、换规则包手册
├── scripts/                          # 纯 Python 标准库
│   ├── parse_contract.py             # F1/F2 解析 + 章节切块
│   ├── hard_check.py                 # F4 硬规则（字符级零漏报）
│   ├── validate_rules.py             # F9 规则自检 + 回归测试
│   ├── render_report.py              # F7 汇总 + 交互式 HTML 报告
│   └── contract_review.py            # 编排入口
├── rules-pack-企业采购合同/          # 首发规则包（可插拔、可热更新）
│   ├── manifest.yaml                 # 包名/版本/生效日期/规则清单/来源
│   ├── hard_terms.json               # 硬规则词表
│   ├── rules/R-*.md                  # 12 条规则，一条一文件
│   └── tests/*.json                  # 回归测试集
└── examples/                         # 演示合同 + 示例报告
```

## ⚖️ 适用边界

- ✅ 货物采购、软件与系统开发、服务外包、工程建设等合同签约前自查/复核
- ✅ 维护审核规则、回归测试、换规则包复用到其他合同类型
- ❌ 不代写合同、不代签、不出具法律意见书

## License

MIT
