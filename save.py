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
    delay = random.choice([1, 2, 3, 1.5, 2.5,1.3,2.1,2.4])
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

async def run_protected_scraper(base_url, folder_name,start_count_str, max_pages):
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
            # await page.mouse.wheel(0, 2000)
            image_urls = []
            async def handle_response(response):
                # 針對 MyAnimeList 圖片網址特徵進行攔截 (常包含 images/manga 且為 webp 或 jpg)
                if "https://myanimelist.net/images/manga/" in response.url:
                    if "webp" in response.url or "jpg" in response.url:
                        if response.url not in image_urls:
                            image_urls.append(response.url)

            page.on("response", handle_response)
            # --- 網路攔截邏輯結束 ---
            for current_page in range(start_count_str,max_pages+1):
                if current_page==1:
                    target_url=base_url
                else:
                    target_url=f"{base_url}?page={current_page}"
                print(f"\n正在處理第 {current_page}/{max_pages} 頁 ")
                print(f"正在前往：{target_url}")
                await page.goto(target_url, wait_until="domcontentloaded", timeout=40000)
                # await page.wait_for_selector('div.seasonal-anime', timeout=15000)
                print("正在滾動頁面以觸發網路請求攔截...")
                await page.mouse.wheel(0, 1000)
                for _ in range(3):  # 往下滾動 4 次
                    await page.mouse.wheel(0, 800) # 每次滾動 800 像素 (大約一個螢幕高度)
                    await asyncio.sleep(random.uniform(0.8, 1.8)) # 每次滾動後停頓看一看
                # await random_human_delay()

                # 抓取所有漫畫連結 (MAL 結構)
                cards = await page.query_selector_all('div.seasonal-anime')
                if  not cards:
                    print(f" 第 {current_page} 頁初次讀取未找到檔案")
                    await page.reload(wait_until="domcontentloaded", timeout=50000)
                    await page.mouse.wheel(0, 800)
                    cards = await page.query_selector_all('div.seasonal-anime')
                if cards:
                    print(f"偵測到 {len(cards)} 個漫畫卡片")
                else:
                    print(f"目前在第幾{start_count_str}頁卡死")
                    break


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
                            await asyncio.sleep(random.uniform(0.6, 1.2))
                        else:
                            print(f"發現漫畫：{title[:20]}... -  無圖片標籤")
                            results.append({
                                "title": title,
                                "href": href,
                                "path": "無圖片"
                            })               
                if current_page < max_pages:
                    safe_delay = random.uniform(6.0, 10.0)
                    print(f"\n第 {current_page} 頁處理完畢。為了模擬人類行為，休息 {safe_delay:.1f} 秒...")
                    await asyncio.sleep(safe_delay)
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
        base_url=""
        while not base_url:
            base_url = input("請輸入目標種類網址 :").strip()
        start_page = input("從第幾頁開始 :").strip()
        start_count_str = int(start_page) if start_page.isdigit() else 1
        
        page_count_str = input("到底幾頁結束 :").strip()
        max_pages = int(page_count_str) if page_count_str.isdigit() else 1
        asyncio.run(run_protected_scraper(base_url, user_input,start_count_str, max_pages))
    except KeyboardInterrupt:
        print("\n\n 收到強制終止指令 (Ctrl+C)！")
        #https://myanimelist.net/manga/genre/37/Supernatural