# 安装与环境检查

## 安装到 Codex

使用内置 skill-installer，把仓库根目录安装为 `cartoon-motion-video-production`。仓库地址：https://github.com/zhangyuanqi0805/cartoon-motion-video-production 。首次安装可使用安装器的 `--repo zhangyuanqi0805/cartoon-motion-video-production --path . --name cartoon-motion-video-production`；遇到下载故障可使用其 `--method git`。

若仓库为私有，安装者必须先用有访问权限的 GitHub 账号登录；无权限就报告缺口，不尝试绕过。

已有旧版时先另存完整备份，再安装更新；个人 `*.local.json`、素材缓存和成品保持在私有工作目录，不从公共仓库覆盖。此次更新不需要修改系统代理或网络配置。安装结果在 Codex 下一轮对话可用。

## 运行环境

当前固定样式的稳定环境为 macOS。需要 Python 3.10+、Node/npx、FFmpeg/ffprobe、ImageMagick 的 magick 命令、HyperFrames 0.8.35。Agent 使用当前机器的真实安装路径设置 `cartoon_skill`；下面使用默认安装位置举例。

```bash
cartoon_skill="$HOME/.codex/skills/cartoon-motion-video-production"
python3 -m venv "$cartoon_skill/.venv"
"$cartoon_skill/.venv/bin/python" -m pip install -r "$cartoon_skill/requirements-setup.txt"
npx --yes hyperframes@0.8.35 --version
"$cartoon_skill/.venv/bin/python" "$cartoon_skill/scripts/install_check.py" --restore-fonts
```

字体恢复只读取本机系统/用户字体目录，写入本 Skill 的三个缺失字体文件，不修改系统字体。提取 Yuanti SC Regular、Lantinghei SC Heavy、Hannotate SC Regular，并恢复封装时的文件时间字段；只有完整 SHA256 与 V55 锁相同才写入。若系统尚未安装这些字体，在 macOS 字体册获取相应字体后重试。版本不同无法匹配时保留缺口，不替换字体、不改锁文件、不缩放文字。`fonttools==4.59.1` 是安装时依赖。

## 兼容输入与配音

本包自带 `vendor/paper-input`，默认使用它，避免误接接口不同的公开纸纹 Skill。熟悉内部接口且确有需要时，才通过 `CARTOON_PAPER_SKILL` 指向另一份已验证兼容模块。

新稿配音需要以下个人环境：

- 本机剪映和已验证的“真人播客女”配音适配器；适配器及剪映动态库 SHA 必须与该用户自己的已验证配置相符。
- `whisper-cli` 和可用模型文件。
- 个人 `auto-config.local.json`；它不随仓库分发，也不要把原作者的配置或登录信息复制到同事机器。
- Agent 可调用的生图工具。没有生图权限时保留缺口，不能切固定模式伪装素材有变化。

已有兼容的本地输入配置时，显式检查：

```bash
"$cartoon_skill/.venv/bin/python" "$cartoon_skill/scripts/install_check.py" --config /abs/path/auto-config.local.json
```

`renderer_ready` 只说明模板、字体、依赖和输入模块可用于构建；`new_manuscript_dependencies_ready` 另要求已验证的配音适配器和 Whisper。任一缺项退出 2 并列出缺项。即使依赖齐全，也仍须实际制作并观看样片，不能据此声称新机器已经全流程通过。

没有配音适配器/配置时，报告“Skill 已安装，首次配音配置待完成”。当前仓库不会自动安装专有配音二进制；不要假装已配置，也不要擅自改用系统音色。可以先导入同事合法持有的兼容配音生产包，验证渲染部分。

## 回归与回退

```bash
python3 "$cartoon_skill/scripts/make_video.py" doctor
python3 -m unittest discover -s "$cartoon_skill/scripts/tests" -v
```

构建和渲染严格按 production-contract.md。若更新失败，保留失败目录与日志，从更新前备份恢复旧 Skill；不删除素材和成品。
