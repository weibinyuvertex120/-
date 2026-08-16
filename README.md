# 见相 Seeform

> 见相帮你把感觉变成画面。

## 它是什么

见相（Seeform）是一个面向 AI Agent 的视觉判断与转化 Skill。它从用户想表达什么开始，先理解照片、判断问题与潜力，再提出一个直接可理解的视觉观点，调用合适的编辑能力，并通过用户选择逐渐理解个人偏好。

Seeform 的核心体验是：

```text
一句感觉或用途 -> 一次简短观点 -> 一个默认方向 -> 少量候选 -> 一次用户决定
```

用户可以说“人物好看一点”“真实但更有状态”或“适合发小红书”。Seeform 应先给出判断和默认方案，不把内部的观察、诊断、路由和证据契约变成多轮问卷。

我始终相信，每一张照片都承载着意义、经历和回忆。

一张照片没有出现在你的社交媒体上，未必是因为它没有价值。可能只是构图没有被发现，光线没有被利用，色彩缺少层次，主体没有被突出，情绪没有被表达，场景还没有形成自己的视觉语言。

照片本身拥有的潜力，只是还没有被看见。

见相不只是给照片套用风格。它会先理解照片，发现照片的问题与潜力，再根据你想表达的感觉和使用场景，给出一个有理由的视觉观点，寻找合适的视觉语言和具体的改变。

## 为什么有用

你可以从一句感觉开始：

- “温柔一点。”
- “真实，但更有完成度。”
- “像生活中最好的一刻。”
- “人物状态很好，只是照片还没有成立。”

见相把这些抽象的感觉，转化为对构图、光线、色彩、主体、空间和质感的具体判断，帮助照片更接近它原本拥有的意义，也更接近你想表达的样子。

它不预设统一的审美，也不把每张照片处理成同一种风格。它关注的是：

> 这张照片已经拥有了什么，以及怎样才能让它被更好地看见。

## 开始使用

从 [Releases](https://github.com/weibinyuvertex120/seeform/releases) 下载最新部署包，并将其安装到支持 Agent Skill 的宿主中。

当前 MVP 支持：

- 图片文件读取与完整性检查；
- 最小 Visual Transformation Plan 校验；
- 曝光、对比度和饱和度调整；
- 裁切与尺寸适配；
- 带矩形区域和可选羽化的局部可逆调整；
- 原图和候选图的工程比较；
- 候选血缘、完整能力报告和 JSON / HTML 证据记录；

使用时提供：

1. 一张照片；
2. 你想表达的感觉；
3. 照片的使用场景；
4. 你希望保留的内容。

## 如何工作

```text
用户意图
-> 照片理解
-> 问题诊断
-> 视觉语言
-> 最小有效改变
-> 候选比较
-> 用户确认
```

见相不从滤镜开始，也不替用户决定什么才是美。它先理解照片，再给出照片真正适合的表达观点；用户只需用一句话确认或纠正方向。

## 与普通 AI 修图的区别

普通 AI 修图通常从一个动作或效果开始：美颜、调色、磨皮、换背景、扩图、消除或套用风格，重点是快速执行既定操作。

Seeform 的差异在于：

- 从“我想表达什么”开始，而不是从滤镜或参数开始；
- 先解释照片哪里没有成立，再决定改什么；
- 根据照片、用途和用户语言形成观点，不默认套用平台审美；
- 比较不同视觉策略及其代价，不只展示一张改前改后；
- 明确允许改变、必须保留和停止条件；
- 用一次简单确认替代用户反复试参数；
- 只从明确用户决定中形成可解释的个人视觉偏好。

Seeform 不声称底层编辑能力天然比成熟影像产品更强。模型负责生成，编辑器负责执行，Seeform 负责理解、判断、提案、约束、比较和反馈闭环。

## 能力边界

当前版本是面向 Agent 宿主的 Skill MVP，不是独立的照片编辑应用。

- V0 文件读取：已具备；
- V1 真实视觉观察：默认不可用；可通过宿主文件桥或本地 llama.cpp + Qwen3-VL GGUF adapter 按现场启用；
- V2 基础编辑：核心支持 Pillow 确定性 L1/L2，以及有 Plan 约束的矩形局部 L3 调整；不代表生成式 L3/L4；
- V3 工程比较：核心支持已有候选、父候选、尺寸、SHA-256、结构化像素指标和报告生成，不代表审美判断；
- 审美判断与最终确认：由宿主能力和用户共同完成。

见相曾在外部 WorkBuddy 宿主上完成过一个真实合照案例的观察、候选生成和工程比较，但该案例仍等待用户确认，不能当作内置 V1 能力或普遍质量证明。

当前版本不默认磨皮、变白、变瘦、改脸型、改变年龄感或生成新的真实事实。

## 本地验证

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q
```

安装后统一通过 `seeform` 执行：

```powershell
seeform --case .\case.json --output .\output
```

直接使用 Skill bundle 时，在 `skills/visual-art-direction` 下运行
`python -m scripts --case .\case.json --output .\output`；两种形式进入同一个 `scripts.runner:main`。

本地 Qwen3-VL 观察使用 `--llama-cpp-config` 接入已启动的 loopback `llama-server`。模型、
mmproj、启动命令和配置示例见
`skills/visual-art-direction/references/llama-cpp-local-observation.md`。

## 项目结构

```text
skills/visual-art-direction/
├── SKILL.md
├── references/
└── scripts/

tests/
dist/
```

## 版本

当前公开版本：`v0.1.0`

部署包：`seeform-visual-art-direction-v0.1.0.zip`

## 许可证

Apache License 2.0，详见 [LICENSE](LICENSE)。

## English

Seeform is a tool-agnostic visual decision and transformation skill for AI agents. It turns visual intent into a concise viewpoint, image diagnosis, editing decisions, and verifiable changes while keeping identity, scene relationships, and authenticity in view.

The product contract is documented in [PRODUCT.md](PRODUCT.md).
