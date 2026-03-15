<div align="center">

# 🎬 Douyin Downloader

**Download and transcribe Douyin (抖音) videos to text — one command, one file per video.**

Paste a video link or a creator's profile. Get clean markdown transcripts.

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## What It Does

| Input | Output |
|-------|--------|
| Single video link | One `.md` transcript file |
| Creator profile link | One `.md` file **per video** (with confirmation prompt) |

**Auto-detects** whether you gave it a video or a profile. No flags needed.

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/zinan92/douyin-downloader.git
cd douyin-downloader

pip install playwright aiohttp mlx-whisper
playwright install chromium
brew install ffmpeg  # macOS
```

### 2. Run

**Single video:**
```bash
python scripts/pipeline.py "https://www.douyin.com/video/7601234567890" \
  --output-dir ~/transcripts/
```

**All videos from a creator:**
```bash
python scripts/pipeline.py "https://www.douyin.com/user/MS4wLjABAAAA..." \
  --output-dir ~/transcripts/creator-name/
```

The script will show you how many videos it found and ask for confirmation:

```
============================================================
找到 86 个视频，确定要全部下载并转录吗？
预计耗时：64 - 107 分钟
输入 y 继续，n 取消，或输入数字限制下载数量：
============================================================
>
```

---

## Output Format

Each video becomes its own file: `01-视频标题.md`, `02-视频标题.md`, ...

```markdown
# 视频标题

> 日期: 2026-03-10 | 来源: https://www.douyin.com/video/123456

转录的文字内容在这里...
```

---

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--output-dir` | `./transcripts` | Output directory (one `.md` per video) |
| `--whisper-model` | `small` | Whisper model size: `tiny` / `base` / `small` / `medium` / `large` |
| `--language` | `zh` | Language hint for transcription |
| `--max-videos` | `0` (all) | Limit number of videos to download |
| `--skip` | `0` | Skip first N videos (useful for resuming) |
| `--concurrency` | `2` | Number of parallel downloads |
| `--keep-audio` | `false` | Keep audio files after transcription |
| `-y` / `--yes` | `false` | Skip confirmation prompt |
| `--work-dir` | `/tmp/douyin-transcriber` | Temp directory for intermediate files |

---

## Built-in Rate Limiting

No need to worry about hammering the server:

- **Max 2 concurrent** downloads
- **8–18s random delay** between individual downloads
- **30–60s pause** between batches of 5
- Automatic retry-friendly (use `--skip` to resume)

---

## Important Notes

### Login Required for Profiles

Douyin only returns ~18 videos without login. For full profile scraping (all videos), you need an authenticated browser session. The script handles the first page automatically, but pagination requires login cookies.

### Whisper Model Selection

| Model | Speed | Quality | VRAM |
|-------|-------|---------|------|
| `tiny` | Fastest | Basic | ~1 GB |
| `base` | Fast | Good | ~1 GB |
| `small` | Medium | Great | ~2 GB |
| `medium` | Slow | Excellent | ~5 GB |
| `large` | Slowest | Best | ~10 GB |

On Apple Silicon, the script automatically uses `mlx-whisper` (5–10x faster). Falls back to `openai-whisper` on other hardware.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Only 18 videos found | Login required — use an authenticated browser session |
| WAF/Cloudflare challenge | Script auto-waits 45s; retry later if persistent |
| Whisper out of memory | Use `--whisper-model small` or `tiny` |
| Audio extraction fails | Make sure ffmpeg is installed: `brew install ffmpeg` |
| Download fails for some videos | Use `--skip N` to resume from where you left off |

---

## How It Works

```
URL ──→ Detect Type ──→ Single Video? ──→ Download ──→ Transcribe ──→ Save .md
                    └──→ User Profile? ──→ Scrape All ──→ Confirm ──→ Batch Process
                                                                        ├── Download (2 parallel)
                                                                        ├── Extract audio (ffmpeg)
                                                                        ├── Transcribe (Whisper)
                                                                        └── Save individual .md files
```

---

## Use as a Claude Code Skill

This repo can be installed as a [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill:

```bash
# Clone into your skills directory
git clone https://github.com/zinan92/douyin-downloader.git \
  ~/.claude/skills/douyin-downloader
```

Claude will auto-detect Douyin URLs and offer to transcribe them. For user profiles, it will ask for confirmation before batch downloading.

### Agent Integration Notes

- **URL detection**: `detect_url_type(url)` returns `"video"`, `"user"`, or `"unknown"`
- **Single video**: No confirmation needed, run directly
- **User profile**: Always surface the video count and ask before proceeding
- **Suggested prompt to user**: `"这个用户共有 N 个视频，确定要全部下载并转录吗？"`
- **Output**: Each video → separate `.md` file in `--output-dir`
- **Resumable**: If interrupted, use `--skip N` to continue from where you left off

---

## License

MIT
