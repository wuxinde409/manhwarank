import asyncio
import random
import os
import httpx
from fake_useragent import UserAgent
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

ua = UserAgent()
REFERER_LIST = ['https://www.google.com/', 'https://myanimelist.net/']

# --- 新增：代理池連線模組 ---
async def get_proxy():
    """從本地端的 Proxy Pool 獲取一個隨機代理 IP"""
    try:
        async with httpx.AsyncClient() as client:
            # 呼叫 proxy_pool 的預設 API
            # response = await client.get("http://127.0.0.1:5010/get/", timeout=5.0) #這是抓本地端時候用的,因為我程式在docler裡面跑,這樣是抓不到的
            response = await client.get("http://host.docker.internal:5010/get/", timeout=5.0)
            if response.status_code == 200:
                proxy_data = response.json()
                proxy_ip = proxy_data.get("proxy")
                print(f"🛡️ 成功獲取代理 IP: {proxy_ip}")
                return proxy_ip
    except Exception as e:
        print(f" 無法連接到本地代理池 (請確認 Docker 是否已啟動): {e}")
    return None

async def delete_proxy(proxy_ip):
    """如果代理失效，通知 Proxy Pool 將其刪除"""
    try:
        async with httpx.AsyncClient() as client:
            await client.get(f"http://127.0.0.1:5010/delete/?proxy={proxy_ip}", timeout=3.0)
            print(f" 已從代理池中剔除失效 IP: {proxy_ip}")
    except:
        pass
# -----------------------------

async def random_human_delay():
    delay = random.choice([1, 2, 3, 1.5, 2.5,3.2,4.1,2.8,1.6,4.6,2.2,3.2,4])
    print(f"模式模擬：隨機延遲 {delay} 秒...")
    await asyncio.sleep(delay)

async def check_honeypot(element):
    is_hidden = await element.evaluate(
        "el => window.getComputedStyle(el).display === 'none' || window.getComputedStyle(el).visibility === 'hidden'"
    )
    return is_hidden

async def download_image(client, img_url, title):
    headers = {"User-Agent": ua.random, "Referer": "https://myanimelist.net/"}
    safe_title = "".join([c for c in title if c.isalnum() or c in (' ', '_')]).rstrip()
    filename = f"{safe_title}_{random.randint(100, 999)}.jpg"
    filepath = f"images/{filename}"

    try:
        # httpx Client 已經在外部掛載了代理，這裡直接請求即可
        resp = await client.get(img_url, headers=headers, timeout=10.0)
        if resp.status_code == 200:
            with open(filepath, "wb") as f:
                f.write(resp.content)
            return filepath
        else:
            print(f"圖片下載失敗，狀態碼: {resp.status_code}")
    except Exception as e:
        print(f"圖片下載出錯 {title}: {e}")
    return "Download Failed"

async def run_protected_scraper():
    results = []
    os.makedirs("romance", exist_ok=True)
    target_url = "https://myanimelist.net/manga/genre/22/Romance"

    MAX_RETRIES = 30  # 設定最大重試次數

    for attempt in range(MAX_RETRIES):
        print(f"\n=== 啟動第 {attempt + 1} 次嘗試 ===")
        
        #抽一個新的 IP #先設定可以
        # proxy_ip = await get_proxy()
        # pw_proxy = {"server": f"http://{proxy_ip}"} if proxy_ip else None
        proxy_ip = None
        pw_proxy = None

        try:
            # 將 Playwright 的啟動包在 try 區塊內，確保失敗時會關閉並釋放資源
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=ua.random,
                    extra_http_headers={'Referer': random.choice(REFERER_LIST)},
                    viewport={'width': 1920, 'height': 1080},
                    proxy=pw_proxy
                )
                page = await context.new_page()
                await stealth_async(page)

                print(f"正在前往：{target_url} (使用 IP: {proxy_ip or '本機網路'})")
                
                # 若這裡發生 ERR_TUNNEL_CONNECTION_FAILED，會立刻跳到 except 區塊
                await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                
                print("成功進入頁面，正在滾動以觸發載入...")
                for _ in range(4):
                    await page.mouse.wheel(0, 800)
                    await asyncio.sleep(random.uniform(0.8, 1.8))
                await random_human_delay()

                cards = await page.query_selector_all('div.seasonal-anime')
                print(f"偵測到 {len(cards)} 個漫畫卡片")

                # 如果連這步都順利完成，代表代理 IP 完全正常，進入下載階段
                httpx_proxies = {
                    "http://": f"http://{proxy_ip}",
                    "https://": f"http://{proxy_ip}"
                } if proxy_ip else None

                async with httpx.AsyncClient(proxies=httpx_proxies) as client:
                    for i, card in enumerate(cards):
                        if await check_honeypot(card):
                            continue

                        link_element = await card.query_selector('.link-title')
                        if not link_element: continue

                        title = (await link_element.inner_text()).strip()
                        href = await link_element.get_attribute("href")
                        
                        img_element = await card.query_selector('img')
                        src = None
                        if img_element:
                            src = await img_element.get_attribute("data-src") or await img_element.get_attribute("src")

                        if src:
                            print(f"發現漫畫：{title[:20]}... - 開始下載")
                            local_path = await download_image(client, src, title)
                            results.append({"title": title, "href": href, "path": local_path})
                            await asyncio.sleep(random.uniform(0.5, 1.8))
                        else:
                            results.append({"title": title, "href": href, "path": "無圖片"})

                # 若成功執行到這裡，代表該次抓取全部完成，強制跳出重試迴圈
                print("\n 頁面資料擷取完畢！")
                break 

        except Exception as e:
            error_msg = str(e).lower()
            print(f" 執行過程中發生異常: {e}")
            
            # 針對特定的網路連線錯誤，剔除代理 IP
            if proxy_ip and ("tunnel" in error_msg or "timeout" in error_msg or "connection" in error_msg or "net::" in error_msg):
                await delete_proxy(proxy_ip)
            
            if attempt < MAX_RETRIES - 1:
                print("準備重試...")
                await asyncio.sleep(2)  # 稍微等待讓網路資源釋放
            else:
                print(" 已達到最大重試次數，任務終止。")

    # 輸出表格
    if results:
        print("\n" + "="*70)
        print(f"{'漫畫名稱':<30} | {'存儲路徑'}")
        print("-" * 70)
        for res in results[:10]:
            print(f"{res['title'][:30]:<30} | {res['path']}")
        print("="*70)

if __name__ == "__main__":
    try:
        asyncio.run(run_protected_scraper())
    except KeyboardInterrupt:
        print("\n\n 收到強制終止指令 (Ctrl+C)！")