# Anime Editing Skill · 动漫混剪

把动漫二创创意推进到可验证镜头：研究原作与参考，挑选真实素材，验证最难动作，再完成对白、口型、字幕、混音与交付。

这是给 Codex 使用的制作方法、验收标准、环境准备工具及实时/离线操作流面板。动画生成、语音合成与剪辑依靠另行准备的工具、模型和素材；安装本仓库不会自动安装它们。

**当前版本：制作方法 + 环境体检/选路 + 技术小样验证 + 实时 H5 报告。完整自动部署和跨机器端到端复现尚未验证。**

## 能做什么

| 任务 | 本仓库提供 | 需要另外准备 |
|---|---|---|
| 单番音乐叙事 / AMV | 选材、情绪与乐句组织、试听验收方法 | 原片、音乐、实际剪辑工具 |
| 跨番新剧情 | 原作核对、镜头顺序、动作和空间连续性检查 | 可用素材及对应软件能力 |
| 原作没有的新动作 | 完整关键画稿 → 固定线稿 → 动作生成的样板经验 | 绘图/图像工具、动画模型及合适算力 |
| 新对白与口型 | 声线/咬字/响度分别验收，按发声和停顿调整嘴部 | 声音参考、语音工具、口型制作能力 |
| 局部返修 | 保留已认可片段，定点调整对白、音乐、字幕和清晰度 | 分轨或可追溯的同源素材 |
| 环境体检 | 检测 CPU/RAM/磁盘、GPU 类型与显存、软件和 CUDA/MPS 状态 | Python 3.9+；受限或未知项目如实报告 |
| 安装与选路 | 按任务给官方工具入口、隔离安装建议、本机/云端条件建议 | 模型要求与真实短样复验；安装和付费沿用授权 |
| 安装后验证 | 合成音视频编解码、已有 Torch 张量、显式用户 case 的有界检查 | 已安装工具、真实模型输入与入口 |
| 展示制作过程 | 实时 H5 自动更新，保留产物播放和离线快照 | Python 3.9+、现代浏览器；实时模式需本机服务运行 |

## 安装与开始

仓库根目录就是完整 Skill 文件夹。下载后将文件夹命名为 `anime-editing`，放入当前 Codex 使用的本地 Skill 目录，保留 `references/`、`scripts/` 和 `assets/` 的相对位置。

按当前官方文档，可放在项目的 `.agents/skills/anime-editing/` 或用户的 `~/.agents/skills/anime-editing/`。也可以让 Codex 的 `$skill-installer` 从本仓库安装。不要覆盖已有同名版本；先比较或备份。安装目录与发现行为以所用版本的 [OpenAI 官方说明](https://learn.chatgpt.com/docs/build-skills) 为准。

安装后给 Codex 一个具体请求，例如：

```text
使用 $anime-editing，把我的跨番创意做成镜头方案。
素材是我提供的原语言高清版本；允许为缺失动作新绘。
先核对原作、找到镜头，再验证最难的持物动作。
当前先交方案与短样，付费服务和发布另行确认。
```

如果只想学习方法，直接阅读 [SKILL.md](SKILL.md)，不需要运行脚本。其他支持 `SKILL.md` 的代理可参考其导入方式；本仓库没有逐一验证其他客户端。

## 先运行一个不需要 GPU 的示例

在仓库目录执行：

```bash
python3 scripts/build_flow_panel.py --data assets/flow-panel/example.json --check
python3 scripts/build_flow_panel.py --data assets/flow-panel/example.json --out output/demo
```

用浏览器打开 `output/demo/index.html`。示例明确标为“未执行”，只演示制作记录界面，没有动画素材。再次构建时使用新的输出目录；脚本拒绝覆盖已有目录。

脚本仅用 Python 标准库，发布候选已在 Python 3.9.6 上验证。它会检查数据、复制显式指定的本地媒体、核对 SHA-256，并生成 HTML/CSS/JS；不会联网下载、剪辑视频或调用模型。面板使用本地资源，无需 CDN 或网页服务器。

实际案例的数据结构和媒体打包方式见 [visual-flow.md](references/visual-flow.md)。媒体会被复制进输出目录；分享前检查其中的素材、文字和路径信息，敏感数据不要填入公开面板。

## 环境体检、选路和实时报告

从仓库根目录执行。`output/` 是本机私有结果，不上传 GitHub。

```bash
python3 scripts/report_progress.py init --data output/flow.json --title "我的动漫制作" --steps "环境体检,选路与安装,关键短样,剪辑与验收"
python3 scripts/serve_flow_panel.py --data output/flow.json --session-file output/.flow-panel-session.json
```

打开服务打印的本机 URL。保持该终端运行，在另一终端执行：

```bash
python3 scripts/report_progress.py run --data output/flow.json --step 1 --log output/probe.log --report-json output/environment.json --output "环境报告已生成" -- python3 scripts/probe_environment.py --out output/environment.json --check-torch
python3 scripts/report_progress.py run --data output/flow.json --step 2 --log output/plan.log --report-json output/plan.json --output "安装与选路建议已生成，执行条件待核对" -- python3 scripts/plan_environment.py --environment output/environment.json --tasks editing,animation,voice,panel --out output/plan.json
python3 scripts/smoke_test.py --out output/smoke.json
```

前两项的开始、结束、失败会自动推送。第三项按实际检查结果登记到第 3 步：缺工具写缺失，检查失败写失败，不能因报告文件存在就写模型通过。完成具体准备后再做真实模型短样。重复运行要使用新的日志名；现有 `flow.json` 继续更新，不重复 init。

**通讯链路：制作步骤 → 原子写入项目记录 → 本机服务 → SSE → 页面局部更新。** 默认约 1 秒检查一次记录，不根据预计耗时伪造百分比。实时服务只监听 127.0.0.1，断线自动重连；使用相同 session 文件重启服务可保持地址。暂停或关闭电脑期间没有实时更新，页面明确显示连接状态。直接打开离线 HTML 仅查看当时快照。

代理需要为云端、浏览器或其他外部工具接入真实状态回执；这版不自动轮询任意 AutoDL 任务，也不解析聊天内容猜测进度。安装建议由脚本给出，实际安装、启动和收费仍按当前任务授权执行；不提供一键开云 GPU。

操作详见[环境准备](references/environment-setup.md)、[小样验证](references/environment-verification.md)和[实时进度](references/live-progress.md)。

## 实际验证到哪一步

一个跨番短片样板在 2026-10-09 获创作者接受，并由创作者报告已发布。验证过的组合路线是：原片叙事、完整关键画稿、固定线稿、短动作生成、日语对白、简单嘴部开合、双语字幕、分轨返修及超分输出。

样板里，原片局部替换道具曾出现手与物漂移；增加跟踪没有解决关键握姿缺失。改用完整画稿后，比较了反向动作生成再倒放的做法。后期把声线、咬字、口型、响度与镜头长度分别处理。具体取舍和失败边界见 [已验证路线](references/validated-reanimation.md)。

这只是一个已接受样板。没有独立核验其平台发布页或传播表现；公开包不附带原片、角色声音、画稿或私有工程，因此读者仍需用自己的输入复验。它不保证任意角色、长动作或复杂交互能自动成功。

新增动作当时以 832×480、20fps 生成，后经超分汇入 1080p 成片；这不等于原生 1080p 动画或已解决全部流畅度问题。

## 软件与硬件边界

阅读、策划和面板生成不需要 GPU。实际剪辑要另有原片、足够磁盘及可用编辑器；FFmpeg、Resolve、AE 等按任务选用，不要求全部安装。

样板的新绘流程曾使用内置图像生成、Anime2Sketch、ToonComposer / Wan2.1、GPT-SoVITS 和 Real-ESRGAN。它们不随本仓库分发。图像生成服务不因此变为开源；也不能把整条已验证路线称为全开源或完全免费。使用其他绘图方法可以作为替代实验，但尚未证明与该样板等效。

动画生成阶段使用过云端 A800 80GB；这是样板环境，不是已测得的最低要求。本仓库没有完整的一键部署脚本或全套模型环境锁定文件。复用前按上游版本验证显存、依赖和预算，先跑关键动作短样。工具与模型入口见 [THIRD_PARTY.md](THIRD_PARTY.md)。

当前配套脚本在 macOS 实机完成体检、合成媒体检查和实时浏览器更新验证；Windows/Linux 硬件解析与选路使用 fixture，未作实机端到端保证。Torch 或模型未安装时如实标缺失；本次升级没有重新生成动画。

可运行 `python3 -m unittest discover -s tests -v` 复验。FFmpeg 不在 PATH 时，真实媒体测试会跳过，其余固定输入测试继续。

## 文件导航

- [SKILL.md](SKILL.md)：入口、路由、执行与验收边界。
- [workflows.md](references/workflows.md)：音乐叙事与跨番剧情方法。
- [crossover-compositing.md](references/crossover-compositing.md)：局部合成控制能力与不适用条件。
- [validated-reanimation.md](references/validated-reanimation.md)：已接受的新绘动作及声音路线。
- [pilot-schema.md](references/pilot-schema.md)：素材、时间轴与验收记录。
- [evidence.md](references/evidence.md)：研究来源和证据等级。
- [visual-flow.md](references/visual-flow.md)：面板数据与生成方法。
- [live-progress.md](references/live-progress.md)：实时服务、命令进度与恢复。
- [environment-setup.md](references/environment-setup.md)：体检、安装建议和按任务选路。
- [environment-verification.md](references/environment-verification.md)：有界技术小样与真实 case。

## 贡献与许可

欢迎提交可复现的错误、方法改进和使用反馈。请说明输入类型、工具版本、失败现象、最小复现与验证结果；尽量用自有或合成小样，不在 Issue / PR 中上传未获授权的原片、角色声音、个人数据或密钥。

本仓库采用 [MIT 许可证](LICENSE)，允许使用、修改和再分发，并要求保留版权与许可声明。仓库自身的许可不覆盖外部动画、音乐、声音、模型权重或第三方工具；参见 [第三方说明](THIRD_PARTY.md)。

---

An anime-editing workflow skill for Codex, with environment planning, bounded smoke checks, and live/offline production-flow panels. The repository contains instructions and templates, not anime footage, voice samples, model weights, or a one-click animation pipeline. The reanimation route has one creator-accepted pilot; external tools and independent validation are still required.
