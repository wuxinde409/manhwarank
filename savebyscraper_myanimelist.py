import asyncio
import random
import os
import httpx
from fake_useragent import UserAgent
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

# 初始化
ua = UserAgent()
REFERER_LIST = ['https://www.google.com/', 'https://myanimelist.net/']

async def random_human_delay():
    delay = random.choice([1, 2, 3, 1.5, 2.5])
    print(f"模式模擬：隨機延遲 {delay} 秒...")
    await asyncio.sleep(delay)

async def check_honeypot(element):
    is_hidden = await element.evaluate(
        "el => window.getComputedStyle(el).display === 'none' || window.getComputedStyle(el).visibility === 'hidden'"
    )
    return is_hidden

async def download_image(client, img_url, title,folder_name):
    """下載圖片並存入本地資料夾"""
    headers = {"User-Agent": ua.random, "Referer": "https://myanimelist.net/"}
    safe_title = "".join([c for c in title if c.isalnum() or c in (' ', '_')]).rstrip()
    filename = f"{safe_title}_{random.randint(100, 999)}.jpg"
    filepath = f"{folder_name}/{filename}"

    try:
        resp = await client.get(img_url, headers=headers)
        if resp.status_code == 200:
            with open(filepath, "wb") as f:
                f.write(resp.content)
            return filepath
    except Exception as e:
        print(f"圖片下載出錯 {title}: {e}")
    return "Download Failed"

async def run_protected_scraper(folder_name):
    results = []
    # os.makedirs("images", exist_ok=True)
    os.makedirs(folder_name, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=ua.random,
            extra_http_headers={'Referer': random.choice(REFERER_LIST)},
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()
        await stealth_async(page)

        try:
            # target_url = "https://myanimelist.net/manga/genre/1/Action"
            target_url ="https://myanimelist.net/manga/genre/10/Fantasy"
            print(f"正在前往：{target_url}")
            await random_human_delay()
            # await page.mouse.wheel(0, 2000)
            for _ in range(3):  # 往下滾動 4 次
                await page.mouse.wheel(0, 800) # 每次滾動 800 像素 (大約一個螢幕高度)
                await asyncio.sleep(random.uniform(0.8, 1.8)) # 每次滾動後停頓看一看
            
            # --- 網路攔截邏輯開始 ---
            image_urls = []

            async def handle_response(response):
                # 針對 MyAnimeList 圖片網址特徵進行攔截 (常包含 images/manga 且為 webp 或 jpg)
                if "https://myanimelist.net/images/manga/" in response.url:
                    if "webp" in response.url or "jpg" in response.url:
                        # 避免同一張圖片被重複記錄
                        if response.url not in image_urls:
                            image_urls.append(response.url)

            page.on("response", handle_response)
            # --- 網路攔截邏輯結束 ---

            await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            
            # 由於 MAL 圖片是向下滾動時才會觸發網路請求，我們需要模擬滾動來啟動攔截器
            print("正在滾動頁面以觸發網路請求攔截...")
            # await page.mouse.wheel(0, 2000)
            for _ in range(3):  # 往下滾動 4 次
                await page.mouse.wheel(0, 800) # 每次滾動 800 像素 (大約一個螢幕高度)
                await asyncio.sleep(random.uniform(0.8, 1.8)) # 每次滾動後停頓看一看
            # await random_human_delay()

            # 抓取所有漫畫連結 (MAL 結構)
            cards = await page.query_selector_all('div.seasonal-anime')
            print(f"偵測到 {len(cards)} 個漫畫卡片")
            print(f"攔截到 {len(image_urls)} 張圖片 URL")

            async with httpx.AsyncClient() as client:
                img_index = 0
                for i, card in enumerate(cards):

                    if await check_honeypot(card):
                        print(f"偵測到蜜罐，跳過第 {i} 個連結")
                        continue

                    # 抓取標題與連結 (MAL 結構)
                    link_element = await card.query_selector('.link-title')
                    if not link_element:
                        continue

                    title = await link_element.inner_text()
                    title = title.strip()
                    href = await link_element.get_attribute("href")
                    img_element = await card.query_selector('img')
                    src = None
                    
                    if img_element:
                        # 2. MAL 的實際高畫質 .webp 網址通常放在 data-src 或 srcset 中
                        # 我們優先抓取 data-src，如果沒有才退而求其次抓 src
                        src = await img_element.get_attribute("data-src")
                        if not src:
                            src = await img_element.get_attribute("src")

                    if src:
                        print(f"發現漫畫：{title[:20]}... - 開始下載圖片")
                        local_path = await download_image(client, src, title,folder_name)
                        results.append({
                            "title": title,
                            "href": href,
                            "path": local_path
                        })
                        await asyncio.sleep(random.uniform(0.5, 3.9))
                    else:
                        print(f"發現漫畫：{title[:20]}... - ⚠️ 無圖片標籤")
                        results.append({
                            "title": title,
                            "href": href,
                            "path": "無圖片"
                        })               

                    # 對應攔截到的圖片 URL
                    # src = image_urls[img_index] if img_index < len(image_urls) else None
                    # img_index += 1

                    # if src:
                    #     print(f"發現漫畫：{title}... - 開始下載圖片")
                    #     local_path = await download_image(client, src, title)
                    #     results.append({
                    #         "title": title,
                    #         "href": href,
                    #         "path": local_path
                    #     })
                    # else:
                    #     print(f"發現漫畫：{title[:20]}... - 無對應攔截圖片")
                    #     results.append({
                    #         "title": title,
                    #         "href": href,
                    #         "path": "無圖片"
                    #     })

            # 輸出表格
            print("\n" + "="*70)
            print(f"{'漫畫名稱':<30} | {'存儲路徑'}")
            print("-" * 70)
            for res in results[:10]: # 只印前 10 筆預覽
                print(f"{res['title'][:30]:<30} | {res['path']}")
            print("="*70)

        except Exception as e:
            print(f"執行過程中發生異常 - {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    try:
        user_input = ""
        while not user_input:
            user_input = input("\n請輸入要儲存的資料夾名稱 :").strip()    
        asyncio.run(run_protected_scraper(user_input))
    except KeyboardInterrupt:
        print("\n\n 收到強制終止指令 (Ctrl+C)！")