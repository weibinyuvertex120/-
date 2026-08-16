# Seeform Domain Glossary

## Visual Intent

用户对照片想表达的感觉、状态或用途，例如“人物好看一点”“真实但更有状态”“适合发小红书”。Visual Intent 可以包含允许改变、必须保留和真实性模式，但用户不需要用结构化字段表达它。

## Source Fact

可以从原片直接观察到的内容，以及明确记录的不确定性。Source Fact 不包含未经证实的身份、年龄、性别、职业、健康、经历或故事推断。

## Visual Diagnosis

基于 Source Fact 对照片主问题、次问题、潜力、可恢复性和最小改造等级的判断。Visual Diagnosis 是观点的依据，不等于用户已经接受的审美结论。

## Visual Viewpoint

Seeform 面向用户给出的简短判断：照片哪里没有成立、什么值得保留、建议先改变什么，以及该方向如何服务用户用途。Visual Viewpoint 连接内部判断和低负担用户交互。

## Transformation Candidate

一次有明确策略、输入来源、输出 hash、父候选、允许改变、必须保留、停止条件和残余风险的视觉改造结果。候选之间应有可理解的策略差异。

## User Decision

用户对具体候选作出的明确决定，包括接受、拒绝、要求调整或自然语言纠正。User Decision 必须绑定候选身份和 hash，不能由模型或工程比较器代填。

## Personal Visual Preference

从多个明确 User Decision 中提取的、可解释且可能稳定的用户偏好。单次反馈只是一条证据，不能直接晋升为长期偏好。

## Overall Credibility

评价人像或照片改造是否仍然成立的综合判断，至少关注人物、材质、光线、场景关系和表达完成度。它不能被单一像素差异、模型分数或“更好看”替代。

## User Surface And Internal Layers

Seeform 的后台可以保留 Visual Intent、Source Fact、Visual Diagnosis、Transformation Candidate 和 User Decision 五层；用户入口保持单轮、直接和低负担。用户首先看到 Visual Viewpoint、默认方向和少量候选差异。
