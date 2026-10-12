# 实时进度接入

报告自动更新依靠一份项目记录和一个本机服务。用户打开一次页面，后续步骤、百分比、回执和媒体变化通过 SSE 推送，页面局部更新，无需手动刷新。服务运行期间默认每秒读取一次记录；制作工具本身没有提供进度时，不显示虚构百分比。

## 启动、写入、恢复

从 Skill 目录执行，路径换成项目私有输出目录。已有 flow.json 直接复用，不再 init。

```bash
python3 scripts/report_progress.py init --data output/flow.json --title "制作记录" --steps "准备,关键短样,剪辑,验收"
python3 scripts/serve_flow_panel.py --data output/flow.json --session-file output/.flow-panel-session.json
```

终端打印本机 URL 与进程号。另一个终端或制作代理写入记录：

```bash
python3 scripts/report_progress.py update --data output/flow.json --step 2 --status running --progress 40 --message "已完成真实任务返回的 4/10 个单元"
python3 scripts/report_progress.py update --data output/flow.json --step 2 --status ready --progress 100 --artifact /项目/sample.mp4 --output "短样已生成，动作尚待验收"
python3 scripts/report_progress.py update --data output/flow.json --step 2 --status accepted --message "原速检查通过，已记录用户接受"
```

示例百分比只是用法；实际使用必须有对应计数。`--report-json` 将显式 JSON 内容放进步骤详情，供环境和选路报告使用；不是执行该文件。`--artifact` 支持图片、音频、视频，可以加 `--asset-type`。初次生成的工具行仅是待补全框架：根据真实运行位置完善 flow.json 的工具、输入和方法，不能长期用“本机与服务”代替准确说明。

本地命令可以由包装器自动写入开始、成功、失败或取消：

```bash
python3 scripts/report_progress.py run --data output/flow.json --step 1 --log output/probe-001.log --report-json output/environment.json --output "体检报告已产出" -- python3 scripts/probe_environment.py --out output/environment.json
```

命令使用 argv，`shell=False`；不解释管道或 shell 变量。默认超时 600 秒，按已授权任务设置 `--timeout`，工作目录可用 `--cwd`。每次用新的日志名。退出 0 表示命令完成，自动设 `ready`；不证明报告内全部检查通过，也不证明真实镜头效果。非零、超时或取消记录 `failed`。子命令提供中间回执时，可由代理/适配器额外调用 update；包装器自身不解析任意工具的日志百分比。

浏览器、内置服务和云端任务由代理在拿到实际回执后 update。当前没有通用 AutoDL 轮询或下载适配器，不能声称页面直接监控尚未接入的任务，也不要为了显示“活跃”反复写假进度。真实任务回执接入后，用户只需看页面。

写入使用同目录锁与原子替换，避免并发丢记录或半截 JSON。需要编辑完整数据时，先读取最新内容；可用 `--expected-revision N` 防止更新过期版本。锁超时不会强占，先核对锁内 owner.json 对应写入者和任务；仅在确认写入者已退出后移除该任务的陈旧锁。

## 页面行为与边界

- 显示连接状态、最近有效记录时间和每步状态。断线自动重连，期间保留最近记录；不能误称数据仍实时。
- 临时无效 JSON 或缺媒体时，保留上一份有效记录并提示异常；修复后自动恢复。
- 常规状态/文字更新保留筛选、缩放、打开的步骤和未变化的媒体元素；新增/替换媒体或重排布局可能重建对应播放器。
- 使用相同 `--session-file` 和 flow.json 重启可恢复原端口与 URL；原端口被其他程序占用时明确失败，不自动改址误导旧页面。session 文件只存本机恢复信息，不上传。新项目使用新 session 文件。
- 页面关闭会释放 SSE，浏览器返回已缓存页面时重连。电脑休眠或服务停止期间不能更新；服务恢复后读取最新完整快照。

HTTP 仅绑定 127.0.0.1，带随机路径并校验 Host/Origin，无上传、安装或命令执行 API。媒体只允许 flow.json 显式引用的本地文件，支持 Range 播放；不开放项目目录浏览。不要把它作为公网服务、绑定到局域网或通过隧道公开。报告文字和引用素材仍是用户数据；公开分享另作审查。

## 结束与离线交付

结束或稳定暂停时先写最终真实状态，生成到新目录：

```bash
python3 scripts/build_flow_panel.py --data output/flow.json --out output/snapshot-001
```

离线包保留数据和媒体副本，不接收后续进度。确认产物保存后对本任务服务按 Ctrl+C；不要停止其他项目服务。保留 flow.json、session 文件与启动命令便于继续。若当前仍需向用户展示实时执行，记录服务进程、用途和停止条件，完成后回收。快照包含原文和素材，公开前审查敏感内容与素材授权；不要上传本机环境报告或模型日志。

## 复验

`python3 -m unittest discover -s tests -p test_live_flow.py -v` 覆盖同一 SSE 连接的更新、异常与恢复、媒体 Range、访问白名单、并发写入和命令状态。再用浏览器实际打开一次报告，由命令改变记录，确认页面自行更新；打开详情播放合成小样，改变其他步骤，确认播放未归零。网络层测试不能代替页面实际验收。
