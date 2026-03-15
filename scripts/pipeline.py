"""
Douyin Transcriber Pipeline (v3)
================================
Download and transcribe Douyin videos to text.

Supports:
- Single video URL: download + transcribe one video
- User profile URL: scrape all videos, ask for confirmation, then batch process

Output: one markdown file per video in the output directory.

Usage:
    python pipeline.py "https://www.douyin.com/video/xxxxx" --output-dir ~/transcripts/
    python pipeline.py "https://www.douyin.com/user/xxxxx" --output-dir ~/transcripts/
"""

from __future__ import annotations

import asyncio
import argparse
import json
import logging
import os
import random
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

CHALLENGE_MAX_WAIT = 45
SCROLL_PAUSE = 3.0
SCROLL_MAX_NO_NEW = 10
DEFAULT_WORK_DIR = "/tmp/douyin-transcriber"
CONCURRENT_DOWNLOADS = 2
BATCH_SIZE = 5
BATCH_PAUSE_MIN = 30
BATCH_PAUSE_MAX = 60
DOWNLOAD_DELAY_MIN = 8
DOWNLOAD_DELAY_MAX = 18


# ---------------------------------------------------------------------------
# 0) URL type detection
# ---------------------------------------------------------------------------

def detect_url_type(url: str) -> str:
    """Detect whether the URL is a single video or a user profile.

    Returns 'video', 'user', or 'unknown'.
    """
    if re.search(r"/video/\d+", url):
        return "video"
    if re.search(r"/user/", url):
        return "user"
    return "unknown"


def extract_video_id_from_url(url: str) -> Optional[str]:
    """Extract video ID from a single video URL."""
    m = re.search(r"/video/(\d+)", url)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# 1) Scrape single video metadata
# ---------------------------------------------------------------------------

async def scrape_single_video(video_url: str) -> list:
    """Return a single-element list with {url, title, date, video_id} for one video."""
    from playwright.async_api import async_playwright

    video_id = extract_video_id_from_url(video_url)
    if not video_id:
        logger.error(f"Cannot extract video ID from: {video_url}")
        return []

    result = {
        "url": video_url,
        "title": f"video_{video_id}",
        "date": "unknown",
        "video_id": video_id,
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        page = await context.new_page()

        detail_data = None

        async def capture_detail(response):
            nonlocal detail_data
            try:
                if response.status == 200 and "/aweme/v1/web/aweme/detail/" in response.url:
                    detail_data = await response.json()
            except Exception:
                pass

        page.on("response", lambda r: asyncio.create_task(capture_detail(r)))

        try:
            await page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            logger.warning(f"Page load error: {e}")

        await page.wait_for_timeout(5000)

        # Try to get title from detail API
        if detail_data and isinstance(detail_data, dict):
            aweme = detail_data.get("aweme_detail", {})
            if isinstance(aweme, dict):
                desc = aweme.get("desc", "").strip()
                if desc:
                    result["title"] = desc
                ct = aweme.get("create_time", 0)
                if ct:
                    result["date"] = datetime.fromtimestamp(ct).strftime("%Y-%m-%d")

        # Fallback: try page title
        if result["title"].startswith("video_"):
            try:
                page_title = await page.title()
                if page_title and "抖音" not in page_title:
                    result["title"] = page_title.strip()
            except Exception:
                pass

        await browser.close()

    logger.info(f"Video: {result['title'][:60]} ({result['date']})")
    return [result]


# ---------------------------------------------------------------------------
# 2) Scrape user profile for video list
# ---------------------------------------------------------------------------

async def scrape_user_videos(user_url: str, max_videos: int = 0) -> list:
    """Return list of {url, title, date, video_id} for every video on a user's profile."""
    from playwright.async_api import async_playwright

    seen_ids = set()
    api_videos = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        async def block_assets(route):
            if route.request.resource_type in ("image", "font", "stylesheet", "media"):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", block_assets)

        first_api_url = None
        first_api_data = None
        api_capture_event = asyncio.Event()

        async def capture_post_api(response):
            nonlocal first_api_url, first_api_data
            try:
                url = response.url
                if response.status == 200 and "/aweme/v1/web/aweme/post/" in url:
                    data = await response.json()
                    if first_api_url is None:
                        first_api_url = url
                        first_api_data = data
                        api_capture_event.set()
                    for item in data.get("aweme_list", []):
                        vid = item.get("aweme_id", "")
                        if vid and vid not in seen_ids:
                            seen_ids.add(vid)
                            desc = item.get("desc", "").strip() or f"video_{vid}"
                            ct = item.get("create_time", 0)
                            date_str = (
                                datetime.fromtimestamp(ct).strftime("%Y-%m-%d")
                                if ct else "unknown"
                            )
                            api_videos.append({
                                "url": f"https://www.douyin.com/video/{vid}",
                                "title": desc,
                                "date": date_str,
                                "video_id": vid,
                            })
            except Exception:
                pass

        page.on("response", lambda r: asyncio.create_task(capture_post_api(r)))

        logger.info(f"Loading user profile: {user_url}")
        try:
            await page.goto(user_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            logger.error(f"Failed to load profile: {e}")
            await browser.close()
            return []

        # Wait for WAF
        deadline = time.monotonic() + CHALLENGE_MAX_WAIT
        while time.monotonic() < deadline:
            html = await page.content()
            if not any(m in html.lower() for m in ["please wait", "waf-jschallenge", "_wafchallengeid"]):
                break
            await page.wait_for_timeout(2000)

        await page.wait_for_timeout(3000)

        try:
            await asyncio.wait_for(api_capture_event.wait(), timeout=15)
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for first API response")

        # Scroll to trigger pagination
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(3000)

        # Paginate via scroll (requires login for pages beyond the first)
        no_new_count = 0
        prev_count = len(api_videos)
        for _ in range(100):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.evaluate("""() => {
                const c = document.querySelector('.route-scroll-container');
                if (c) c.scrollTop = c.scrollHeight;
            }""")
            await page.wait_for_timeout(int(SCROLL_PAUSE * 1000))

            current_count = len(api_videos)
            if current_count == prev_count:
                no_new_count += 1
            else:
                no_new_count = 0
            prev_count = current_count

            if no_new_count >= SCROLL_MAX_NO_NEW:
                break
            if max_videos > 0 and current_count >= max_videos:
                break

        # Fallback to DOM if API interception found nothing
        if not api_videos:
            logger.info("API interception found no videos, falling back to DOM parsing")
            links = await page.evaluate("""() => {
                const results = [];
                document.querySelectorAll('a[href*="/video/"]').forEach(a => {
                    const match = a.href.match(/\\/video\\/(\\d+)/);
                    if (match) results.push({
                        url: a.href,
                        title: a.textContent?.trim() || a.getAttribute('title') || '',
                        video_id: match[1]
                    });
                });
                return results;
            }""")
            for link in links:
                vid = link.get("video_id", "")
                if vid not in seen_ids:
                    seen_ids.add(vid)
                    api_videos.append({
                        "url": link["url"],
                        "title": link.get("title", f"video_{vid}"),
                        "date": "unknown",
                        "video_id": vid,
                    })

        await browser.close()

    if max_videos > 0:
        api_videos = api_videos[:max_videos]

    logger.info(f"Total videos found: {len(api_videos)}")
    return api_videos


# ---------------------------------------------------------------------------
# 3) Download video & extract audio
# ---------------------------------------------------------------------------

async def _get_video_src(page, video_url: str) -> Optional[str]:
    """Navigate to video page and extract the video source URL."""
    src = None
    aweme_detail = None
    media_candidates = []
    response_tasks = []

    async def handle_response(response):
        nonlocal aweme_detail
        try:
            url = response.url
            if response.status in (200, 206) and "douyinvod.com" in url and url.startswith("http"):
                media_candidates.append(url)
            if response.status == 200 and "/aweme/v1/web/aweme/detail/" in url and aweme_detail is None:
                aweme_detail = await response.json()
        except Exception:
            pass

    page.on("response", lambda r: response_tasks.append(asyncio.create_task(handle_response(r))))

    try:
        await page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        logger.warning(f"Page load error for {video_url}: {e}")
        return None

    deadline = time.monotonic() + CHALLENGE_MAX_WAIT
    while time.monotonic() < deadline:
        try:
            html = await page.content()
            if not any(m in html.lower() for m in ["please wait", "waf-jschallenge", "_wafchallengeid"]):
                break
        except Exception:
            pass
        await page.wait_for_timeout(2000)

    await page.wait_for_timeout(6000)
    if response_tasks:
        await asyncio.gather(*response_tasks, return_exceptions=True)

    if aweme_detail:
        src = _extract_src_from_detail(aweme_detail)

    if not src and media_candidates:
        src = media_candidates[0]

    if not src:
        try:
            src = await page.evaluate("""() => {
                const v = document.querySelector('video');
                if (!v) return null;
                if (v.src && v.src.startsWith('http')) return v.src;
                const sources = Array.from(v.querySelectorAll('source'));
                const mp4 = sources.find(s => s.type === 'video/mp4');
                return mp4 ? mp4.src : (sources[0] ? sources[0].src : null);
            }""")
        except Exception:
            src = None

    if src and src.startswith("http"):
        return src
    return None


async def download_single_audio(
    video_url: str, output_audio: Path, semaphore: asyncio.Semaphore, delay: float = 0,
) -> bool:
    """Download one video and extract audio. Uses semaphore to limit concurrency."""
    import aiohttp
    from playwright.async_api import async_playwright

    if delay > 0:
        await asyncio.sleep(delay)

    async with semaphore:
        video_file = output_audio.with_suffix(".mp4")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
            )
            page = await context.new_page()

            async def block_assets(route):
                if route.request.resource_type in ("image", "font", "stylesheet"):
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", block_assets)

            src = await _get_video_src(page, video_url)
            if not src:
                logger.warning(f"No video src found for {video_url}")
                await browser.close()
                return False
            logger.info("Got video src, downloading...")

            headers = {
                "User-Agent": await page.evaluate("navigator.userAgent"),
                "Referer": "https://www.douyin.com/",
            }
            await browser.close()

        async with aiohttp.ClientSession() as session:
            async with session.get(src, headers=headers, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                if resp.status not in (200, 206):
                    logger.warning(f"Download failed: status {resp.status}")
                    return False
                with open(video_file, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1024 * 1024):
                        f.write(chunk)

        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_file), "-vn", "-acodec", "copy",
             str(output_audio.with_suffix(".aac"))],
            capture_output=True, text=True,
        )

        if result.returncode != 0:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(video_file), "-vn", "-acodec", "libmp3lame",
                 "-q:a", "4", str(output_audio)],
                capture_output=True, text=True,
            )
        else:
            aac_file = output_audio.with_suffix(".aac")
            if aac_file.exists():
                aac_file.rename(output_audio)

        if video_file.exists():
            video_file.unlink()

        if result.returncode != 0 and not output_audio.exists():
            logger.warning(f"ffmpeg failed: {result.stderr[:200]}")
            return False

        return output_audio.exists()


def _extract_src_from_detail(detail_payload: dict) -> Optional[str]:
    if not isinstance(detail_payload, dict):
        return None
    aweme = detail_payload.get("aweme_detail")
    if not isinstance(aweme, dict):
        return None
    video = aweme.get("video")
    if not isinstance(video, dict):
        return None

    bit_rates = video.get("bit_rate")
    if isinstance(bit_rates, list):
        sortable = []
        for item in bit_rates:
            if not isinstance(item, dict):
                continue
            score = item.get("bit_rate", 0)
            play_addr = item.get("play_addr")
            urls = play_addr.get("url_list") if isinstance(play_addr, dict) else []
            src = _first_http(urls)
            if src:
                sortable.append((score, src))
        if sortable:
            sortable.sort(key=lambda x: x[0], reverse=True)
            return sortable[0][1]

    for key in ("play_addr_h264", "play_addr", "download_addr", "play_addr_265"):
        addr = video.get(key)
        if isinstance(addr, dict):
            src = _first_http(addr.get("url_list"))
            if src:
                return src
    return None


def _first_http(urls) -> Optional[str]:
    if not isinstance(urls, list):
        return None
    for url in urls:
        if isinstance(url, str) and url.startswith("http"):
            return url
    return None


# ---------------------------------------------------------------------------
# 4) Transcribe with mlx-whisper or fallback to openai-whisper
# ---------------------------------------------------------------------------

def transcribe_audio_mlx(audio_path: Path, model: str = "small", language: str = "zh") -> str:
    """Transcribe using mlx-whisper (5-10x faster on Apple Silicon)."""
    try:
        import mlx_whisper
        model_map = {
            "tiny": "mlx-community/whisper-tiny-mlx",
            "base": "mlx-community/whisper-base-mlx-q4",
            "small": "mlx-community/whisper-small-mlx",
            "medium": "mlx-community/whisper-medium-mlx",
            "large": "mlx-community/whisper-large-v3-mlx",
            "large-v3": "mlx-community/whisper-large-v3-mlx",
            "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
        }
        model_id = model_map.get(model, model_map["small"])
        result = mlx_whisper.transcribe(str(audio_path), path_or_hf_repo=model_id, language=language)
        return result.get("text", "").strip() or "[转录为空]"
    except ImportError:
        logger.info("mlx-whisper not available, falling back to openai-whisper CLI")
        return _transcribe_audio_cli(audio_path, model, language)
    except Exception as e:
        logger.warning(f"mlx-whisper error: {e}, falling back to CLI")
        return _transcribe_audio_cli(audio_path, model, language)


def _transcribe_audio_cli(audio_path: Path, model: str = "small", language: str = "zh") -> str:
    """Fallback: use openai-whisper CLI."""
    result = subprocess.run(
        ["whisper", str(audio_path), "--model", model, "--language", language,
         "--output_format", "txt", "--output_dir", str(audio_path.parent)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.warning(f"Whisper CLI failed: {result.stderr[:200]}")
        return "[转录失败]"
    txt_file = audio_path.with_suffix(".txt")
    if txt_file.exists():
        text = txt_file.read_text(encoding="utf-8").strip()
        txt_file.unlink()
        return text
    return "[转录失败 - 无输出文件]"


# ---------------------------------------------------------------------------
# 5) Write individual transcript file
# ---------------------------------------------------------------------------

def _safe_filename(title: str, max_len: int = 80) -> str:
    """Create a filesystem-safe filename from a video title."""
    safe = re.sub(r'[\\/:*?"<>|\n\r#]', '', title)
    return safe[:max_len].strip()


def write_transcript_file(
    output_dir: Path, index: int, video: dict, text: str, source_url: str,
) -> Path:
    """Write a single transcript to its own markdown file. Returns the file path."""
    num = str(index).zfill(2)
    safe_title = _safe_filename(video["title"])
    filename = f"{num}-{safe_title}.md"
    filepath = output_dir / filename

    content = (
        f"# {video['title']}\n\n"
        f"> 日期: {video.get('date', 'unknown')} | 来源: {video['url']}\n\n"
        f"{text}\n"
    )
    filepath.write_text(content, encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# 6) Pipeline orchestrator
# ---------------------------------------------------------------------------

async def run_pipeline(
    url: str,
    output_dir: str,
    whisper_model: str = "small",
    language: str = "zh",
    max_videos: int = 0,
    keep_audio: bool = False,
    work_dir: str = DEFAULT_WORK_DIR,
    concurrency: int = CONCURRENT_DOWNLOADS,
    skip: int = 0,
    auto_confirm: bool = False,
):
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    url_type = detect_url_type(url)

    # --- Single video ---
    if url_type == "video":
        logger.info("Detected: single video URL")
        videos = await scrape_single_video(url)
        if not videos:
            logger.error("Failed to get video info.")
            return
        # Download + transcribe
        video = videos[0]
        safe_name = re.sub(r'[^\w\-]', '_', video["video_id"])
        audio_file = work / f"{safe_name}.mp3"
        sem = asyncio.Semaphore(1)
        ok = await download_single_audio(video["url"], audio_file, sem)
        if not ok:
            logger.error("Download failed.")
            return
        logger.info(f"Transcribing: {video['title'][:50]}...")
        text = transcribe_audio_mlx(audio_file, model=whisper_model, language=language)
        if not keep_audio and audio_file.exists():
            audio_file.unlink()
        filepath = write_transcript_file(out_dir, 1, video, text, url)
        logger.info(f"Done! Output: {filepath}")
        return

    # --- User profile ---
    if url_type == "user":
        logger.info("Detected: user profile URL")
        logger.info("=" * 60)
        logger.info("STEP 1: Scraping user profile...")
        logger.info("=" * 60)
        videos = await scrape_user_videos(url, max_videos=max_videos)

        if not videos:
            logger.error("No videos found.")
            return

        # Ask for confirmation (unless --yes flag)
        if not auto_confirm:
            print()
            print("=" * 60)
            print(f"找到 {len(videos)} 个视频，确定要全部下载并转录吗？")
            print(f"预计耗时：{len(videos) * 45 // 60} - {len(videos) * 75 // 60} 分钟")
            print("输入 y 继续，n 取消，或输入数字限制下载数量：")
            print("=" * 60)
            answer = input("> ").strip().lower()
            if answer == "n" or answer == "":
                logger.info("已取消。")
                return
            if answer.isdigit():
                limit = int(answer)
                videos = videos[:limit]
                logger.info(f"限制为前 {limit} 个视频")
            elif answer != "y":
                logger.info("已取消。")
                return

        if skip > 0:
            logger.info(f"Skipping first {skip} videos (already processed)")
            videos = videos[skip:]

        if not videos:
            logger.info("No remaining videos to process.")
            return

        total = len(videos)
        logger.info(f"Starting batched pipeline for {total} videos...")

        semaphore = asyncio.Semaphore(concurrency)
        start_time = time.monotonic()
        success_count = 0
        fail_count = 0

        for batch_start in range(0, total, BATCH_SIZE):
            batch = videos[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1

            if batch_start > 0:
                pause = random.uniform(BATCH_PAUSE_MIN, BATCH_PAUSE_MAX)
                logger.info(f"--- Rate limit: pausing {pause:.0f}s ---")
                await asyncio.sleep(pause)

            logger.info(f"--- BATCH {batch_num}: videos {batch_start+1}-{batch_start+len(batch)} / {total} ---")

            audio_files = []
            download_tasks = []
            for i, video in enumerate(batch):
                idx = batch_start + i + 1 + skip
                safe_name = re.sub(r'[^\w\-]', '_', video.get("video_id", f"v{idx}"))
                audio_file = work / f"{safe_name}.mp3"
                audio_files.append((idx, video, audio_file))
                delay = i * random.uniform(DOWNLOAD_DELAY_MIN, DOWNLOAD_DELAY_MAX)
                download_tasks.append(
                    download_single_audio(video["url"], audio_file, semaphore, delay=delay)
                )

            logger.info(f"Downloading {len(batch)} videos (max {concurrency} parallel)...")
            results = await asyncio.gather(*download_tasks, return_exceptions=True)

            for (idx, video, audio_file), result in zip(audio_files, results):
                if isinstance(result, Exception) or result is False:
                    logger.warning(f"[{idx}/{total+skip}] Download failed: {video['title'][:40]}")
                    write_transcript_file(out_dir, idx, video, "[下载失败，已跳过]", url)
                    fail_count += 1
                    continue

                logger.info(f"[{idx}/{total+skip}] Transcribing: {video['title'][:40]}...")
                text = transcribe_audio_mlx(audio_file, model=whisper_model, language=language)
                write_transcript_file(out_dir, idx, video, text, url)
                success_count += 1

                if not keep_audio and audio_file.exists():
                    audio_file.unlink()

                elapsed = time.monotonic() - start_time
                done = success_count + fail_count
                remaining = total - done
                eta = (elapsed / done) * remaining if done > 0 else 0
                logger.info(f"[{idx}/{total+skip}] Done. ETA: {int(eta//60)}m{int(eta%60)}s")

        elapsed_total = time.monotonic() - start_time
        logger.info(f"ALL DONE! {success_count}/{total} videos in {int(elapsed_total//60)}m{int(elapsed_total%60)}s")
        logger.info(f"Output directory: {out_dir}")
        if fail_count > 0:
            logger.warning(f"{fail_count} videos failed to download")
        return

    # --- Unknown URL ---
    logger.error(f"Cannot determine URL type: {url}")
    logger.error("Expected a Douyin video URL (/video/xxx) or user profile URL (/user/xxx)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download Douyin videos and transcribe audio to text. "
        "Supports single video URLs and user profile URLs.",
    )
    parser.add_argument("url", help="Douyin video or user profile URL")
    parser.add_argument("--output-dir", default="./transcripts", help="Output directory for transcript files")
    parser.add_argument("--whisper-model", default="small", help="Whisper model: tiny/base/small/medium/large")
    parser.add_argument("--language", default="zh", help="Audio language for Whisper")
    parser.add_argument("--max-videos", type=int, default=0, help="Max videos (0=all, only for user profiles)")
    parser.add_argument("--keep-audio", action="store_true", help="Keep audio files after transcription")
    parser.add_argument("--work-dir", default=DEFAULT_WORK_DIR, help="Temp work directory")
    parser.add_argument("--concurrency", type=int, default=CONCURRENT_DOWNLOADS, help="Parallel downloads")
    parser.add_argument("--skip", type=int, default=0, help="Skip first N videos (for resuming)")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation for batch downloads")

    args = parser.parse_args()

    asyncio.run(run_pipeline(
        url=args.url,
        output_dir=args.output_dir,
        whisper_model=args.whisper_model,
        language=args.language,
        max_videos=args.max_videos,
        keep_audio=args.keep_audio,
        work_dir=args.work_dir,
        concurrency=args.concurrency,
        skip=args.skip,
        auto_confirm=args.yes,
    ))


if __name__ == "__main__":
    main()
