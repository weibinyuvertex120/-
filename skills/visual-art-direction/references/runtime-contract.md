# Runtime Contract · 运行时契约

本文档定义 `visual-art-direction` Skill 的运行时能力边界、状态语义和真实证据要求。

当前唯一执行函数是 `scripts.runner:main`。安装包通过 `seeform` 调用；直接使用 Skill bundle
时通过 `python -m scripts` 调用。不得把 `deterministic_editor.py`、
`compare_candidates.py` 或 adapter 模块另行包装成第二套公开工作流。

---

## 一、能力分级

### V0：文件访问

**允许**：
- 读取图片文件
- 获取尺寸和格式
- 计算 SHA-256
- 检查输入完整性

**禁止**：
- 事实观察
- 视觉诊断
- 艺术策略最终判断
- 结果审美评价

**证据要求**：
- 文件存在且可读
- Pillow 可识别为有效图片
- SHA-256 计算成功

### V1：视觉观察

**允许**：
- 实际查看图片
- 记录事实观察
- 判断问题维度、缺失类型和不确定性
- 输出结构化观察结果

**禁止**：
- 没有 V2 时声称已完成编辑
- 没有候选时声称已完成结果比较
- 把宿主的自然语言总结当作运行时观察证据
- 从画面推断未经证实的身份、年龄、职业、健康或故事

**结构化结果**：

```json
{
  "success": true,
  "provider": "host-defined-provider",
  "provider_version": "",
  "input_sha256": "sha256-of-original-image",
  "prompt_sha256": "sha256-of-observation-prompt",
  "items": [
    {
      "dimension": "portrait|scene|P01-P10|other",
      "statement": "可从图像确认的事实",
      "evidence": ["支持事实的可见线索"],
      "confidence": "high|medium|low"
    }
  ],
  "uncertainties": [],
  "error": ""
}
```

**证据要求**：
- 必须由 adapter healthcheck 返回真实、可执行的观察路径
- adapter 名称或 capability 名称本身不能让能力变成 true
- runner 必须实际调用 `observe(image, prompt)`
- `input_sha256` 必须匹配 V0 输入 hash
- `prompt_sha256` 必须匹配本次观察请求
- schema 错误、adapter 异常或 hash 不匹配时 fail-closed 为 `failed_execution`
- 自然语言"我可以看图"不能作为完成证据

**第一阶段本地 provider**：

- `qwen3-vl-4b-llama.cpp` 通过 loopback `llama-server` 调用
  `Qwen/Qwen3-VL-4B-Instruct-GGUF`
- healthcheck 必须同时证明 server 可达、配置 model ID 已加载；server 提供 modality 元数据时还必须包含 image
- 请求使用 schema-constrained JSON；模型只生成语义字段，provider/version/input hash/prompt hash 由 adapter 绑定
- 每条观察至少包含一条可见 evidence；malformed JSON、空证据、连接错误或模型不匹配均 fail-closed
- 运行配置和启动方法见 `llama-cpp-local-observation.md`

### V2：图像编辑

**第一版分类**：

1. `deterministic-pillow`
   - L1：曝光、对比度、饱和度
   - L2：明确 box 裁切、比例适配
   - L3：有 Visual Transformation Plan 约束的矩形局部曝光、对比度和饱和度调整

2. 外部 adapter
   - 只做健康检查和协议定义
   - 不默认调用真实生成模型

**有限局部 L3 不等于拥有生成式 L3/L4 能力。**

**证据要求**：
- 内置 deterministic-pillow 的健康证据覆盖 L1/L2 和 Plan 约束的矩形局部 L3；外部 adapter 必须有真实执行路径
- 服务可达不等于模型可用
- 模型可用不等于编辑结果已完成

### V3：结果比较

**第一版内置 `local-compare`**：
- 检查原图和候选是否可读
- 记录尺寸和比例变化
- 记录 SHA-256
- 生成像素变化摘要
- 计算变化区域 bounding box
- 生成 JSON 和 HTML 工程报告
- 输出 `changed_pixels`、`total_pixels`、`change_ratio` 和 `size_matches` 稳定字段
- 支持 compare-only case 传入已有候选，并按父候选进行比较
- compare-only 候选必须声明实际 `operation` 和通过强类型校验的 `parameters`
- 裁切比较额外记录 `crop_box`、源面积、保留/移除面积及比例；面积相对直接父候选计算

**明确限制**：
- 工程差异不等于审美质量
- 像素变化不等于主问题改善
- 比较脚本不能输出"更美""更高级""通过摄影师审核"等结论
- V3 工程比较不能自动替代摄影师判断或用户确认

---

## 二、状态语义

| 状态 | 语义 | 使用场景 |
|------|------|----------|
| `ready` | 能力探测通过，可以继续 | 初始状态 |
| `blocked_no_input` | 输入文件不存在或不可读 | 文件缺失 |
| `blocked_no_view_capability` | 没有图像观察能力 | V1 缺失 |
| `blocked_no_edit_capability` | 没有图像编辑能力 | V2 缺失 |
| `blocked_no_comparison_capability` | 没有原图/候选视觉比较能力 | V3 缺失 |
| `blocked_no_candidate` | 没有候选图可用于比较 | 无输出 |
| `completed_phase` | diagnosis 或 edit 阶段完成，不表示 V3 或用户通过 | 阶段结果 |
| `completed_with_user_feedback_pending` | V3 完成，等待真实用户反馈 | compare/full 结果 |
| `completed` | V3 完成且收到绑定候选 hash 的 `accepted` 反馈 | 最终状态 |
| `rejected` | 用户拒绝当前最终候选 | 用户反馈 |
| `changes_requested` | 用户要求继续调整 | 用户反馈 |
| `failed_invalid_contract` | 契约校验失败 | 参数错误 |
| `failed_execution` | 执行过程失败 | 运行时错误 |

**错误示例**：
- ❌ "模板已创建"写成"视觉诊断完成"
- ❌ "脚本已运行"写成"审美评价通过"
- ❌ "文件已生成"写成"候选比较完成"

---

## 三、确定性能力范围

### L1：曝光、对比度、饱和度

**参数边界**：
- `exposure`: -1.0 .. 1.0
- `contrast`: 0.5 .. 1.5
- `saturation`: 0.5 .. 1.5

**特性**：
- 只使用 Pillow 确定性操作
- 输出默认 PNG，避免 JPEG 二次压缩
- 参数必须有限制，拒绝极端值

### L2：裁切、调整大小

**裁切边界**：
- 必须是绝对坐标 `(left, upper, right, lower)`
- 必须在图像范围内
- 不能是零面积或反向坐标

**调整大小边界**：
- `width`/`height`: 正整数，最大 8192
- `fit`: "contain" 或 "cover"

**禁止**：
- 不做人脸检测
- 不做人脸重构
- 不生成背景
- 不生成新人物

---

## 四、外部 Adapter 健康检查

**不等于真实结果**：
- 服务可达不等于模型可用
- 模型可用不等于编辑结果已完成
- 必须分开记录

**协议定义**：
- healthcheck 返回 `AdapterHealth`
- 包含 capabilities、evidence、checked_at
- 只有健康且有证据时才允许对应能力为 true

---

## 五、真实用户反馈

**不能自动填充**：
- V3 工程比较不能替代真实用户反馈
- Agent、观察模型和比较器都不能生成 `UserFeedback`
- 旧 `user_confirmation_status` 不再是 CaseRequest 合法字段

`UserFeedback` 只能随 `compare` 请求提交，并必须包含 `feedback_id`、`case_id`、
`candidate_id`、`candidate_sha256`、`decision`、`source_event_id` 和 `submitted_at`。
`decision` 为 `accepted|rejected|changes_requested`。反馈必须精确绑定一个叶子候选的 ID 和
SHA-256；full 运行结束后只能进入待反馈状态，用户查看候选后应以 compare 重跑 V3 并提交反馈。

当 `decision=changes_requested` 时，下一版 Plan 必须使用 `decision_source=hybrid`，并额外携带
`parent_plan_id`、`parent_plan_sha256`、`trigger_feedback_id`、`trigger_feedback_sha256`、
`parent_candidate_id` 和 `parent_candidate_sha256`。新 case 通过 `parent_plan` 提交父 Plan
原件，通过 `trigger_feedback` 提交上一轮 UserFeedback 原件；运行时核对父 Plan canonical
hash、反馈 canonical hash、反馈候选 hash，以及首个 V2 操作的父候选输入。缺少父 Plan artifact
或任一 hash 不匹配时，返回 `failed_invalid_contract`，这样自然语言意见不会脱离具体候选独立
变成下一版决策。

---

## 六、证据记录要求

**必须记录**：
- 能力 probe 结果
- V1 观察结果（provider、版本、输入 hash、prompt hash、事实观察、置信度和不确定性）
- 操作详情（操作类型、参数、输入/输出 hash）
- 比较结果（尺寸变化、像素变化摘要）
- 用户反馈原始事件及其候选绑定
- 残余风险

**不能写成**：
- "脚本成功"写成"视觉质量通过"
- 执行者自评写成用户确认

---

## 七、执行计划、局部调整与候选血缘

### 最小 Visual Transformation Plan

Plan 是宿主或 Agent 在诊断后提供的执行约束，不是运行时自动生成的审美结论。最小字段为：

- `plan_id`
- `visual_goal`
- `recommended_level`
- `operations`
- `success_criteria`
- `must_preserve`
- `allowed_changes`
- `forbidden_changes`
- `stop_condition`
- `decision_source`
- `basis`
- `observation_sha256`

Plan 存在时，操作必须在 `operations` 中且不得超过 `recommended_level`。旧 L1/L2 case
为兼容仍可不带 Plan，血缘中标记为 `legacy-unplanned`。任何 L3 局部调整都必须带 Plan。

`observation_sha256` 是对完整 `ObservationResult` 使用 UTF-8、排序键、无多余空白的 canonical
JSON 计算所得。`basis` 必须引用有效 observation index、匹配 dimension，并逐字引用该观察项的
一条 evidence。edit/full 中带 Plan 时必须同时提交同一个 `source_observation`；运行时核对
Observation、Plan、输入图片的 hash 链，不重新生成另一份措辞可能漂移的 Observation。
非 `hybrid` Plan 不得携带反馈修订字段或 `parent_plan`；`hybrid` Plan 的六个修订字段必须
全部存在，并且必须同时提交可由 `parent_plan_sha256` 校验的 `parent_plan` artifact。

### Phase 输入契约

- `diagnosis`：只执行 V1，禁止 Plan、operations、comparison candidates 和 UserFeedback。
- `edit`：必须有 operations，只执行 V2；带 Plan 时必须同时提供匹配的 source Observation；hybrid Plan 还必须提供匹配的 parent_plan 和 trigger_feedback。
- `compare`：必须有已有候选，只执行 V3；禁止 operations，可提交绑定叶子候选的 UserFeedback。
- `full`：必须有 source Observation、绑定它的 Plan 和 operations，消费 V1 证据后执行 V2/V3；禁止已有候选和当前 UserFeedback，hybrid Plan 还必须提供匹配的 parent_plan 和 trigger_feedback。

已存在的最终候选只能通过 compare 复核。edit 成功只表示 V2 完成，不能声明 V3 或最终交付完成。

### 局部可逆调整

`local_adjustment` 固定为 L3，只接受矩形 `box`、`exposure`、`contrast`、`saturation`
和 `feather`。它输出新文件并保留父候选。"可逆"表示可以沿血缘回退到父候选或按记录参数重放，
不表示输出像素可以通过反向参数无损恢复。

### 候选血缘

每个候选记录：

- `candidate_id` 与 `parent_candidate_id`
- `plan_id`
- 输入/输出路径与 SHA-256
- 操作、参数和 `reversible`

父候选路径或 hash 不匹配时返回 `failed_invalid_contract`。V3 报告和 EvidenceRecord 必须保留
候选、父候选和 Plan 标识；RunResult 与 EvidenceRecord 还必须保留 hybrid Plan 的 `parent_plan`
artifact。

候选输出必须使用唯一规范路径，且不得与原图或其他候选通过硬链接指向同一文件。运行时在编辑前
保留输出路径、编辑后复核输入/输出 hash，并拒绝 provider 返回的操作、hash 或血缘与请求不一致。
同一个 case 不能同时提交 `operations` 和 `comparison_candidates`；compare-only 候选 ID 必须唯一，
父候选必须先于子候选出现，并携带实际 operation 和 parameters。

### Adapter 执行一致性

能力报告中的 V1/V2/V3 provider 必须是本次实际调用的 adapter。V2 adapter 实现
`edit(request)`；V3 adapter 实现 `compare(original, candidate, report_dir, ...)` 并返回完整、
可验证的 ComparisonResult。provider 缺少对应执行方法、执行异常或返回证据不一致时，运行时
fail-closed，不得静默切换到其他内置实现。编辑参数按操作对应的强类型 schema 校验，非法类型、
范围或多余字段返回 `failed_invalid_contract`。

### 完整能力报告

序列化能力报告必须包含 `input_path`、`input_exists`、`input_sha256`、`input_size`、
`capabilities`、`status`、`checked_at`、`adapters_checked` 和 `has_v0` 到 `has_v3`。
EvidenceRecord 保存完整报告，不得只截取 capability map。

### CLI 退出码

- `0`：`completed_phase`、`completed_with_user_feedback_pending`、`completed`、`rejected` 或 `changes_requested`
- `1`：契约或执行失败
- `2`：能力、输入或候选阻塞

---

## 八、Bundle 规则

**必须包含**：
- `SKILL.md`
- `references/`
- `scripts/`

**不能包含**：
- `.skill-work/`
- 原图、候选图
- 模型权重
- 密钥
- 运行状态
- `__pycache__/`、`*.pyc`、`*.pyo`
