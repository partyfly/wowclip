# WowClip

WowClip 是一个完全免费、本地优先的视频切片工具，目标是把长视频自动整理成适合短视频平台的竖屏片段。

它的核心不是云端服务，而是一套可审计的本地流水线：本地分析视频和音频，生成词级字幕，选择候选高光片段，检测镜头和人脸，生成 9:16 竖屏裁剪方案，编译标准 `edl.json` 时间线，并用 FFmpeg 在本地导出 MP4。

[English README](README.md)

## 当前状态

WowClip 目前是偏开发者和自动化集成的本地流水线。核心代码位于当前仓库，包括 Python/Node.js 脚本、JSON Schema、参考文档和测试。它已经可以作为本地实验、自动化切片和编辑器集成的基础，但还不是一个一键安装的桌面应用。

## 能做什么

- 使用 `yt-dlp` 下载 YouTube 视频，或直接处理本地视频文件。
- 使用本地 `faster-whisper` 模型生成语音转写。
- 在选片之前，为整段素材生成工程化字幕资产。
- 基于字幕文本和时间戳选择候选高光片段。
- 抽取代表帧并检测镜头边界。
- 使用本地 OpenCV 模型做人脸检测和同人跟踪。
- 生成确定性的、以人脸为中心的 9:16 竖屏裁剪方案。
- 把视频、音频、字幕、裁剪位置编译成标准 `edl.json`。
- 使用 FFmpeg 在本地导出 MP4。

## 设计原则

- **本地优先：** 视频、音频、转写、时间线和人脸检测结果都保留在本机。
- **免费技术栈：** 优先使用开源工具和本地模型。
- **非破坏式编辑：** 不覆盖源视频，所有生成文件都写入项目目录。
- **EDL 是事实来源：** `edl.json` 是可编辑时间线，不把一次性的 FFmpeg 命令当成项目状态。
- **先字幕，后选片：** 所有语音片段都应能追溯到源字幕、源词或源语音段。
- **不静默下载：** 脚本可以准备模型目录，但不会在运行时偷偷下载模型。

## 目录结构

```text
.
├── SKILL.md                         # 本地 Agent 使用的工作流契约
├── assets/editor/EDITOR_CONTRACT.md # 可选编辑器集成契约
├── references/                      # 流水线设计说明
├── schemas/                         # 时间线、高光计划、竖屏计划 JSON Schema
├── scripts/                         # 本地流水线脚本
└── tests/                           # 裁剪规划和去遮罩工具测试
```

## 环境要求

安装系统工具：

- Python 3.10+
- Node.js 18+
- FFmpeg 和 FFprobe
- `yt-dlp`，用于 YouTube 下载

安装 Python 依赖：

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

先创建预期的模型目录结构：

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

## 快速开始：本地视频

检查源视频：

```bash
node scripts/wowclip-probe.mjs '{"path":"/abs/source.mp4"}'
```

生成本地字幕：

```bash
python3 scripts/wowclip-transcribe-local.py '{"sourcePath":"/abs/source.mp4","projectRootDir":"/abs/wowclip-project","language":"zh"}'
```

选择候选片段：

```bash
python3 scripts/wowclip-select-clips.py '{"transcriptPath":"/abs/wowclip-project/transcripts/source.json","projectRootDir":"/abs/wowclip-project","maxClips":5}'
```

之后继续执行抽帧、镜头检测、人脸检测、同人跟踪、竖屏裁剪规划、时间线构建、校验、预览和导出。完整命令列表见 `SKILL.md`。

## 快速开始：YouTube 到竖屏 MP4

在 FFmpeg、yt-dlp、Python 依赖和本地模型都准备好之后：

```bash
python3 scripts/wowclip-auto-youtube.py '{"url":"https://www.youtube.com/watch?v=...","projectRootDir":"/abs/wowclip-project","language":"zh","maxClips":3,"portraitMode":"auto","export":true}'
```

命令会把所有中间产物写入 `projectRootDir`，包括：

- `transcripts/`
- `LiveClipper/subtitles/`
- `plans/clips/highlight-plan.json`
- `plans/portrait/plan.json`
- `cache/previews/`
- `edl.json`
- `exports/youtube_portrait.mp4`
- `wowclip-auto-result.json`

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
