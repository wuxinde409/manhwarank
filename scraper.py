import asyncio
import random
import time
import os
import httpx
from fake_useragent import UserAgent
from playwright.async_api import async_playwright
# from playwright_stealth import stealth
import playwright_stealth
from playwright_stealth import stealth_async
# 初始化隨機 UA 產生器
ua = UserAgent()

# 模擬真實的參照位址 (Referer) 清單
REFERER_LIST = [
    'https://www.google.com/',
    'https://www.bing.com/',
    'https://asuracomic.net/',
    'https://www.facebook.com/'
]
async def download_image(client, img_url, title):
    """解決 Referral Denied 並將圖片存入本地 images 資料夾"""
    headers = {
        "Referer": "https://asuracomic.net/",
        "User-Agent": ua.random
    }
    
    # 清理標題名稱以防非法字元，若標題為空則給予隨機名稱
    safe_title = "".join([c for c in (title or "untitled") if c.isalnum() or c in (' ', '_')]).rstrip()
    filename = f"{safe_title}_{random.randint(100, 999)}.jpg"
    filepath = f"images/{filename}"

    try:
        resp = await client.get(img_url, headers=headers)
        if resp.status_code == 200:
            with open(filepath, "wb") as f:
                f.write(resp.content)
            return filepath
    except Exception as e:
        print(f"下載出錯 {title}: {e}")
    return "Download Failed"
async def random_human_delay():
    """設定隨機延遲時間，模擬不規則的人類行為模式"""
    # 延遲秒數清單，加入一些長短不一的間隔
    delay_choices = [1, 3, 5, 8, 12, 1.5, 2.7]
    delay = random.choice(delay_choices)
    print(f"模式模擬：隨機延遲 {delay} 秒...")
    await asyncio.sleep(delay)

async def check_honeypot(element):
    """
    避免蜜罐陷阱 (Honeypot Traps)：
    檢查連結是否包含隱藏樣式（如 display:none），避免掉入無限循環 [cite: 121]。
    """
    is_hidden = await element.evaluate(
        "el => window.getComputedStyle(el).display === 'none' || window.getComputedStyle(el).visibility === 'hidden'"
    )
    return is_hidden


async def run_protected_scraper():
    results = []
    os.makedirs("images", exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        current_ua = ua.random
        current_referer = random.choice(REFERER_LIST)

        context = await browser.new_context(
            user_agent=current_ua,
            extra_http_headers={'Referer': current_referer},
            viewport={'width': 1920, 'height': 1080}
        )

        page = await context.new_page()
        await stealth_async(page)

        try:
            # target_url = "https://asuracomic.net/series?page=2"
            target_url = "https://myanimelist.net/manga/genre/1/Action"
            print(f"正在前往：{target_url}")

            # 攔截網路請求，收集圖片 URL
            image_urls = []

            async def handle_response(response):
                if "https://myanimelist.net/images/manga" in response.url:
                    if "webp" in response.url:
                        image_urls.append(response.url)

            page.on("response", handle_response)

            # 前往目標頁面
            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                print("頁面載入超時，嘗試繼續...")
                pass

            # 隨機延遲，等圖片請求跑完
            await random_human_delay()

            # 抓取所有漫畫連結
            cards = await page.query_selector_all('a[href*="series/"]')
            print(f"偵測到 {len(cards)} 個漫畫名稱")
            print(f"攔截到 {len(image_urls)} 張圖片 URL")

            async with httpx.AsyncClient() as client:
                img_index = 0
                for i ,card in enumerate:

                    # 檢查，跳過隱藏元素
                    if await check_honeypot(card):
                        print(f"偵測到蜜罐，跳過第 {i} 個連結")
                        continue

                    href = await card.get_attribute("href")

                    # 抓標題
                    title_element = await card.query_selector('div[class*="w-\\[100\\%\\]"]')
                    title = await title_element.inner_text() if title_element else "未知標題"
                    title = title.strip()

                    # 對應攔截到的圖片 URL
                    src = image_urls[img_index] if img_index < len(image_urls) else None
                    img_index += 1

                    if src:
                        print(f"發現漫畫：{title} - URL: {src}")
                        local_path = await download_image(client, src, title)
                        results.append({
                            "title": title,
                            "href": href,
                            "path": local_path
                        })
                    else:
                        print(f"發現漫畫：{title} - 無圖片")
                        results.append({
                            "title": title,
                            "href": href,
                            "path": "無圖片"
                        })

            # 輸出表格
            print("\n" + "="*70)
            print(f"{'漫畫名稱':<30} | {'存儲路徑'}")
            print("-" * 70)
            for res in results:
                print(f"{res['title'][:30]:<30} | {res['path']}")
            print("="*70)

        except Exception as e:
            print(f"執行過程中發生異常 - {e}")
        finally:
            await browser.close()
if __name__ == "__main__":
    asyncio.run(run_protected_scraper())