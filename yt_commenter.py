import asyncio
import json
import logging
import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import google.genai as genai
import urllib.request
from dotenv import load_dotenv
from playwright.async_api import async_playwright


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
VIEWPORT = {"width": 1920, "height": 1080}
SCROLL_DISTANCE = 1200
COMMENT_PLACEHOLDERS = ["yt-formatted-string#simplebox-placeholder", "div#placeholder-area", "#placeholder-area", "#simplebox-placeholder"]
COMMENT_INPUT_SELECTOR = "#contenteditable-root"
SUBMIT_SELECTOR = "ytd-button-renderer#submit-button button"
ARABIC_PROMPT = "اكتب تعليقاً واحداً فقط باللغة العربية بناءً على عنوان الفيديو: {title}. يجب أن يكون التعليق قصيراً، إيجابياً، ويبدو كأنه من شخص حقيقي. أضف إيموجي واحد فقط. ممنوع كتابة أي شرح، ممنوع كتابة مقدمات، أرسل نص التعليق فقط"


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def load_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_video_urls() -> List[str]:
    videos_path = Path("videos.txt")
    if not videos_path.exists():
        raise FileNotFoundError("videos.txt not found.")
    urls = [line.strip() for line in videos_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not urls:
        raise RuntimeError("videos.txt is empty.")
    logging.info("تم تحميل الروابط من الملف: %d", len(urls))
    return urls


def extract_video_id(video_url: str) -> str:
    parsed = urlparse(video_url)
    if parsed.hostname in {"www.youtube.com", "youtube.com", "m.youtube.com"}:
        query = parse_qs(parsed.query)
        if "v" in query and query["v"]:
            return query["v"][0]
    return video_url


async def fetch_video_title(video_url: str) -> str:
    video_id = extract_video_id(video_url)
    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    logging.info("Fetching title from oEmbed: %s", oembed_url)
    request = urllib.request.Request(oembed_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    title = payload.get("title", "").strip()
    if not title:
        raise RuntimeError("Failed to fetch video title from oEmbed.")
    logging.info("Fetched title: %s", title)
    return title


def build_prompt(title: str) -> str:
    return ARABIC_PROMPT.format(title=title)


def generate_comment(title: str) -> Optional[str]:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    if api_key:
                        os.environ["GEMINI_API_KEY"] = api_key
                        break
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to .env or the environment.")
    prompt = build_prompt(title)
    logging.info("Generating comment with Gemini.")
    last_error = None
    model_candidates = ("gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-2.5-pro-preview-03-25", "gemini-1.5-pro", "gemini-1.5-flash-002", "gemini-1.5-pro-002")
    for model_name in model_candidates:
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model=model_name, contents=prompt)
            text = getattr(response, "text", "") or ""
            text = text.strip()
            if text:
                return text
        except Exception as exc:
            last_error = exc
            logging.warning("Gemini model %s failed: %s", model_name, exc)
            message = str(exc)
            if "RESOURCE_EXHAUSTED" in message or "429" in message or "NOT_FOUND" in message or "404" in message:
                continue
            raise
    logging.warning("Gemini unavailable or quota blocked; continuing without generated comment. Last error: %s", last_error)
    return None


async def add_cookies(context) -> None:
    cookies_data = load_json_file("cookies.json")
    cookies: List[Dict[str, Any]] = []
    for cookie in cookies_data:
        cookies.append(
            {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie["domain"],
                "path": cookie["path"],
                "expires": cookie.get("expirationDate", -1),
                "httpOnly": cookie["httpOnly"],
                "secure": cookie["secure"],
                "sameSite": "None" if cookie["sameSite"] == "no_restriction" else ("Lax" if cookie["sameSite"] == "lax" else "Lax"),
            }
        )
    logging.info("Injecting %d cookies.", len(cookies))
    await context.add_cookies(cookies)


async def try_open_comment_box(page):
    for selector in COMMENT_PLACEHOLDERS:
        try:
            logging.info("Trying comment placeholder: %s", selector)
            locator = page.locator(selector).first
            await locator.wait_for(state="visible", timeout=8000)
            await locator.click(timeout=8000)
            return True
        except Exception:
            continue
    return False


async def comment_on_video(page, video_url: str, comment_text: str) -> None:
    logging.info("Opening video: %s", video_url)
    await page.goto(video_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)
    logging.info("Scrolling down %d px.", SCROLL_DISTANCE)
    await page.mouse.wheel(0, SCROLL_DISTANCE)
    await page.wait_for_timeout(10000)

    clicked = await try_open_comment_box(page)
    if not clicked:
        logging.warning("فشل العثور على الصندوق، جاري إعادة التحميل...")
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        await page.mouse.wheel(0, SCROLL_DISTANCE)
        await page.wait_for_timeout(10000)
        clicked = await try_open_comment_box(page)
        if not clicked:
            raise RuntimeError("Could not locate comment placeholder.")

    logging.info("Waiting for comment editor.")
    editor = page.locator(COMMENT_INPUT_SELECTOR).first
    await editor.wait_for(state="visible", timeout=15000)
    await editor.click(timeout=10000)
    await editor.fill(comment_text)

    delay_ms = random.randint(1800, 4200)
    logging.info("Waiting human-like delay: %d ms", delay_ms)
    await page.wait_for_timeout(delay_ms)

    logging.info("Submitting comment.")
    await page.locator(SUBMIT_SELECTOR).first.click(timeout=10000)

    try:
        await page.wait_for_timeout(5000)
        if await page.get_by_text(comment_text, exact=False).count() > 0:
            logging.info("تم التحقق من ظهور التعليق داخل الصفحة.")
            return
    except Exception:
        pass

    logging.info("لم يتم العثور على نص التعليق مباشرة بعد الإرسال، جاري انتظار إضافي للتحقق.")
    await page.wait_for_timeout(5000)
    if await page.get_by_text(comment_text, exact=False).count() == 0:
        raise RuntimeError("Comment submission could not be verified.")


async def main() -> None:
    setup_logging()
    load_dotenv()
    video_urls = load_video_urls()
    video_url = random.choice(video_urls)
    browser = None

    try:
        title = await fetch_video_title(video_url)
        comment_text = generate_comment(title)
        if not comment_text:
            logging.info("Skipping comment submission because Gemini did not return a usable comment.")
            return
        logging.info("Generated comment: %s", comment_text)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=USER_AGENT, viewport=VIEWPORT)
            # Stealth disabled due to package API mismatch; keeping headless/user-agent/viewport/cookies only.
            await add_cookies(context)
            page = await context.new_page()
            try:
                await comment_on_video(page, video_url, comment_text)
                logging.info("Comment submitted successfully.")
            finally:
                await context.close()
    except Exception as exc:
        logging.exception("Error during automation: %s", exc)
        if browser is not None:
            try:
                context = browser.contexts[0] if browser.contexts else None
                if context and context.pages:
                    await context.pages[0].screenshot(path="debug_error.png")
                    logging.info("Saved debug screenshot to debug_error.png")
            except Exception:
                logging.exception("Failed to save debug screenshot.")
            finally:
                await browser.close()
        raise
    else:
        if browser is not None:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
