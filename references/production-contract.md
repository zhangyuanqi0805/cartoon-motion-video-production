# 生产合同与命令

## 输入与依赖

视觉正本在 `assets/v55/`；固定1280×720、30fps、HyperFrames 0.8.35。保持已测运行版本；升级属于模板维护，须另建回归版本。运行依赖为 Python 3、Node/npx、FFmpeg/ffprobe；兼容输入模块随包放在 `vendor/paper-input`；可通过 CARTOON_PAPER_SKILL 显式指定已验证的兼容模块。不能将 GitHub 的 paper-card-video-skill-auto 公共版直接当作此接口。doctor 回报实际依赖路径。素材检查另需 ImageMagick（magick）。Mac 字体不在仓库分发，安装时从使用者自己的 Mac 读取并按 V55 哈希验证；其余第三方组件见 THIRD_PARTY_NOTICES.md。

`doctor` 验证所有包内文件 SHA，同时检查 Node/npx、FFmpeg/ffprobe、ImageMagick、纸纹输入脚本目录和已缓存的 HyperFrames 0.8.35 能否启动。只有 dependencies_ready=true 才表示这些本机依赖已就绪；TEMPLATE_OK 单独只证明模板完整。缺依赖时退出非零，不自动装包或改网络；Agent 另行检查生图工具是否可用。`presets` 返回插画及原始 slot。语义：phone 手机、listen 聊天、choices 示范/选择、timer 计时、shelf 阅读、blocks 积累、angry 情绪、oneblock 一步任务、draw 绘画、together 陪伴、parentphone 家长用手机、praise 鼓励、notes 清单记录、calendar 长期安排、walk 外出。

## 素材模式

diverse-v55 是新稿默认；先按 [按需素材合同](on-demand-assets.md) 规划、生成、验收，再把稿件绑定的 asset_bundle 写入 job。缺素材包时构建返回 ASSET_GENERATION_REQUIRED，Agent 应继续执行生图链路。开场保持 V55，正文只换元素。

fixed-v55 只用于显式原样复刻或对照，不读素材缓存。旧 asset-pool/manifest.json 保留作历史资料，本入口不再从它自动挑开场或未经逐图复核的素材。

## 新稿准备

用户交定稿并要求制作后，Agent 读全文，按本包 [输入计划合同](input-plan.md)自行生成 content plan；其后续纸纹视频总控不用于卡通成品。计划含原 Markdown SHA、真实授权人/时间、三行标题、分幕 lines 和逐卡 line_english。禁止摘要或占位英文；已有同稿批准回执与配音包优先复用。

```bash
cartoon_skill="$HOME/.codex/skills/cartoon-motion-video-production"
python3 "$cartoon_skill/scripts/make_video.py" doctor
python3 "$cartoon_skill/scripts/make_video.py" prepare --manuscript /abs/path/定稿.md --content-plan /abs/path/content-plan.json --output /abs/path/input-v1
```

`prepare` 只编排原稿/确认合同 → 官方真人播客女 TTS → 无损拆卡 → 音频母带 → Whisper full JSON → token alignment。默认原速 `--tempo 1.0`，不自动继承纸纹的加速比。`--config` 指定已验证配音配置，`--whisper-model` 指定模型；默认读取兼容输入模块的 `references/auto-config.local.json`（个人配置，首次安装需单独提供；推荐通过 --config 显式指定）。不要打印或复制密钥。剪映动态库/配音器校验失败就停，不换系统音色。

成功状态 `INPUT_READY_NOT_RENDERED`；失败保留证据，修正后新建版本。

## 插画计划与导入

读 production 的 `alignment-high-fidelity-v1.json` 和 `audio-high-fidelity-v1/audio-manifest.json`，按真实句起点写 visual plan。开头约4–5秒，在一句结束处切换；正文插画覆盖一个语义段，长段可在句边界分成有目的的连续动作。

```json
{
  "render_mode": "diverse-v55",
  "opening": {"duration": 4.927, "lines": ["孩子10岁前", "三次成长机会", "从日常练起"], "tag": "每天一点进步"},
  "visuals": [
    {"preset": "choices", "asset_family": "choice", "start": 4.927, "end": 8.398, "meaning": "示范和选择说明成长方法"},
    {"preset": "notes", "asset_family": "planning", "start": 8.398, "end": 17.288, "meaning": "记录不同年龄阶段的培养重点"}
  ]
}
```

例子仅示字段，时间必须来自本稿；visuals 从开头结束连续覆盖至母带结束。meaning 写真实语义；不要把每条短字幕都当成新插画场景。固定模式必须显式写 render_mode=fixed-v55；普通新稿可省略而默认变化模式。开场不接收变体；正文实际选择来自冻结的 asset_bundle。

```bash
python3 "$cartoon_skill/scripts/make_video.py" presets
python3 "$cartoon_skill/scripts/make_video.py" import-paper --production /abs/path/input-v1 --visual-plan /abs/path/visual-plan-v1.json --output /abs/path/cartoon-job-v1.json
```

生产包需含 job.json、job-high-fidelity.json、approval.json、manuscript_approved.txt、provenance.json、官方逐幕 WAV/TTS manifest、母带/audio manifest、匹配的 token alignment。导入只核验内容输入，暂不要求已经完成生图；构建时才要求素材包。导入核验批准稿、TTS文字/WAV、母带、音色和时间轴；只取正文/英文/时长，不继承纸纹 motion、icon、canvas 或渲染工程。

## 内部 job v2

schema_version=2；顶层只允许 title、duration、manuscript、narration、alignment、captions、visuals、opening、provenance、`render_mode`、`asset_bundle`。

| 字段 | 合同 |
|---|---|
| manuscript | path/sha256；字幕拼接只忽略空白，标点仍须一致 |
| narration | path/sha256/source_sha256/provider/voice_id；原稿绑定，官方 zh_female_mizai_saturn_bigtts |
| alignment | path/sha256，format=paper-card-token-offsets；真实 Whisper token 派生 |
| captions | text/en/start/end；导入后按源生产包重算核对，不接受手填等长时间 |
| visuals | preset/start/end/meaning；可选 `asset_family`/`variant_id`；已知插画，连续覆盖正文 |
| provenance | 批准稿、批准回执、TTS、母带、源 job 的路径与 SHA，原 Markdown SHA |
| render_mode | `fixed-v55` 或 `diverse-v55`；缺省为 `diverse-v55` |
| asset_bundle | diverse-v55 的 path/sha256；绑定当前稿件的已验收素材，固定模式省略 |

直接短语 token 合同仅用于维护测试，不是普通生产路线；不要手写标成 token 的 JSON 绕过配音与对齐。

## 构建与成片

```bash
python3 "$cartoon_skill/scripts/make_video.py" build --job /abs/path/cartoon-job-v1.json --seconds 30 --output /abs/path/sample30-v1
python3 "$cartoon_skill/scripts/make_video.py" check --project /abs/path/sample30-v1 --runtime
python3 "$cartoon_skill/scripts/make_video.py" render --project /abs/path/sample30-v1 --output /abs/path/cartoon-sample30-v1.mp4
python3 "$cartoon_skill/scripts/make_video.py" verify --project /abs/path/sample30-v1 --video /abs/path/cartoon-sample30-v1.mp4 --output /abs/path/qc-sample30-v1
```

build 在固定模式复制固定素材，在多样化模式复制 asset-selection.json 选中的插画及 asset-evidence 证据；两种模式都按 preset 而不是旧 scene 编号绑定几何和加载器，保留 V55 动效。超过8秒的正文段只按段长有界放大同一条单向平移轨迹，最多1.9倍，避免慢配音拉长画面后出现视觉停顿。F48 是每张插画唯一的 shell-motion owner：首次进场后接三段连续轨迹，第一段使用 `driftJoinEase`（末速约0.6），与下一段的位移/时长比相接，再进入中段匀速和退出；不追加第二个外层 transform writer，不用循环抖动。该适配已固化在模板锁中。content-job.json、timeline.json、build-manifest.json 和多样化模式的 `asset-selection.json` 保存输入、全稿/输出时长、素材选择和构建文件 SHA。check/render 拒绝工程篡改。完整片同一个 job 省略 --seconds，改用新工程/视频/QC路径。

## 验收与报告

verify 提供规格、帧数、音轨、全解码、正文插画 ROI 冻结检测、最终 MP4 接触表、全部字幕分页 `all-caption-pages/page-*.png`、`caption-page-index.json` 和切换条带；它还保存单帧亮度突变候选与黑帧检查。asset_coverage 按本次实际输出时长列出每段 replaced / kept_v55 及数量，必须据此披露未变化的片段，不把技术通过写成所有素材已换。开头保留 V55 有意停留，正文从首个插画开始检测；结束仍处于 freeze 也不能漏报。阈值 -55dB / 0.5s 是筛查，不能证明动态舒服。技术失败退出非零，通过仅为 TECH_PASS_REVIEW_REQUIRED。

Agent 另须查看全部字幕、长场景中段和切换边界，确认由快到慢再衔接、无循环抖动/闪屏、中文与英文可读且对应。通过听音或同母带音频比对检查声音，未听过不要写听感验收通过。逐版报告绑定视频 SHA，列上版→本版、V55 对照、已解决/剩余问题、技术与视觉门、分项评分和下一步。零runtime错误、模板SHA一致与高评分不能互相替代。

日常生产不改本 Skill 源码。维护先备份，针对原失败做真实新内容样片及独立调用测试，通过后作范围明确的本地提交；外部更新按用户当次授权执行。
