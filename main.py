import asyncio
import json
import os
import sys
import subprocess
from bs4 import BeautifulSoup

def ensure_playwright_browsers():
    """
    Terminal ki zaroorat nahi hai: Script khud hi check karke
    Playwright Chromium browser install kar legi.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("❌ 'playwright' library package missing hai. Pehle pip install playwright karein.")
        sys.exit(1)

    print("⚙️ Playwright browser binaries check ho rahe hain...")
    try:
        # Code se hi 'playwright install chromium' execute hoga
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        print("✅ Playwright Chromium successfull install ho gaya!")
    except Exception as e:
        print(f"⚠️ Browser install warning: {e}")

async def scrape_band_posts(target_url="https://www.band.us/@reqfwa", output_file="band_posts.json"):
    from playwright.async_api import async_playwright

    print(f"🚀 Scraping started for: {target_url}")
    
    async with async_playwright() as p:
        # Hosting environment ke liye memory-friendly browser flags
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
        
        # Resource blocking to save RAM/Bandwidth on hosting panel
        page = await context.new_page()
        await page.route("**/*.{png,jpg,jpeg,gif,svg,webp,css,woff,woff2}", lambda route: route.abort())

        try:
            # Page navigation & wait
            await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            
            # Post feed DOM load hone ka wait (max 15 sec)
            try:
                await page.wait_for_selector("div.gPostItem, div._postItem, article", timeout=15000)
            except Exception:
                # Content render ke liye fall back wait
                await page.wait_for_timeout(5000)

            # Lazy-loaded posts grab karne ke liye initial smooth scroll
            for _ in range(3):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(1500)

            html_content = await page.content()

        finally:
            await browser.close()

        # Parse content with BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        scraped_posts = []

        # Target post elements
        post_elements = soup.select("div.gPostItem, div._postItem, article, div.cPostCard")
        
        for idx, post in enumerate(post_elements, 1):
            text_content = post.get_text(separator="\n", strip=True)
            if text_content and text_content.lower() != "loading...":
                scraped_posts.append({
                    "post_id": idx,
                    "content": text_content
                })

        # Fallback parsing
        if not scraped_posts:
            main_body = soup.find("main") or soup.find("body")
            if main_body:
                text = main_body.get_text(separator="\n", strip=True)
                if "loading..." not in text.lower()[:50]:
                    scraped_posts.append({
                        "post_id": 1,
                        "content": text
                    })

        # Data JSON file mein write karein
        if scraped_posts:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(scraped_posts, f, ensure_ascii=False, indent=4)
            print(f"✅ Total {len(scraped_posts)} posts saved into '{output_file}'!")
        else:
            print("⚠️ No valid posts found to write.")

if __name__ == "__main__":
    # 1. Automatic browser setup without terminal
    ensure_playwright_browsers()
    
    # 2. Run Main Scraper Loop
    asyncio.run(scrape_band_posts())
