# WowClip Agent Skill

WowClip 是一个完全免费、本地优先的视频切片 **Agent Skill**，用于把长视频整理成适合短视频平台的竖屏片段。

它应该安装到 Codex、OpenClaw、Claude Code，或其他兼容 `SKILL.md` 的编程 Agent 中使用。WowClip 不是一个独立桌面软件，也不是面向普通用户的一键式视频编辑器。这个 skill 的作用是给 Agent 一套可重复执行的本地工作流：分析媒体、生成字幕、选择高光片段、规划竖屏裁剪、构建可编辑的 `edl.json`，并用本地工具导出 MP4。

[English README](README.md)

## 这是什么

- 一个以 `SKILL.md` 为入口的可复用 Agent Skill。
- 一套由编程 Agent 执行的本地视频切片工作流。
- 一组可在本机运行的 Python 和 Node.js 辅助脚本。
- 一个本地完成字幕、高光选择、人脸竖屏裁剪、EDL 构建、预览和 FFmpeg 导出的流程。

## 这不是什么

- 不是 SaaS 产品。
- 不是云端剪辑 API。
- 不是一键安装的桌面视频编辑器。
- 不是 GUI 时间线编辑器。
- 不包含模型权重包。

## 作为 Skill 安装

把这个仓库 clone 到你的 Agent skills 目录。

Codex 示例：

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/partyfly/wowclip.git ~/.codex/skills/wowclip
```

OpenClaw 或 Claude Code 请把本仓库安装到对应 Agent 会扫描 `SKILL.md` 的 skills/plugins 目录中。

然后开启新的 Agent 会话，明确要求使用 WowClip：

```text
Use the wowclip skill to analyze this local video and create 3 vertical short clips with burned subtitles.
```

或者：

```text
Use the wowclip skill on this YouTube URL. Keep everything local after download, generate subtitles, build edl.json, preview frames, and export MP4.
```

## Agent 工作流

启用 skill 后，Agent 应该按下面的流程工作：

1. 检查源媒体。
2. 在选片之前，为整段素材生成本地字幕。
3. 基于字幕文本和时间戳选择候选高光片段。
4. 抽取代表帧并检测镜头边界。
5. 使用本地 OpenCV 模型做人脸检测和同人跟踪。
6. 生成确定性的 9:16 人脸居中竖屏裁剪计划。
7. 把视频、音频、字幕和裁剪位置编译成 `edl.json`。
8. 校验时间线和竖屏裁剪计划。
9. 生成预览帧或蒙太奇预览图。
10. 使用 FFmpeg 在本地导出 MP4。

可编辑的事实来源是 `edl.json`，不是一次性的 FFmpeg 命令。

## 目录结构

```text
.
├── SKILL.md                         # Agent 工作流契约
├── agents/openai.yaml               # 可选 Agent 元信息
├── assets/editor/EDITOR_CONTRACT.md # 可选编辑器集成契约
├── references/                      # 流水线设计说明
├── schemas/                         # 时间线、高光计划、竖屏计划 JSON Schema
├── scripts/                         # skill 使用的本地辅助脚本
└── tests/                           # 裁剪规划和去遮罩工具测试
```

## 本地运行环境

安装系统工具：

- Python 3.10+
- Node.js 18+
- FFmpeg 和 FFprobe
- `yt-dlp`，用于 YouTube 下载

安装本地辅助脚本所需的 Python 依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

默认 Python 依赖包括 `faster-whisper`、OpenCV、NumPy、Pillow 和 yt-dlp。部分能力是可选的：

- 如果不手动提供转写片段，本地 ASR 需要 `faster-whisper`。
- 人脸检测需要 OpenCV YuNet 模型。
- 同人跟踪推荐使用 OpenCV SFace 模型。
- 硬字幕或水印移除可选接入 ProPainter。

## 模型准备

先创建预期的本地模型目录结构：

```bash
python3 scripts/wowclip-bootstrap-models.py '{"modelsDir":"./assets/models"}'
```

这个命令只创建目录并报告缺失文件，不会自动下载模型。

建议的本地模型路径：

```text
assets/models/
├── opencv/
│   ├── face_detection_yunet.onnx
│   └── face_recognition_sface.onnx
├── silero/
│   └── silero_vad.onnx
├── whisper/
└── propainter/
```

更多说明见 `references/local-models.md`。

## 直接运行脚本

推荐入口是让 Agent 读取并执行 `SKILL.md`。高级用户也可以直接运行底层辅助脚本。

检查源视频：

```bash
node scripts/wowclip-probe.mjs '{"path":"/abs/source.mp4"}'
```

生成本地字幕：

```bash
python3 scripts/wowclip-transcribe-local.py '{"sourcePath":"/abs/source.mp4","projectRootDir":"/abs/wowclip-project","language":"zh"}'
```

执行 YouTube 到竖屏 MP4 的流程：

```bash
python3 scripts/wowclip-auto-youtube.py '{"url":"https://www.youtube.com/watch?v=...","projectRootDir":"/abs/wowclip-project","language":"zh","maxClips":3,"portraitMode":"auto","export":true}'
```

命令会把转写、工程化字幕、高光计划、竖屏裁剪计划、预览缓存、`edl.json` 和导出 MP4 写入 `projectRootDir`。

## 测试

运行当前 WowClip 测试：

```bash
python3 -m unittest discover -s tests
```

## 隐私说明

WowClip 的设计目标是让运行时媒体处理全部在本地完成。项目脚本不应上传源视频、音频、转写文本、人脸检测结果或时间线。你仍需自行检查额外安装的第三方工具和模型的行为与许可证。

## 第三方工具与模型

本仓库中的 WowClip 项目代码使用 MIT License。第三方工具、模型和数据集仍遵循它们自己的许可证和使用条款，包括 FFmpeg、yt-dlp、faster-whisper、Whisper 模型权重、OpenCV 模型、Silero VAD 和 ProPainter。

除非第三方许可证允许，请不要重新分发模型权重或第三方二进制文件。

## License

MIT。详见 [LICENSE](LICENSE)。
