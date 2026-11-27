import asyncio
import json
import os
import sys
import subprocess
from bs4 import BeautifulSoup
from aiohttp import web

# Global variable to hold scraped results in memory
SCRAPED_DATA = []

def ensure_playwright_browsers():
    """Ensure Playwright Chromium is installed."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("❌ 'playwright' missing. Please check requirements.txt.")
        sys.exit(1)

    print("⚙️ Checking Playwright binaries...")
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        print("✅ Playwright Chromium ready!")
    except Exception as e:
        print(f"⚠️ Browser install warning: {e}")

async def scrape_band_posts(target_url="https://www.band.us/@reqfwa"):
    global SCRAPED_DATA
    from playwright.async_api import async_playwright

    print(f"🚀 Scraping started for: {target_url}")
    
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
                "--disable-gpu"
            ]
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        
        page = await context.new_page()
        await page.route("**/*.{png,jpg,jpeg,gif,svg,webp,css,woff,woff2}", lambda route: route.abort())

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            
            try:
                await page.wait_for_selector("div.gPostItem, div._postItem, article", timeout=15000)
            except Exception:
                await page.wait_for_timeout(5000)

            for _ in range(3):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(1500)

            html_content = await page.content()

        finally:
            await browser.close()

        soup = BeautifulSoup(html_content, "html.parser")
        results = []

        post_elements = soup.select("div.gPostItem, div._postItem, article, div.cPostCard")
        
        for idx, post in enumerate(post_elements, 1):
            text_content = post.get_text(separator="\n", strip=True)
            if text_content and text_content.lower() != "loading...":
                results.append({
                    "post_id": idx,
                    "content": text_content
                })

        if not results:
            main_body = soup.find("main") or soup.find("body")
            if main_body:
                text = main_body.get_text(separator="\n", strip=True)
                if "loading..." not in text.lower()[:50]:
                    results.append({
                        "post_id": 1,
                        "content": text
                    })

        SCRAPED_DATA = results
        
        # Also write to file locally as backup
        with open("band_posts.json", "w", encoding="utf-8") as f:
            json.dump(SCRAPED_DATA, f, ensure_ascii=False, indent=4)

        print(f"✅ Scraping finished! Extracted {len(SCRAPED_DATA)} items.")

# Web Routes for Render Subdomain
async def handle_root(request):
    """Raw JSON viewing on browser."""
    return web.json_response(SCRAPED_DATA)

async def handle_trigger(request):
    """Manually trigger scraping via /scrape URL."""
    asyncio.create_task(scrape_band_posts())
    return web.Response(text="🚀 Scraper triggered in background! Refresh root '/' after a few seconds.")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_root)
    app.router.add_get('/scrape', handle_trigger)

    # Render automatically sets PORT environment variable
    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Web Server listening on port {port}")

async def main():
    ensure_playwright_browsers()
    
    # 1. Start Web Server first so Render detects port immediately
    await start_web_server()
    
    # 2. Run initial scrape pass
    await scrape_band_posts()

    # Keep server alive
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
