# 按需素材合同

本版将“生成→检查→固定槽位预览→视觉复核→缓存→稿件绑定→成片对比”固化为可执行过程。生图由 Agent 调用工具，脚本只负责确定性处理，不假装提供不存在的生图接口。

## 哪些固定，哪些能变

| 区域 | 固定项 | 可换项 |
|---|---|---|
| 整页 | 1280×720、30fps、绿色纸纹和色调、留白、叠放关系 | 本轮不换 |
| 开场 | 原 V55 全页构图、黑板位置、字幕位置和字体 | 稿件文字；背景元素未拆开前不自动换整图 |
| 正文大字/英文 | 原字号、字体、基线位置、揭示动画 | 本稿准确中英文 |
| 正文插画 | 已校准主体区域、主体中心、宽高比保留、同一个 motion owner | 卡通人物/动作/道具/纯物件组合、适度色彩变化 |
| 时间与音轨 | 官方既定音色、真实 token 对齐 | 本稿内容、语义切点和真实时长 |

已校准替换槽位是 choices、blocks、notes、listen、shelf、draw、together；数值正本是 scripts/generated_assets.py 的 SLOTS。其余 preset 可沿用 V55，未经校准不得猜坐标。notes 使用最终约375×280区域，不再沿用旧素材清单的300×227；blocks 使用最终运行时约223×275宽高。生成后的图片坐标由可见主体的 bounds 等比例适配，素材元数据不允许改页面坐标。

## 当前稿件需要多少就生成多少

使用当前项目自己的 library 目录与 usage-history.json，不写 Skill 源码或共享正式素材清单。同一项目连续生产沿用同一个缓存与历史；换线程先找已有记录，不得每片新建空库却声称完成近期去重。候选测试使用候选目录下的 library，正式素材库不受影响。30秒阶段只规划实际会出现的片段；先做好当下几张，再按全长片需求继续。正文可使用单人、双人互动、道具/物件组合等形式，不限定每张都是同一对母子。

入口示例（cartoon_skill 指向当前已安装包的绝对路径，由 Agent 设置）：

~~~bash
python3 "$cartoon_skill/scripts/generated_assets.py" plan --job /abs/source-job.json --library /abs/library --history /abs/usage-history.json --seconds 30 --output /abs/asset-plan-v1.json
python3 "$cartoon_skill/scripts/generated_assets.py" brief --preset choices --subject '家长和孩子一起阅读黄色绘本' --background alpha --output /abs/reading-brief.json
~~~

plan 在已验收缓存里选符合 preset、未在最近五份不同稿件用过的图片；无合适素材时输出 action=generate。它是可执行的下一步清单，不是“视频已完成”。改稿后重新 plan，不把另一个稿件的 bundle 直接复用；从库取原始 entry 重新绑定即可。当前保存的 bundle 保证重复构建不会重新随机选图。

生图时读 brief 和 reference_images 的实际图。两张参考图只约束线条、色彩、卡通风格，不允许把参考视频整页画进去。主要规范：

- 长边至少900、短边至少512像素；提示词通常要求1024以上。
- 清晰黑粗线，扁平、简洁、青蓝/橙黄主色；人物和物件可辨识。
- 主体完整，外缘留约2–5%空白；不贴边裁头裁手、不把主体画成小图标。
- 形状匹配目标宽高比。可见主体在槽位两方向均达到78%以上，否则不拉伸救图。
- 无字幕/字母/水印/logo/页面/小窗/边框/纸纹/额外动画。

## 背景方案

alpha 是第一选择：检查实际 alpha 像素，不靠文件扩展名或屏幕棋盘判断。外侧确实透明、主体主要区域不透明、边缘干净才可过技术门。

white-key 是适用范围较窄的备用输入：纯白底 RGB PNG，V55 页面通过静态显示蒙版隐藏近白色，保留其它颜色；源 PNG 不变。不能把它称作透明 PNG。技术检查要求边缘接近纯白，画面实际复核要求无白框、晕边、肤色变暗或镂空。不要生成大块白色钟面、白衣、近白道具；让它们变成有色填充。保留白色是意义所必需时用真 alpha 或换图。

蒙版只属于新图片的显示适配，不写入基线模板、不拥有运动。原 V55 已有的进场、渐进缩放、平移、退出负责让它动。不要用 multiply 叠色，它在本轮实测中造成明显发暗，已淘汰。

## 技术检查与视觉复核

~~~bash
python3 "$cartoon_skill/scripts/generated_assets.py" check --source /abs/reading.png --preset choices --background white-key --output /abs/reading-check.json
~~~

检查包含真实像素格式、尺寸、背景、可见主体 bounds、安全边距、目标槽位填充率和等比例 placement。TECH_PASS_VISUAL_REVIEW_REQUIRED 不是视觉通过，TECH_FAIL 不可入库。

首次新图需要实际 V55 预览。写 preview-bindings.json（visual_index 从0开始）：

~~~json
[
  {"visual_index":0,"source":"/abs/reading.png","background_mode":"white-key"}
]
~~~

~~~bash
python3 "$cartoon_skill/scripts/preview_assets.py" --job /abs/source-job.json --bindings /abs/preview-bindings.json --seconds 30 --output /abs/unadmitted-preview-v1
~~~

预览目录没有 build-manifest，不能用生产 render/check 当成正式工程。打开自动生成的 review.html，点击“片段”、播放/暂停按钮，或拖时间滑块查看稳定帧和进出场。控件只在预览页，不修改视频版面或生产 index.html。若浏览器限制 file 地址的 iframe 访问，用 python3 -m http.server 8765 --bind 127.0.0.1 --directory /abs/unadmitted-preview-v1 临时提供本机只读服务，再打开 http://127.0.0.1:8765/review.html；用完停止该进程。不要从 CUA 的只读 evaluate 调用改变时间轴的函数。工具不可用可做其它环节，但不能捏造视觉复核。原图也必须查看。

Agent 记录 review.json，source_sha256 必须属于刚查看的图片，evidence 至少包含一张实际 V55 合成 PNG（不小于320×180），并绑定 SHA。可以再附观察报告；不要只附有外部依赖的 review.html，它复制进素材包后未必还能打开。截图可以来自实际浏览器预览或已渲染的最终 MP4；必须实际查看，不用源图冒充合成图。以下只是字段示例，观察内容要据实重写：

~~~json
{
  "source_sha256":"<actual sha256>",
  "preset":"choices",
  "background_mode":"white-key",
  "decision":"candidate_pass",
  "reviewer":"Agent本轮视觉复核",
  "checks":{
    "style_matches_v55":true,
    "anatomy_and_objects_clear":true,
    "no_text_logo_frame":true,
    "edges_clean":true,
    "background_composite_clean":true,
    "size_and_proportions_match":true,
    "meaning_reasonable":true
  },
  "observations":"写看到了什么、与V55哪里一致、剩余限制；不是自动填全通过。",
  "evidence":[{"path":"/abs/preview-frame.png","sha256":"<actual sha256>"}]
}
~~~

这些记录是可追溯证据，不是能证明审美正确的自动评分。新图只要有一项失败，就新建修订；对同一问题一次定向重试后仍失败，应推进其它图或其它流程，并保留失败记录。

## 入库、绑定、冻结

~~~bash
python3 "$cartoon_skill/scripts/generated_assets.py" admit --source /abs/reading.png --brief /abs/reading-brief.json --review /abs/reading-review.json --library /abs/library
~~~

输出不可覆盖的 entry，内含原图、提示词、技术测量、视觉观察、可离线查看的合成 PNG 和所有文件哈希。只交 HTML/文字报告的新入库会被拒绝；早期未标记 portable-v55-frame-v1 的历史 entry 保持可读，不伪称已补齐新证据。需要补证时在新库版本重新 admit，不覆盖旧 entry。再次消费会重查像素与 SHA，拒绝“换了图片但继续沿用旧通过报告”。

写 bindings.json：

~~~json
[{"visual_index":0,"entry":"/abs/library/choices-<sha16>/entry.json"}]
~~~

~~~bash
python3 "$cartoon_skill/scripts/generated_assets.py" bind --job /abs/source-job.json --bindings /abs/bindings.json --output /abs/asset-bundle-v1
~~~

把命令返回的 path/sha256 写进新 job.asset_bundle；render_mode 保持 diverse-v55。bundle 保存当前稿件 SHA；没有绑定的正文段继续用 V55，样片实际范围内至少要有一处验收过的替换，否则构建拒绝“零变化样片”。Agent 应主动覆盖本稿适合替换的多个片段，不把“一处”当目标上限。

build 会复制插画与整包证据，原布局不变。asset-selection.json 记录每个片段是否替换、用了哪张图、来源 SHA、显示模式与固定槽位。build-manifest.json 与 verify 的 asset_coverage 自动汇总本次时长内已换/保留 V55 的段数和时间段；逐版报告据此说明覆盖情况与缺口。

完成技术检查后：

~~~bash
python3 "$cartoon_skill/scripts/generated_assets.py" record --project /abs/sample30-v1 --verification /abs/qc/verification.json --history /abs/usage-history.json
~~~

记录实际生成的候选用于近期去重，不表示用户批准。更丰富素材降低肉眼重复感，但不承诺平台不会判重复。


## 旧输入迁移

旧 fixed-v55 job 可能残留曾被忽略的 cover-03 或旧 variant_id。迁移时先保留原 job，另存新 job，仅清除旧素材路由字段，保持原稿、音轨、字幕、切点和开场文案不动，并记录移除项。不要把这些旧字段再次激活；新选择来自稿件专属 bundle。

已构建工程也可生成单独的带控件页面：python3 scripts/review_page.py --project /abs/sample30 --output /abs/sample30-review.html。它不改原工程；通过两者共同父目录的本机 HTTP 服务访问。
