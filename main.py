import os
import json
import requests
from playwright.sync_api import sync_playwright

PAGE_URL = "https://www.facebook.com/naklongpoong"
STORAGE_FILE = "last_post.json"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

def send_discord_webhook(content, url):
    if not DISCORD_WEBHOOK_URL:
        print("ไม่พบ DISCORD_WEBHOOK_URL")
        return

    payload = {
        "username": "นักลงพุง Notifier",
        "avatar_url": "https://img.icons8.com/color/512/facebook-new.png",
        "embeds": [
            {
                "title": "📢 มีโพสต์ใหม่จากเพจ นักลงพุง!",
                "url": url,
                "description": content,
                "color": 3447003,
                "footer": {
                    "text": "Facebook Page Monitor • naklongpoong"
                }
            }
        ]
    }
    
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if res.status_code in [200, 204]:
            print("✅ ส่งแจ้งเตือนเข้า Discord สำเร็จ!")
        else:
            print(f"❌ ส่งไม่สำเร็จ: HTTP {res.status_code}")
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการส่ง Discord: {e}")

def get_latest_post():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        try:
            page.goto(PAGE_URL, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)
            
            posts = page.locator('div[role="feed"] > div, div[role="article"]')
            if posts.count() > 0:
                first_post = posts.first
                text = first_post.inner_text().strip()
                preview_text = text[:300] + ("..." if len(text) > 300 else "")
                return {"preview": preview_text, "full_text": text, "url": PAGE_URL}
        except Exception as e:
            print(f"Scraping Error: {e}")
        finally:
            browser.close()
    return None

def main():
    latest = get_latest_post()
    if not latest or not latest["preview"]:
        print("ไม่พบโพสต์ หรือโหลดหน้าเว็บไม่สำเร็จ")
        return

    last_data = {}
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                last_data = json.load(f)
        except Exception:
            last_data = {}

    if last_data.get("full_text") != latest["full_text"]:
        print("🔔 ตรวจพบโพสต์ใหม่ กำลังส่งการแจ้งเตือน...")
        send_discord_webhook(content=latest["preview"], url=latest["url"])
        
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(latest, f, ensure_ascii=False, indent=2)
    else:
        print("ℹ️ ยังไม่มีโพสต์ใหม่")

if __name__ == "__main__":
    main()
