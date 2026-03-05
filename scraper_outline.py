import asyncio
from playwright.async_api import async_playwright
from fake_useragent import UserAgent

ua = UserAgent()

async def test_series_api():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=ua.random,
            viewport={'width': 1920, 'height': 1080}
        )
        
        # 停用 Service Worker
        await context.add_init_script("navigator.serviceWorker.register = () => Promise.resolve()")
        
        page = await context.new_page()
        series_data = []

        async def handle_response(response):
            if "gg.asuracomic.net/api/series" in response.url:
                try:
                    data = await response.json()
                    print(f" 攔截到 series API：{response.url}")
                    print(str(data)[:500])
                    series_data.append(data)
                except Exception as e:
                    print(f"解析失敗：{e}")

        page.on("response", handle_response)

        await page.goto("https://asuracomic.net/series?page=1", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(10)
        next_data = await page.evaluate("""
            () => {
                const el = document.getElementById('__NEXT_DATA__');
                return el ? JSON.parse(el.textContent) : null;
            }
        """)
        
        if next_data:
            print("找到 __NEXT_DATA__！")
            print(str(next_data)[:500])
        else:
            print("沒有找到 __NEXT_DATA__")

asyncio.run(test_series_api())