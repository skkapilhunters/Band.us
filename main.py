import asyncio
import json
import os
import re
import subprocess
import sys
from bs4 import BeautifulSoup
from aiohttp import web

TARGET_URL = "https://www.band.us/@reqfwa"
BAND_ID = "67130116"
OUTPUT_FILE = "band_posts.json"
SCROLL_STEPS = 8  # Zyada posts chahiye toh isko badha sakte ho

SCRAPED_DATA = []
IS_SCRAPING = False


def ensure_playwright_browsers():
    """Terminal ke bina Playwright Chromium ensure karta hai."""
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        print("❌ 'playwright' install nahi hai. requirements.txt check karein.")
        sys.exit(1)

    print("⚙️ Playwright Chromium check/install ho raha hai...")
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
        print("✅ Playwright Chromium ready hai.")
    except Exception as e:
        print(f"⚠️ Browser setup warning: {e}")


def extract_post_id_from_element(post_el):
    """Post element ya uske links/attributes se Band post ID (e.g. 153217) nikaalta hai."""
    # 1. Direct href mein /post/<id> check karo
    for a_tag in post_el.find_all("a", href=True):
        match = re.search(r"/band/\d+/post/(\d+)", a_tag["href"])
        if match:
            return match.group(1), f"https://www.band.us{match.group(0)}" if a_tag["href"].startswith("/") else a_tag["href"]

    # 2. Element ya parent attributes mein numeric ID check karo
    for attr in ["data-post-no", "data-postno", "data-post-id", "data-id", "id"]:
        val = post_el.get(attr)
        if val:
            digits = re.search(r"\b(\d{4,})\b", str(val))
            if digits:
                pid = digits.group(1)
                return pid, f"https://www.band.us/band/{BAND_ID}/post/{pid}"

    return None, None


def get_all_posts_container(soup):
    """
    Page mein 'All Posts' heading/label dhundhta hai aur uske baad ka
    feed container return karta hai taaki Trending Posts / Notice skip ho sakein.
    """
    all_posts_label = soup.find(
        lambda tag: tag.name in ["h1", "h2", "h3", "h4", "div", "span", "p"]
        and tag.get_text(strip=True).lower() == "all posts"
    )

    if all_posts_label:
        # Sabse kareebi parent section/wrapper uthao jo heading ke neeche posts rakhta ho
        parent = all_posts_label.find_parent(["section", "div"])
        if parent and parent.parent:
            return parent.parent
        if parent:
            return parent

    return soup.find("main") or soup.body or soup


def parse_all_posts(html_content):
    """HTML se sirf 'All Posts' section ki posts parse karta hai."""
    soup = BeautifulSoup(html_content, "html.parser")
    container = get_all_posts_container(soup)

    # Agar 'All Posts' marker mila hai, toh uske baad ke elements par focus karo
    all_posts_marker = container.find(
        lambda tag: tag.name in ["h1", "h2", "h3", "h4", "div", "span", "p"]
        and tag.get_text(strip=True).lower() == "all posts"
    )

    candidate_elements = []
    if all_posts_marker:
        # Marker ke baad aane wale siblings / descendants dekho
        for el in all_posts_marker.find_all_next(["div", "article", "li"]):
            text = " ".join(el.get_text("\n", strip=True).split())
            if not text or len(text) < 25:
                continue
            if "trending posts" in text.lower() and len(text) < 60:
                continue
            pid, post_url = extract_post_id_from_element(el)
            if pid:
                candidate_elements.append((pid, post_url, el))

    # Fallback: Agar marker ke saath direct post ID wale cards nahi mile toh pure container mein dekho
    if not candidate_elements:
        for el in container.find_all(["div", "article"]):
            pid, post_url = extract_post_id_from_element(el)
            if pid:
                candidate_elements.append((pid, post_url, el))

    seen_ids = set()
    posts = []

    for pid, post_url, el in candidate_elements:
        if pid in seen_ids:
            continue

        raw_lines = [
            line.strip()
            for line in el.get_text("\n", strip=True).splitlines()
            if line.strip()
        ]
        content = "\n".join(raw_lines)

        # Bohat chhote ya sirf UI buttons wale blocks skip karo
        if not content or content.lower() == "loading..." or len(content) < 20:
            continue
        if content.strip().lower() == "all posts":
            continue

        seen_ids.add(pid)
        posts.append({
            "post_id": pid,
            "url": post_url,
            "content": content,
        })

    return posts


async def scrape_band_posts(target_url=TARGET_URL, scroll_steps=SCROLL_STEPS):
    global SCRAPED_DATA, IS_SCRAPING

    if IS_SCRAPING:
        print("⏳ Scrape pehle se chal raha hai, skip kar rahe hain.")
        return SCRAPED_DATA

    IS_SCRAPING = True
    from playwright.async_api import async_playwright

    print(f"🚀 All Posts scraping start: {target_url}")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--no-first-run",
                    "--no-zygote",
                    "--single-process",
                    "--disable-gpu",
                ],
            )

            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )

            page = await context.new_page()

            # Images/fonts/media block karke RAM aur bandwidth bachao
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,mp4,webm}",
                lambda route: route.abort(),
            )

            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)

                # Feed render hone ka wait
                try:
                    await page.wait_for_function(
                        "() => document.body && document.body.innerText.toLowerCase().includes('all posts')",
                        timeout=20000,
                    )
                except Exception:
                    await page.wait_for_timeout(5000)

                # Neeche scroll karke All Posts section ke aur items load karo
                prev_height = 0
                for step in range(scroll_steps):
                    curr_height = await page.evaluate("() => document.body.scrollHeight")
                    await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(2000)

                    new_height = await page.evaluate("() => document.body.scrollHeight")
                    print(f"📜 Scroll {step + 1}/{scroll_steps} | height: {curr_height} -> {new_height}")

                    if new_height == prev_height and new_height == curr_height:
                        break
                    prev_height = new_height

                html_content = await page.content()

            finally:
                await browser.close()

        results = parse_all_posts(html_content)
        SCRAPED_DATA = results

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(SCRAPED_DATA, f, ensure_ascii=False, indent=4)

        print(f"✅ All Posts scrape complete! Total posts saved: {len(SCRAPED_DATA)}")
        return SCRAPED_DATA

    except Exception as e:
        print(f"❌ Scrape error: {e}")
        return SCRAPED_DATA
    finally:
        IS_SCRAPING = False


# --- Render HTTP Server Routes ---

async def handle_root(request):
    return web.json_response({
        "band_id": BAND_ID,
        "section": "All Posts",
        "is_scraping": IS_SCRAPING,
        "count": len(SCRAPED_DATA),
        "posts": SCRAPED_DATA,
    })


async def handle_scrape(request):
    if IS_SCRAPING:
        return web.json_response({"status": "already_running"}, status=200)
    asyncio.create_task(scrape_band_posts())
    return web.json_response({"status": "triggered", "message": "Scraping All Posts in background."})


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/scrape", handle_scrape)

    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Server running on 0.0.0.0:{port}")


async def main():
    ensure_playwright_browsers()
    await start_web_server()
    await scrape_band_posts()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
