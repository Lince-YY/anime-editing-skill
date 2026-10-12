# 安装后的小样验证

先检查已有环境，再跑有界小样。工具不安装软件、不下载权重、不上传文件、不租云、不自动运行真实模型。环境盘点与本脚本独立：环境报告可以未运行小样；版本或可用性信息不能代替小样通过。

```bash
python3 scripts/smoke_test.py --out /本地验证目录/report.json
python3 scripts/smoke_test.py --out /本地验证目录/cpu.json --python /已有/python --backend cpu
python3 scripts/smoke_test.py --out /本地验证目录/media.json --checks ffmpeg --ffmpeg /已有/ffmpeg --ffprobe /已有/ffprobe
```

仅使用 Python 3.9+ 标准库。默认检查 `ffmpeg,torch`；`--checks` 可选择 `ffmpeg,torch,case` 的逗号列表。`--backend` 为 `auto/cpu/cuda/mps`；auto 按 CUDA、MPS、CPU 实際可用性选一个，并在报告中写实际选择。`--python` 指向已有解释器，默认当前解释器，不创建虚拟环境。FFmpeg/ffprobe 默认在 PATH 查找，缺失时为 `missing`。

FFmpeg 检查实际生成 0.4 秒、64×64 的合成测试音视频，使用 FFV1 与 PCM 编码，ffprobe 验证真实编码、尺寸、采样率和时长，再分别完整解码视频与音轨。结果的 `scope=synthetic_media_smoke`，不能证明任何源素材、镜头或声音效果。

Torch 检查在独立子进程导入现有 torch，验证所选 backend 可用性，并在该设备执行三个元素的 tensor 平方求和，再取回数值。`scope=tensor_smoke`、`model_verified=false`，不加载模型。torch 未安装为 `missing`；指定设备不可用或导入/计算失败为 `failed`。每次 Torch 检查限 30 秒，媒体命令各限 20 秒。

## 用户提供的真实模型 case

`--case` 只执行用户显式提供的 JSON 入口。工具不扫描磁盘寻找脚本，不根据依赖、仓库配置或环境报告自动执行代码。调用前应读懂 argv 对应的脚本，确认本次模型、真实输入、设备、输出和授权范围。JSON 不是安全沙箱；它可以执行任意本地代码。提供 case 不隐式授权网络、下载、上传、付费或云任务；包含这些动作的入口必须先取得对应明确授权。设备参数需要写进 case 的命令，本工具的 `--backend` 不会替用户改写模型命令。

例如先准备好本地模型、权重、真实输入与一个不会联网的推理入口，再编写：

```json
{
  "command": ["/已有/python", "infer.py", "--input", "input.png", "--output", "sample.mp4", "--device", "cpu"],
  "cwd": "/本地样板目录",
  "timeout_seconds": 60,
  "outputs": [{
    "path": "sample.mp4",
    "type": "video",
    "min_bytes": 1024,
    "min_duration_seconds": 0.5,
    "max_duration_seconds": 5,
    "width": 512,
    "height": 512
  }]
}
```

```bash
python3 scripts/smoke_test.py --checks case --backend cpu --case /本地样板目录/case.json --out /本地验证目录/model.json
```

`command` 必须为非空 argv 字符串数组，使用 `shell=False`，不展开管道、shell 变量或命令替换。相对 `cwd` 基于 case JSON 所在目录；相对输出路径基于 cwd。timeout 默认为 60 秒，上限 300 秒，输出声明上限 16 个。退出码非零、超时、启动失败均为失败。POSIX 系统对子进程组执行终止与必要强杀，并有界回收，避免超时后留下同组后台进程；这不是对脱离进程组的恶意代码的隔离保障。Windows 的进程树清理尚未验证，case 不执行并记 `unknown`；媒体与 tensor 检查仍可独立运行。

每个声明的输出在执行前必须不存在；发现旧文件或符号链接会拒绝运行，不覆盖旧资产。执行后必须为新出现的普通文件并达到 `min_bytes`（默认 1）。此检查证明本次创建了声明路径，不能证明模型确实推理或文件没有复制其他素材。`type` 可为 `video/audio/image/file`；媒体必须能被 ffprobe 识别并由 FFmpeg 完整解码，工具缺失为 `unknown`，不假通过。video/audio 必须有正时长和相应轨道；image 验证尺寸与解码。可加精确 `codec,width,height,sample_rate,channels`，及 `min_duration_seconds/max_duration_seconds`。`file` 只验证存在与大小，不验证任意专有格式内容。

真实 case 的 `scope=user_model_case`，`model_identity=user_declared_unverified`、`backend_verified=false`、`effect_acceptance=false`。产物存在和可解码仍不代表用户效果验收；模型身份、实际设备、关键动作、口型、画面质量、声音听感及观看理解应另外留证并验收。没有真实 case 时，不能宣称模型小样已通过。

## 报告与证据

报告结构为 `schema_version,generated_at,checks,overall`。每项包含 `name,status,scope,backend,details`；status 为 `passed/failed/missing/unknown/skipped`。`overall` 优先级为 failed → unknown → missing → passed；全部跳过为 skipped。CLI 对 passed/skipped 返回 0，其余返回 1；参数错误返回 2。

报告旁建立每次独立的 `*-evidence-*` 目录，保存测试产物与 stdout/stderr 原始日志；报告只记路径、有限结构化数值与固定原因码，不内嵌原始日志、argv 或异常文本。原始日志仍可能包含脚本输出的密钥、路径或个人信息，留在本地，分享前自行审查脱敏。报告中的绝对路径也应在公开分享前处理。未被选择的检查不会暗示通过；显式选择 case 而不提供入口记 skipped。

```bash
python3 -m unittest discover -s tests -p 'test_smoke.py' -v
```

测试包含现有 FFmpeg 可用时的真实极短编码/探测/解码；缺失、超时、非零退出、旧输出保护与成功产物使用本地 fixture，不声称验证了真实模型。
