---
name: douyin-downloader
description: Use when needing to download and transcribe Douyin/抖音 videos to text. Supports single video URLs (/video/xxx) and user profile URLs (/user/xxx) with auto-detection. Triggers on Douyin links, 抖音 transcription requests, Chinese short video audio extraction, or batch video downloading.
---

# Douyin Downloader

Download and transcribe Douyin videos to text. Auto-detects single video vs user profile.

## When to Use

- User shares a `douyin.com/video/xxx` link → download + transcribe one video
- User shares a `douyin.com/user/xxx` link → scrape all videos, **ask for confirmation**, then batch process
- User asks to transcribe 抖音 content

## Quick Reference

```bash
# Single video
python scripts/pipeline.py "https://www.douyin.com/video/123" --output-dir ./out/

# User profile (will prompt for confirmation)
python scripts/pipeline.py "https://www.douyin.com/user/MS4wLj..." --output-dir ./out/

# Skip confirmation
python scripts/pipeline.py "https://www.douyin.com/user/MS4wLj..." --output-dir ./out/ -y
```

## Output

One markdown file per video: `01-标题.md`, `02-标题.md`, etc.

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--output-dir` | `./transcripts` | One .md per video |
| `--whisper-model` | `small` | tiny/base/small/medium/large |
| `--language` | `zh` | Audio language hint |
| `--max-videos` | `0` (all) | Limit count (profile only) |
| `--skip` | `0` | Skip first N (for resuming) |
| `--concurrency` | `2` | Parallel downloads |
| `-y` | false | Skip confirmation |

## Prerequisites

```bash
pip install playwright aiohttp mlx-whisper
playwright install chromium
brew install ffmpeg
```

## Important

- Login required for user profiles with 18+ videos
- Built-in rate limiting: 2 concurrent, random delays, batch pauses
- For profiles, always confirm with user before batch downloading
