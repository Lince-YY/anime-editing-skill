# 来源与成熟度

初次整理于2026-10-04；动态合成方法增补于2026-10-06。来源是研究依据，不是所有步骤都已由本机复现。

- 5条用户指定动漫作品：主要为画面抽样；一条有本地全片跨度联系表，未完成5条完整音轨听审。
- B站16、抖音8条教程/作者经验入口：访问层级包括正文、简介目录、画面抽查，不能称24条视频全部看完。
- 基础剪接、变速、叠层、字幕、混音有既有工程和成片；复杂动态同框及动漫音乐审美需要真实样板。

关键公开来源：
- [omokage：AMV剪辑心得](https://www.bilibili.com/video/BV1Zb4y1S7q5/)：作者长简介中的表达与信息取舍。
- [CaptainX：MAD/AMV正道教程](https://www.bilibili.com/opus/78157645896715991)：透视、选材与原有光效。
- [-Kira-R创作复盘](https://www.bilibili.com/opus/964741193356279809)：静止系分层、补图和运镜，非动态战斗通解。
- [lolligerjoj原文](https://lolligerjoj.wordpress.com/2016/10/22/twixtor-on-anime-footage-and-ae-workflow-using-twixtor/)与[B站译文](https://www.bilibili.com/opus/82666859045536657)：作画拍数和补帧。旧版参数用前重验。
- [RE:Vision官方](https://revisionfx.com/faq/how_do_i_get_the_most_out_of_twixtor/)：快速运动/遮挡等补帧限制。
- [Adobe Roto流程](https://helpx.adobe.com/after-effects/desktop/roto-brush-and-refine-matte/roto-brush/roto-brush-refine-matte.html)：传播、修正和冻结。
- [抖音抠像转场](https://www.douyin.com/video/7360632620981488933)：画中画进入与人物分离，不能等同复杂同框互动。
- [南门录像厅音乐重构](https://www.douyin.com/video/7621062321426681088)：章节和部分画面验证，未完整听审。

不采用：按标题补写教程、固定插件/帧率/时长公式、场景检测自动理解剧情、参考作者成片自动取得素材授权、导出成功等于内容成立。

## 动态合成增补的证据级别

可执行方法见[跨番动态合成](crossover-compositing.md)，其中链接直接指向支持步骤的来源。核验的是方法文档与作者正文；未宣称完整观看全部教程，也未取得废宅羊的作者自述工程，不能断言其使用某个软件。

| 来源 | 本次真正获得的证据 | 仍不能证明 |
|---|---|---|
| [Adobe跟踪文档](https://helpx.adobe.com/after-effects/desktop/animate-in-after-effects/track-motion/tracking-stabilizing-motion-cs5.html) | Mocha跟踪导出、matte、羽化导入差异 | 本机自动跟踪和手指Roto质量 |
| [Resolve20 VFX官方训练书](https://documents.blackmagicdesign.com/UserManuals/DaVinci-Resolve-20-Fusion-Visual-Effects.pdf) | 免费版课程、平面变换及蒙版流程 | 当前版本所有自动化权限、本机性能 |
| [Blender平面跟踪](https://docs.blender.org/manual/en/4.4/movie_clip/tracking/clip/editing/track.html) | 同平面点与Plane Track操作条件 | 缺失物体视角、无GUI跟踪已跑通 |
| [Reisir蒙版正文](https://amv.tools/after-effects/masking) | 分部位动画蒙版、接缝重叠 | 完整跨番动态持物工程 |
| [Tfrog动漫Roto正文](https://amvtutorial.com/tutorials/anime-rotoscope) | 特定颜色/区域分离的实际方法 | 通用自动抠像准确率 |
| [Adobe Clone Stamp](https://helpx.adobe.com/after-effects/desktop/drawing-painting-and-paths/paint-tools-and-paint-strokes/paint-tools-brush-clone-stamp.html) | 跨时间/位置复制已有源像素 | 原片从未出现的形状与动作 |

[Tfrog合成拆解](https://tfrog.de/en/tutorials/anime-compositing/)本次只核到官网图层索引，未看完整视频/运行工程；[侑子_Yuuko的B站合成教程](https://www.bilibili.com/video/BV1ET421y7bH/)只核到简介，不据其标题编写流程。CaptainX和-Kira-R属于旧来源增量回读，不包装成新增完整动态案例。

“原镜头底层＋道具层＋原手指前景层”的持物方案，是由上述控制能力综合形成的工程推导；不是某作者工程的照搬，也不是本机样板通过。纯原片插镜配新对白曾未达到用户的同场互动要求，因此仅完成结构验证、技术导出、抽帧或语音识别都不得触发整片扩展。

硬件判断另查当前官方需求和实机负载：[AE要求](https://helpx.adobe.com/after-effects/desktop/get-started/technical-requirements/system-requirements.html)、[Blender要求](https://www.blender.org/download/requirements/)、[SAM3官方要求](https://github.com/facebookresearch/sam3)。满足内存下限不等于本机动态合成通过；分割模型能出mask也不等于事件能成立。
