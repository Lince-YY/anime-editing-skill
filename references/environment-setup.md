# 本机体检与按任务选路

先读取本机事实，再决定只为当前任务准备什么。两个脚本只用 Python 3.9+ 标准库，输出 JSON 采用同目录临时文件加原子替换；不安装依赖、不租云实例、不调用模型生成、不上传、不读取凭证或账户。体检报告可能含本机软件路径，保存在任务私有输出目录，不提交公开仓库。

```bash
python3 scripts/probe_environment.py --out /your/private-output/environment.json
python3 scripts/plan_environment.py --environment /your/private-output/environment.json --tasks editing,lineart,animation,voice,upscale,panel --out /your/private-output/environment-plan.json
```

`--disk-path /path/to/media` 指定实际素材所在文件系统。可选 `--check-torch` 仅在有明确需要时，在有超时的子进程中导入当前 Python 已有的 torch；不安装 torch、不加载权重、不跑模型。不同虚拟环境结果可能不同，请用计划执行模型的 Python 重测。

已有模型目录通过显式路径检查，脚本只看预定标志文件，不遍历磁盘：

```bash
python3 scripts/probe_environment.py --check-torch --tool-root tooncomposer=/path/to/ToonComposer --tool-root anime2sketch=/path/to/Anime2Sketch --out /your/private-output/environment.json
```

支持的目录 ID 是 `anime2sketch,tooncomposer,gpt_sovits,real_esrgan`。目录标志存在只证明找到源码位置，不证明依赖、权重、启动或激活成功。编辑器发现限于 PATH 和少量常见安装路径；发现不到写 `unknown`，不据此要求重装。CPU、RAM、GPU通过 macOS `sysctl/system_profiler`、Windows CIM、Linux `/proc/lspci` 和已安装的 NVIDIA 工具获取。命令超时、权限或解析失败写 `unknown`；工具确实不在 PATH 写 `missing`。GPU枚举不完整与确实不存在分别处理。

## 稳定字段与边界

体检 `schema_version=1.0`：

- `generated_at`：带 UTC 时区的生成时间。
- `host{os,arch,cpu,ram_gb,disk_free_gb}`：OS是 `Darwin/Windows/Linux`；未知值为 `null`。容量字段以 GiB（1024³字节）记录，历史字段名保留 `_gb`。
- `gpus[]`：`vendor,model,memory_gb,memory_kind,kind,source`。`memory_kind` 为 `dedicated/shared/unified/unknown`；`kind` 为 `discrete/integrated/unknown`。Apple统一内存记录主机RAM规模，不能当作等量独立显存或当前可用GPU内存。Windows CIM显存字段可能截断，不用于容量判断。
- `gpu_detection`：`reported/partial/unknown`；`gpus=[]` 配合 `unknown` 表示未知，不表示没有GPU。
- `tools{}`：工具项包含 `status(found/missing/unknown),path,version,reason`；`video_editors` 为编辑器项映射。
- `backends{cpu,cuda,mps,torch}`：各项 `status(available/unavailable/unknown/not_checked)`；CPU可用仅指Python可运行；CUDA/MPS可用仅指torch报告，不是模型测试。
- `warnings[]`：失败、枚举范围与已知限制。

选路任务枚举是 `editing,lineart,animation,voice,upscale,panel`，只准备选中的任务。`assets/tool-profiles.json` 列出官方入口、核验日期、需求、兼容边界、许可入口、版本策略及隔离/回滚建议。选路报告的每个 `tasks[]` 包含 `task,route,backend_candidate,reasons,unknowns,missing_tools,install_plan,pilot_evidence,execution_ready,execution_gate`。`route` 可为 `local/local_gpu/cloud/hybrid/manual_check`；当前自动规则不需要输出hybrid，组合任务可以人工选择本机剪辑加云端生成。

`install_plan` 区分确认缺失和安装状态未知：前者给按需安装，后者先检查现有环境。每步含官方来源、版本策略、隔离、下载大小未知、回滚及安装后验证命令。命令是供审阅的建议，不由脚本执行。安装或权重下载按本次授权进行；官方某些启动脚本会自动下载权重，启动前先查清。不要为了几个模型把不同要求强塞入当前环境。

[ToonComposer官方README](https://github.com/TencentARC/ToonComposer#-configuration)称480p、61帧生成约需57GB显存，默认设备是CUDA。这是特定工作量观察，不是本仓库测得的最低配置，也不是任意参数的硬门槛。当前自动规则用单张NVIDIA专用显存与该参考负载比较，不相加多卡容量；达到只成为本机GPU候选。低于时给云端条件建议，未知时人工核对；其他优化或CPU路线需另有当前目标实测证据。

声线、线稿和超分可以先评估CPU小样。MPS可用不自动证明任意工具支持MPS；GPT-SoVITS训练与推理分开，上游macOS训练质量提示应查当前版本。Real-ESRGAN CPU需核对float32与tile配置。实际瓶颈才是扩大云端或购买硬件的依据。

## 对接真实技术样测

可用 `--pilot-results /path/to/smoke.json` 读取技术样测报告；它不运行样测。支持 `schema_version` 与 `checks[{name,status,scope,backend,details}]`。任务范围声明的 `name` 等于上述任务ID、`backend`等于选中候选后端且 `scope`非空时，保存其声明状态；不自动认证。对本仓库 `smoke_test.py` 的真实报告，按下面的限定规则记录 `pilot_evidence.partial_checks`：

- `ffmpeg + synthetic_media_smoke + backend=null/cpu` 只作为 `editing` 的合成媒体编解码技术部分证据，不能证明真实剪辑或效果。
- `torch + tensor_smoke` 仅当后端与该模型任务候选相同，记录张量运算的后端部分证据，不能证明模型依赖、权重或镜头。
- `case + user_model_case` 仅记录同后端的用户用例输出检查；任务归属为 `unknown`，模型身份、实际模型后端与效果仍未验收。

部分检查即使 `passed`，汇总任务状态仍为 `unknown`，`task_verified/model_verified/effect_acceptance`均为false。无关名称、scope或不匹配/auto后端忽略并保留 `unknown`；`execution_ready=false`不变。示例任务声明：

```json
{"schema_version":"1.0","checks":[{"name":"editing","status":"passed","scope":"synthetic 2-second CPU encode/decode; exact recorded version","backend":"cpu","details":"See private technical report"}]}
```

传入证据仅作为有范围的声明保存，脚本不认证来源、时效或目标一致性。全部结果保持 `execution_ready=false`，需要本次任务审阅与授权。技术通过不能推导真实镜头、声音、观众理解或用户接受。`--cloud-authorized/--upload-authorized`只记录已有授权，默认false；即使true也不执行云端、收费或上传。没有费用、提供商或素材上传授权时，云端建议始终条件化。

## 验证范围

运行 `python3 -m unittest discover -s tests -p test_environment.py -v` 可验证纯函数与固定输入的选路、超时和失败解析。跨平台实现不等于跨平台实机验收：本次只在macOS实机执行只读体检；Windows/Linux与不同GPU容量由fixture覆盖。没有在此流程安装模型或做动画/语音/超分生成。获得当前任务的真实输入、目标和执行授权后，再建立单工具短样，记录准确参数、耗时、峰值显存和恢复点。
