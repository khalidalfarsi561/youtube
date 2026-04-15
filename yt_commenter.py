import asyncio
import json
import logging
import os
import random
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

import google.generativeai as genai
import urllib.request
from dotenv import load_dotenv
from pathlib import Path
from playwright.async_api import async_playwright


VIDEO_URLS = [
    "https://www.youtube.com/watch?v=Mlc5DfyvhTM",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
]

ARABIC_PROMPT = "اكتب تعليقاً واحداً فقط باللغة العربية بناءً على عنوان الفيديو: {title}. يجب أن يكون التعليق قصيراً، إيجابياً، ويبدو كأنه من شخص حقيقي. أضف إيموجي واحد فقط. ممنوع كتابة أي شرح، ممنوع كتابة مقدمات، أرسل نص التعليق فقط"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
VIEWPORT = {"width": 1920, "height": 1080}
SCROLL_DISTANCE = 600
COMMENT_PLACEHOLDERS = ["#placeholder-area", "#simplebox-placeholder"]
COMMENT_INPUT_SELECTOR = "#contenteditable-root"
SUBMIT_SELECTOR = "ytd-button-renderer#submit-button button"

COOKIES: List[Dict[str, Any]] = [
    {"domain": ".youtube.com", "expirationDate": 1810723888.59786, "hostOnly": False, "httpOnly": False, "name": "__Secure-1PAPISID", "path": "/", "sameSite": "unspecified", "secure": True, "session": False, "storeId": "0", "value": "Q4YHbI1vx-taKkeh/AP1QExuWNYRazzHds", "id": 1},
    {"domain": ".youtube.com", "expirationDate": 1810723888.600218, "hostOnly": False, "httpOnly": True, "name": "__Secure-1PSID", "path": "/", "sameSite": "unspecified", "secure": True, "session": False, "storeId": "0", "value": "g.a0008wijNZsPlxw993wqWqgslphd-ssL7-e4S-TjduTzlLvVd642Ljit_Jhwy2Qp39SX6FmbsAACgYKAdQSARESFQHGX2MiSf14qubDgKtAEiNuVwuqRRoVAUF8yKphUz4rjcOtAgDicFmuK6mQ0076", "id": 2},
    {"domain": ".youtube.com", "expirationDate": 1807767740.147829, "hostOnly": False, "httpOnly": True, "name": "__Secure-1PSIDCC", "path": "/", "sameSite": "unspecified", "secure": True, "session": False, "storeId": "0", "value": "AKEyXzV_9xIaqaUVDEaQtBY7DPjPT-Z7Q-g81y6HhAIZX_y6e09PO-Jg-vC7_2OqOEcL733RCSI", "id": 3},
    {"domain": ".youtube.com", "expirationDate": 1807767737.571588, "hostOnly": False, "httpOnly": True, "name": "__Secure-1PSIDTS", "path": "/", "sameSite": "unspecified", "secure": True, "session": False, "storeId": "0", "value": "sidts-CjUBWhotCR6-4OXMXeWJhhqk-Blb-HuZ6QcTUX2oeFnSYGa2kd_BROTsRmwPO2PcuXztuxRLhBAA", "id": 4},
    {"domain": ".youtube.com", "expirationDate": 1810723888.598137, "hostOnly": False, "httpOnly": False, "name": "__Secure-3PAPISID", "path": "/", "sameSite": "no_restriction", "secure": True, "session": False, "storeId": "0", "value": "Q4YHbI1vx-taKkeh/AP1QExuWNYRazzHds", "id": 5},
    {"domain": ".youtube.com", "expirationDate": 1810723888.600468, "hostOnly": False, "httpOnly": True, "name": "__Secure-3PSID", "path": "/", "sameSite": "no_restriction", "secure": True, "session": False, "storeId": "0", "value": "g.a0008wijNZsPlxw993wqWqgslphd-ssL7-e4S-TjduTzlLvVd6425Jp2cH_xa5SDNd7oDG4tVAACgYKAXkSARESFQHGX2MivzxKNsfKHnfe6COxiDlPPRoVAUF8yKq8sgAlarJwJZ9hdH4cBImO0076", "id": 6},
    {"domain": ".youtube.com", "expirationDate": 1807767740.148106, "hostOnly": False, "httpOnly": True, "name": "__Secure-3PSIDCC", "path": "/", "sameSite": "no_restriction", "secure": True, "session": False, "storeId": "0", "value": "AKEyXzV5JIpKWaEvhcTqXT8ZfmUTLX4xgfScmOOtkGq-yNSZ99PeadPnoDUT4cIWObAXEgwfE78", "id": 7},
    {"domain": ".youtube.com", "expirationDate": 1807767737.572272, "hostOnly": False, "httpOnly": True, "name": "__Secure-3PSIDTS", "path": "/", "sameSite": "no_restriction", "secure": True, "session": False, "storeId": "0", "value": "sidts-CjUBWhotCR6-4OXMXeWJhhqk-Blb-HuZ6QcTUX2oeFnSYGa2kd_BROTsRmwPO2PcuXztuxRLhBAA", "id": 8},
    {"domain": ".youtube.com", "expirationDate": 1791458021.965949, "hostOnly": False, "httpOnly": True, "name": "__Secure-BUCKET", "path": "/", "sameSite": "lax", "secure": True, "session": False, "storeId": "0", "value": "CMAB", "id": 9},
    {"domain": ".youtube.com", "expirationDate": 1810723888.597359, "hostOnly": False, "httpOnly": False, "name": "APISID", "path": "/", "sameSite": "unspecified", "secure": False, "session": False, "storeId": "0", "value": "jtG5wJ6s8MKOTqvz/AnxkTtB5Yx2Yht-Ny", "id": 10},
    {"domain": ".youtube.com", "expirationDate": 1810723888.596637, "hostOnly": False, "httpOnly": True, "name": "HSID", "path": "/", "sameSite": "unspecified", "secure": False, "session": False, "storeId": "0", "value": "AqQekbD-ZkaWHyTip", "id": 11},
    {"domain": ".youtube.com", "expirationDate": 1807532985.267574, "hostOnly": False, "httpOnly": True, "name": "LOGIN_INFO", "path": "/", "sameSite": "no_restriction", "secure": True, "session": False, "storeId": "0", "value": "AFmmF2swRAIgTV-pO06fy9tblF0X92ISlahqVkOullEDhd-o1BgMpCkCIAV66vbadI82I95sg_nKzqOdCr7G0f7oEpeQcNUDXJAI:QUQ3MjNmd0RIZERPSVRIZzZCNk1BRTRRaFJhSENpRXViZVQzTzFkZHVhWUVJaWVtZWhZTkRVYXJYQXd0dGJoUmpMZldYOHZJY1FmWWVZU1pNRHpJM1l4WV82Wm1wc3I1S1FQTGFHSGlTMEhVSFMwQ1JWVXo1bkdodHBMdmktZ1k4TlBOVk1RVUxFZWY5SjcxcGdLSVZUWG9xNmpRNmNTX05R", "id": 12},
    {"domain": ".youtube.com", "expirationDate": 1810791735.450505, "hostOnly": False, "httpOnly": False, "name": "PREF", "path": "/", "sameSite": "unspecified", "secure": True, "session": False, "storeId": "0", "value": "f4=4000000&f6=40000000&tz=Asia.Muscat&f7=100", "id": 13},
    {"domain": ".youtube.com", "expirationDate": 1810723888.597614, "hostOnly": False, "httpOnly": False, "name": "SAPISID", "path": "/", "sameSite": "unspecified", "secure": True, "session": False, "storeId": "0", "value": "Q4YHbI1vx-taKkeh/AP1QExuWNYRazzHds", "id": 14},
    {"domain": ".youtube.com", "expirationDate": 1810723888.599946, "hostOnly": False, "httpOnly": False, "name": "SID", "path": "/", "sameSite": "unspecified", "secure": False, "session": False, "storeId": "0", "value": "g.a0008wijNZsPlxw993wqWqgslphd-ssL7-e4S-TjduTzlLvVd642K34UTZtdvfWNnfELT9n_mAACgYKAQcSARESFQHGX2Mi2Y4D7brZp28CurlGMwjlRRoVAUF8yKqcgveuMczB_LOgUC2Nj0Om0076", "id": 15},
    {"domain": ".youtube.com", "expirationDate": 1807767740.147383, "hostOnly": False, "httpOnly": False, "name": "SIDCC", "path": "/", "sameSite": "unspecified", "secure": False, "session": False, "storeId": "0", "value": "AKEyXzWlCU0hP4iKhqPxBcvc3I1CWtXizePUf42tEw80HugEMMwZtVUsHfW5uFTj-yiij-IJnQ", "id": 16},
    {"domain": ".youtube.com", "expirationDate": 1810723888.597083, "hostOnly": False, "httpOnly": True, "name": "SSID", "path": "/", "sameSite": "unspecified", "secure": True, "session": False, "storeId": "0", "value": "AME1EELg4RzO0S-k5", "id": 17},
]


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


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
    return title


def build_prompt(title: str) -> str:
    return ARABIC_PROMPT.format(title=title)


def generate_comment(title: str) -> str:
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
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemma-4-31b-it")
    prompt = build_prompt(title)
    logging.info("Generating comment with Gemini.")
    response = model.generate_content(prompt)
    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("Gemini returned no text.")
    comment = text.strip()
    if not comment:
        raise RuntimeError("Gemini returned empty comment text.")
    return comment


async def add_cookies(context) -> None:
    cookies: List[Dict[str, Any]] = []
    for cookie in COOKIES:
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


async def comment_on_video(page, video_url: str, comment_text: str) -> None:
    logging.info("Opening video: %s", video_url)
    await page.goto(video_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)
    logging.info("Scrolling down %d px.", SCROLL_DISTANCE)
    await page.mouse.wheel(0, SCROLL_DISTANCE)
    await page.wait_for_timeout(5000)

    placeholder_locator = None
    for selector in COMMENT_PLACEHOLDERS:
        try:
            logging.info("Trying comment placeholder: %s", selector)
            locator = page.locator(selector).first
            await locator.wait_for(state="visible", timeout=8000)
            await locator.click(timeout=8000)
            placeholder_locator = locator
            break
        except Exception:
            continue
    if placeholder_locator is None:
        try:
            frame_locator = page.frame_locator("iframe").locator(COMMENT_PLACEHOLDERS[0]).first
            await frame_locator.wait_for(state="visible", timeout=8000)
            await frame_locator.click(timeout=8000)
            placeholder_locator = frame_locator
        except Exception:
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


async def main() -> None:
    setup_logging()
    video_url = random.choice(VIDEO_URLS)
    browser = None
    try:
        title = await fetch_video_title(video_url)
        logging.info("Fetched title: %s", title)
        comment_text = generate_comment(title)
        logging.info("Generated comment: %s", comment_text)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=USER_AGENT, viewport=VIEWPORT)
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