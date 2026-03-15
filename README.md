<div align="center">

# Douyin Downloader

**一条命令，把抖音视频变成文字稿**

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## 痛点

- 抖音没有导出文字稿的功能，想回顾视频内容只能重新看一遍
- 批量下载工具多，但下载完还得手动转录，流程断裂
- 博主几十上百个视频，一个个处理太慢，中途失败还得从头来

## 解决方案

粘贴一个链接，自动完成 **下载 + 转录 + 保存**，每个视频生成一个干净的 Markdown 文件。

- **单个视频**：粘贴视频链接，直接出文字稿
- **整个博主**：粘贴主页链接，自动翻页抓取全部视频，确认后批量处理
- **断点续传**：通过 `state.json` 自动跳过已完成的视频，中断后重跑即可
- **失败重试**：下载失败自动重试 2 次，无需人工干预
- **Cookie 持久化**：登录一次，后续自动复用 session

## 架构

```
URL ──> 类型检测 ──> 单个视频? ──> 下载 ──> 转录 ──> 保存 .md
                 └──> 用户主页? ──> 翻页抓取全部 ──> 确认数量
                                                      |
                                              批量处理（并发下载）
                                              ├── 下载视频 (Playwright + aiohttp)
                                              ├── 提取音频 (ffmpeg)
                                              ├── 语音转文字 (Whisper)
                                              └── 保存为独立 .md 文件
```

## 快速开始

### 1. 安装依赖

```bash
git clone https://github.com/zinan92/douyin-downloader.git
cd douyin-downloader

pip install playwright aiohttp mlx-whisper
playwright install chromium
brew install ffmpeg  # macOS
```

### 2. 转录单个视频

```bash
python scripts/pipeline.py "https://www.douyin.com/video/7601234567890" \
  --output-dir ~/transcripts/
```

### 3. 批量转录某个博主的全部视频

```bash
python scripts/pipeline.py "https://www.douyin.com/user/MS4wLjABAAAA..." \
  --output-dir ~/transcripts/blogger-name/
```

脚本会显示视频总数并等待确认：

```
============================================================
找到 86 个视频，确定要全部下载并转录吗？
预计耗时：64 - 107 分钟
输入 y 继续，n 取消，或输入数字限制下载数量：
============================================================
>
```

### 4. 输出格式

每个视频生成一个独立文件：`01-视频标题.md`、`02-视频标题.md`...

```markdown
# 视频标题

> 日期: 2026-03-10 | 来源: https://www.douyin.com/video/123456

转录的文字内容在这里...
```

## 功能一览

| 功能 | 说明 |
|------|------|
| 自动类型检测 | 粘贴链接自动识别是单个视频还是用户主页 |
| 批量翻页抓取 | 自动滚动翻页，获取用户全部视频列表 |
| 并发下载 | 默认 2 路并发，内置随机延迟和批次暂停 |
| Whisper 转录 | Apple Silicon 自动使用 mlx-whisper（5-10x 加速） |
| Cookie 持久化 | 登录状态保存到 `~/.douyin-cookies.json`，后续自动复用 |
| 断点续传 | `state.json` 记录进度，中断后重跑自动跳过已完成视频 |
| 自动重试 | 下载失败自动重试最多 2 次 |
| 反爬内置 | 随机延迟 8-18s、批次暂停 30-60s、WAF 自动等待 |

## 技术栈

| 组件 | 技术 |
|------|------|
| 网页抓取 | Playwright (Chromium headless) |
| 视频下载 | aiohttp (异步 HTTP) |
| 音频提取 | ffmpeg |
| 语音转文字 | mlx-whisper (Apple Silicon) / openai-whisper (fallback) |
| 并发控制 | asyncio + Semaphore |
| 语言 | Python 3.9+ |

## 项目结构

```
douyin-downloader/
├── scripts/
│   └── pipeline.py      # 主程序：下载 + 转录 pipeline
├── SKILL.md             # Claude Code skill 描述文件
├── LICENSE              # MIT
└── README.md
```

## 配置

### 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `url` | (必填) | 抖音视频或用户主页链接 |
| `--output-dir` | `./transcripts` | 输出目录，每个视频一个 .md 文件 |
| `--whisper-model` | `small` | Whisper 模型：`tiny` / `base` / `small` / `medium` / `large` |
| `--language` | `zh` | 转录语言 |
| `--max-videos` | `0`（全部） | 限制下载视频数量 |
| `--skip` | `0` | 跳过前 N 个视频 |
| `--concurrency` | `2` | 并发下载数 |
| `--keep-audio` | `false` | 转录后保留音频文件 |
| `-y` / `--yes` | `false` | 跳过确认提示（用于自动化） |
| `--work-dir` | `/tmp/douyin-transcriber` | 中间文件临时目录 |
| `--cookies-file` | `~/.douyin-cookies.json` | Cookie 持久化文件路径 |

### Whisper 模型选择

| 模型 | 速度 | 质量 | 显存 |
|------|------|------|------|
| `tiny` | 最快 | 基础 | ~1 GB |
| `base` | 快 | 较好 | ~1 GB |
| `small` | 中等 | 很好 | ~2 GB |
| `medium` | 慢 | 优秀 | ~5 GB |
| `large` | 最慢 | 最佳 | ~10 GB |

### 常见问题

| 问题 | 解决方案 |
|------|----------|
| 只抓到 18 个视频 | 需要登录 — 先在浏览器登录抖音 |
| WAF/Cloudflare 拦截 | 脚本会自动等待 45s，持续失败请稍后重试 |
| Whisper 内存不足 | 换用更小的模型：`--whisper-model tiny` |
| 音频提取失败 | 确认已安装 ffmpeg：`brew install ffmpeg` |
| 部分视频下载失败 | 脚本会自动重试，也可重跑自动跳过已完成的 |

## For AI Agents

### Metadata

```yaml
tool_name: douyin-downloader
tool_type: cli
description: 下载抖音视频并转录为文字，支持单视频和用户主页批量处理
cli_command: python scripts/pipeline.py
input_format: Douyin URL (video or user profile)
output_format: Markdown files (one per video)
prerequisites:
  - playwright (pip install playwright && playwright install chromium)
  - aiohttp (pip install aiohttp)
  - mlx-whisper (pip install mlx-whisper)
  - ffmpeg (brew install ffmpeg)
```

### Agent Workflow

```yaml
steps:
  - name: detect_url_type
    description: 判断输入是单个视频还是用户主页
    logic: |
      /video/\d+ → "video" (直接处理，无需确认)
      /user/    → "user"  (需要确认后批量处理)

  - name: run_single_video
    condition: url_type == "video"
    command: python scripts/pipeline.py "{url}" --output-dir {output_dir} -y

  - name: run_user_profile
    condition: url_type == "user"
    command: python scripts/pipeline.py "{url}" --output-dir {output_dir} -y --max-videos {limit}
    note: 务必先告知用户视频总数，获得确认后再执行

  - name: resume_after_interrupt
    description: 中断后重跑，自动跳过已完成视频
    command: python scripts/pipeline.py "{url}" --output-dir {output_dir} -y
    note: state.json 会自动跟踪进度，无需手动 --skip
```

### Claude Code Skill 安装

```bash
git clone https://github.com/zinan92/douyin-downloader.git \
  ~/.claude/skills/douyin-downloader
```

安装后 Claude 会自动识别抖音链接并提供转录服务。

## License

MIT
