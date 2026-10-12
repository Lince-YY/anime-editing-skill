# 第三方工具、来源与素材

本仓库分发的是制作方法、参考索引、通用面板模板和生成面板的 Python 脚本。没有捆绑下列项目的源代码或权重，也没有捆绑番剧视频、截图、角色声音、音乐、关键画稿或制作工程。

本仓库的 [MIT 许可证](LICENSE)只适用于本仓库自身可授权的内容。链接到第三方项目不表示取得其所有内容的再分发权，也不改变其软件、模型、训练数据或服务条款。使用时阅读对应版本的上游许可和模型说明，不以“代码公开”推断所有模型和输出用途均无限制。

## 样板使用过的工具入口

| 工具 | 在样板中的作用 | 分发情况 |
|---|---|---|
| [Anime2Sketch](https://github.com/Mukosame/Anime2Sketch) | 从画稿得到固定线稿 | 代码、权重不包含 |
| [ToonComposer](https://github.com/TencentARC/ToonComposer) | 用关键画稿、线稿约束新增动作 | 代码、权重不包含 |
| [Wan2.1](https://github.com/Wan-Video/Wan2.1) | ToonComposer 路线相关基础模型 | 代码、权重不包含 |
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | 新增日语对白 | 代码、权重和声音参考不包含 |
| [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) | 新增画面的超分增强 | 代码、权重不包含 |
| [FFmpeg](https://ffmpeg.org/) | 编解码、分轨混音、字幕与成片组织 | 可执行文件不包含；具体构建许可另查 |

关键画稿还使用过宿主提供的图像生成能力。该服务不随 Skill 分发，不是本项目开源代码的一部分。工具名称是历史样板记录，不代表当前所有版本都可互换，也不是最低依赖清单。

Resolve、AE、Blender 等是部分路线的可选工具，教程链接不等于该软件已纳入最终成片生产。公开研究来源集中在 [evidence.md](references/evidence.md) 和 [crossover-compositing.md](references/crossover-compositing.md)，保留方法摘要和链接，不转载完整教程。

## 案例边界

文档提到的番剧与角色用于说明已有样板的技术取舍，不表示与原作权利人或上述工具作者有合作、授权或背书。私有原片、台词合成参考、云账户信息、账单、完整提示与制作工程未进入公开包。使用者应准备自己可使用的素材，并按实际发布用途处理相应授权。
