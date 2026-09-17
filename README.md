# 卡通动效视频生产

把定稿制作成 V55 样式的卡通动效视频：**只换元素，不换版面。** 新稿默认按需选择或生成正文插画；开场构图、绿色纸纹、标题、字幕位置与字体、连续动效保持固定。每版交付视频和对比分析。

版本：`2026.09.17`。本次将新稿默认配音调为1.10倍原速，保持音高，并按实际母带更新字幕对齐；开场字幕、版式与动效不变。本仓库是卡通动效安装入口，与纸纹视频是两个产品。

## 给同事的安装提示词

**这是公开仓库。同事无需 GitHub 账号、登录或访问申请。** 把下面的提示词交给 Codex，它会完成安装并引导一次性设置。

[下载完整安装提示词](https://raw.githubusercontent.com/zhangyuanqi0805/cartoon-motion-video-production/main/INSTALL_PROMPT.txt) · [查看提示词文件](INSTALL_PROMPT.txt) · [下载完整 Skill ZIP](https://github.com/zhangyuanqi0805/cartoon-motion-video-production/archive/refs/heads/main.zip)

```text
请从 GitHub 安装或更新这个 Codex Skill（2026.09.17 语速校准版或更新版本）：
公开仓库：https://github.com/zhangyuanqi0805/cartoon-motion-video-production
中文名：卡通动效视频生产
英文名：cartoon-motion-video-production

这是公开仓库，下载和安装不需要 GitHub 账号、登录、访问申请或协作者权限。

请优先调用系统内置的 $skill-installer，用 repo `zhangyuanqi0805/cartoon-motion-video-production`、path `.`、name `cartoon-motion-video-production` 安装仓库根目录的最新版。安装器不可用时，按仓库 references/installation.md 的公开下载或 git clone 方法安装。已有旧版先备份，保留个人配置、素材缓存和成品。

安装后按照 references/installation.md 引导我完成一次性设置：自动检查并配置能自动处理的本地依赖、V55 字体、渲染环境、配音和生图能力；只有确实需要我登录剪映、授予系统权限或处理无法自动完成的缺项时，再清楚告诉我该做什么。缺少配音配置时如实说明，不能把 Skill 安装成功说成完整出片环境已就绪。

制作规则：只换元素，不换 V55 版面。新稿默认按需选择或生成新的正文插画，保持开场布局、标题、字幕和连续动效，开场字幕保留在原位置；新稿默认配音1.10倍原速并保持音高，按新母带重建字幕对齐，旧配音包先检查tempo_ratio，不能重复加速；每版交 MP4 和与 V55、上一版的对比分析。不要让我逐条填写 JSON、分镜、英文或样式参数。

完成后用中文告诉我如何调用。下一轮 Codex 对话开始使用，等待我提供定稿，不要自行生成视频。
```

## 安装范围

当前稳定环境是 macOS。仓库包含 V55 渲染模板、插画、兼容的原稿/音频/时间轴处理模块、素材生成与验收脚本；无需安装 GitHub 上另一份纸纹视频 Skill。Windows 完整生产未验证。

Mac 自带中文字体在安装者本机提取，校验通过才使用；仓库不分发它们。配音需要个人的已验证剪映适配器、剪映安装和 Whisper 模型，这些不在仓库内。仅安装 Skill 不会自动获得配音或生图服务，也不代表已经完成新电脑的全流程验收。已有兼容配音包可直接导入。

详见 [安装与环境检查](references/installation.md)、[生产合同](references/production-contract.md)、[素材生成规范](references/on-demand-assets.md) 和 [第三方说明](THIRD_PARTY_NOTICES.md)。

## 日常调用

```text
用“卡通动效视频生产”Skill，按下面这份定稿做一个30秒样片。只换元素，不换版面；新稿按需选择或生成新插画。交付 MP4，并提供与 V55、上一版的对比分析，说明变化和未解决的问题。
【粘贴定稿】
```

首次安装后，在 Codex 下一轮对话中使用。长视频先按实际请求做样片或完整片；30秒样片不能标成全文成品。技术通过不等于视觉验收或发布授权。
