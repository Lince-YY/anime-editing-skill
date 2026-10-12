# 可视化操作流

多步骤制作进入面板交付，或用户需要查看制作全貌、方法证据与交接时，读本页。用项目已有资料生成离线面板：顶部横轴为步骤，右侧纵轴为工具；节点展示真实产物，点步骤展开输入、方法、产物和运行信息。图片可放大，视频、音频可播放。步骤数随实际流程变化，不固定套样板的十步、工具或硬件。

## 从事实到面板

1. 先核对当前阶段、接受版本、工程、执行回执和实际媒体。按关键产物划分步骤，同一步可有多个工具节点。缺产物写“计划”或“缺失”，无验收写“待验证”；不要用占位图或早期版本冒充完成。
2. 在项目目录整理 `flow.json`。每步填写输入、做法和输出；脚本入口、实际提示词、参数、模型版本、来源与验收证据写入 `content`、`models`、`notes`，长原文留项目文件并给可追溯路径。界面提交不等于本机推理：明确本机 CPU、本机 GPU、远程云 GPU、内置服务；硬件、后端或加载状态无证据时写“未知/未记录”。`place` 只分位置，CPU/GPU 写入说明。
3. 媒体 `src` 用相对 JSON 目录或本地绝对路径，供生成器读取。先统计涉及文件体积与输出盘余量；超大体积先说明预计复制量，再按当前任务范围选择必要样本。生成器只复制媒体、生成页面，不转码或执行模型。确有编码兼容问题才另制播放副本，保留原件并记录转换参数与用途，`original_src` 指向原件。
4. 生成到新的项目输出目录：

   ```sh
   python3 <skill>/scripts/build_flow_panel.py --data <flow.json> --check
   python3 <skill>/scripts/build_flow_panel.py --data <flow.json> --out <new-directory>
   ```

   输出 HTML、脚本与 `media/` 相对引用，不依赖 CDN。检查引用、连线、状态和版本；离线打开，抽查图片、视频、音频及步骤详情。技术可播放与内容验收分别记录。
5. 制作中的变化按[实时进度接入](live-progress.md)写入 JSON，由服务推送给页面，不重建整页或要求用户刷新。阶段完成、稳定暂停或分享时才导出新的离线版本。项目素材、提示原文和执行证据留项目；Skill 只存通用模板、生成器及说明。面板不扩展为模型执行器，不控制云实例，也不新增付费或发布授权。

## 最小字段索引

以下为通用 JSON 合同；不用的数组保留为空。所有引用须存在，步骤 `id` 连续为 `1..N`，节点 `id` 唯一。未知状态用文字说明，禁止推断成功。

```text
meta: {title, brand, date(YYYY-MM-DD), lead, revision?, updated_at?, final_step?, final_label,
       environment_legend[{place,text}], footer[], final_caption?}
steps[]: {id, short_title, title, subtitle, status, progress?(0..100), message?, updated_at?, environment, tools[],
          input, action, output, content, models[], notes[], media[asset_id]}
assets: {asset_id: {id, type(image/video/audio), title, caption, src,
                   original_src?, status}}
runtime[]: {id(对应step_id), models[{role, file, state}]}
chart: {lanes[{name, place(local/cloud/service/hybrid), tag?, detail}],
        nodes[{id, row(0起), step(step_id), place, title, asset?,
               poster?(图片asset_id), caption, text?, status?}],
        links[[起点node_id, 终点node_id]]}
runtime_groups[]: {place, label, title, description, ids[step_id]}
handoff?: {title, description,
           items[{step, place, tag, title, caption}]}
```

`final_step` 指实际用于最终查看的步骤，尚无成片时 `final_label` 明示样段/计划；不写“已完成”。`environment_legend` 提供运行位置图例，`runtime_groups` 汇总机器与服务；模型文件存在、配置指定、实际加载成功须分别表达。`chart.nodes.asset` 和 `poster` 引用 `assets`，`row` 对应工具行，`links` 表达产物依赖与交接。`text` 可展示真实计划或文字产物；它不代替缺失媒体。`handoff` 仅突出本项目重要交接，没有必要则省略。

步骤 `status` 必填：`planned`（计划）、`running`（制作中）、`ready`（已产出，未必通过验收）、`accepted`（已接受）、`missing`（缺产物）、`failed`（未通过）。无媒体时资产可省略 `src`，但状态必须为未完成；有 `src` 却找不到文件会报错。同一工具行的同一步只放一个节点，多个产物通过步骤详情展示。`--check` 校验引用并统计复制体积，不写文件。

可从[三步未执行示例](../assets/flow-panel/example.json)改成项目数据；保留真实状态。新目录生成避免覆盖已接受版本。生成器的哈希检查只证明副本一致，不证明播放、动作或听感通过。
