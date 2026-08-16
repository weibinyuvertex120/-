# llama.cpp + Qwen3-VL 本地视觉观察

仅在需要启用本地 V1 视觉观察时读取。此路径使用 llama.cpp 的 `llama-server` 多模态接口，
不会把模型或照片发送到远端。

## 能力边界

- provider：`qwen3-vl-4b-llama.cpp`
- 模型：`Qwen/Qwen3-VL-4B-Instruct-GGUF`
- 能力：仅 V1 结构化视觉观察
- 输入：单张本地图片和 `observation_prompt`
- 输出：由 adapter 绑定 provider、版本、输入 hash 和 prompt hash 的 `ObservationResult`
- V2/V3：继续使用 `deterministic-pillow` 和 `local-compare`

第一阶段只允许 loopback 地址。adapter 不启动进程、不下载模型，也不接受远程 base URL。
llama.cpp 多模态仍处于快速演进期，部署时应记录实际 llama.cpp build/version；升级后重新跑 adapter
回归和一张真实照片用例。

## 准备 llama-server

官方 GGUF 仓库当前提供：

- `Qwen3VL-4B-Instruct-Q4_K_M.gguf`
- `mmproj-Qwen3VL-4B-Instruct-F16.gguf`
- `mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf`

llama.cpp 的 `-hf` 会在仓库存在 mmproj 时自动获取对应文件。首次启动可以使用：

```powershell
llama-server `
  -hf Qwen/Qwen3-VL-4B-Instruct-GGUF:Q4_K_M `
  --alias Qwen/Qwen3-VL-4B-Instruct-GGUF `
  --host 127.0.0.1 `
  --port 8080 `
  --jinja `
  --ctx-size 8192 `
  --n-gpu-layers auto
```

已有本地文件时可以显式指定：

```powershell
llama-server `
  --model C:\models\Qwen3VL-4B-Instruct-Q4_K_M.gguf `
  --mmproj C:\models\mmproj-Qwen3VL-4B-Instruct-F16.gguf `
  --alias Qwen/Qwen3-VL-4B-Instruct-GGUF `
  --host 127.0.0.1 `
  --port 8080 `
  --jinja
```

`--alias` 必须与 adapter config 的 `model` 一致，否则 healthcheck 不会暴露 V1。

## 配置与运行

复制同目录的 `llama-cpp-qwen3-vl.config.example.json` 到运行时工作目录后按现场修改。
不要把密钥或机器特定路径提交到 Skill。

```powershell
seeform `
  --case C:\cases\photo-001\case.json `
  --output C:\cases\photo-001\output `
  --llama-cpp-config C:\cases\photo-001\llama-cpp.json
```

`requested_phase=full` 时，runner 会按同一证据链依次执行：

1. 读取 diagnosis 阶段保存的 Qwen3-VL `source_observation`；
2. 校验其 canonical SHA-256 与输入 Plan 的 `observation_sha256` 一致；
3. 内置 V2 编辑；
4. 内置 V3 工程比较；
5. 写入完整 EvidenceRecord，状态进入 `completed_with_user_feedback_pending`。

因此 full 不是首次观察后由 runner 自动生成艺术决策。应先用 diagnosis 获得结构化 Observation，
由宿主或 Agent 基于它生成带 `decision_source`、`basis` 和 `observation_sha256` 的 Plan；full 消费
这份不可变 V1 证据并验证来源绑定。模型即使 seed 固定也可能发生等义措辞漂移，所以不能通过
重新观察来替换 Plan 实际引用的 Observation。已有最终候选应使用 compare，不得用 edit 冒充 V3。

## 失败条件

以下情况必须 fail-closed：

- llama-server 不可达；
- `/v1/models` 不包含配置的 model ID；
- server 明确报告模型不支持 image input；
- 模型响应不是 schema-valid JSON；
- observation provider、输入 hash 或 prompt hash 与本次请求不一致；
- 每条观察没有可见 evidence。

官方来源：

- <https://github.com/ggml-org/llama.cpp/tree/master/tools/mtmd>
- <https://github.com/ggml-org/llama.cpp/tree/master/tools/server>
- <https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF>
