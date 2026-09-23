import os
import json
import hashlib
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

def get_recent_posts():
    """ดึง 5 โพสต์ล่าสุดจากหน้าเพจ"""
    posts_data = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        try:
            page.goto(PAGE_URL, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)
            
            # เลื่อนหน้าจอลงเล็กน้อยเพื่อให้โหลดโพสต์ย้อนหลัง
            page.evaluate("window.scrollBy(0, 1000)")
            page.wait_for_timeout(2000)

            posts = page.locator('div[role="feed"] > div, div[role="article"]')
            count = posts.count()
            
            # ตรวจสอบ 5 โพสต์แรก
            for i in range(min(5, count)):
                item = posts.nth(i)
                text = item.inner_text().strip()
                if len(text) > 20:  # กรองเฉพาะกล่องที่มีเนื้อหาโพสต์จริง
                    # สร้าง Hash ID ของโพสต์เพื่อความแม่นยำ
                    post_id = hashlib.md5(text.encode("utf-8")).hexdigest()
                    preview_text = text[:350] + ("..." if len(text) > 350 else "")
                    posts_data.append({
                        "id": post_id,
                        "preview": preview_text,
                        "full_text": text,
                        "url": PAGE_URL
                    })
        except Exception as e:
            print(f"Scraping Error: {e}")
        finally:
            browser.close()
            
    return posts_data

def main():
    recent_posts = get_recent_posts()
    if not recent_posts:
        print("ไม่พบโพสต์ หรือโหลดหน้าเว็บไม่สำเร็จ")
        return

    # โหลดประวัติโพสต์ที่เคยแจ้งเตือนแล้ว
    history_ids = []
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    history_ids = data
                elif isinstance(data, dict) and "full_text" in data:
                    # รองรับไฟล์แคชเวอร์ชันเก่า
                    old_id = hashlib.md5(data["full_text"].encode("utf-8")).hexdigest()
                    history_ids = [old_id]
        except Exception:
            history_ids = []

    new_posts_found = []
    # ตรวจหาโพสต์ใหม่ (วนจากโพสต์เก่าไปใหม่ เพื่อให้เวลาแจ้งเตือนเรียงตามลำดับเวลา)
    for post in reversed(recent_posts):
        if post["id"] not in history_ids:
            new_posts_found.append(post)

    if new_posts_found:
        print(f"🔔 ตรวจพบโพสต์ใหม่ {len(new_posts_found)} โพสต์!")
        for post in new_posts_found:
            send_discord_webhook(content=post["preview"], url=post["url"])
            history_ids.append(post["id"])

        # เก็บประวัติ 30 โพสต์ล่าสุดกันรายการยาวเกินไป
        history_ids = history_ids[-30:]
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(history_ids, f, ensure_ascii=False, indent=2)
    else:
        print("ℹ️ ไม่มีโพสต์ใหม่ (ทุกโพสต์เคยแจ้งเตือนไปแล้ว)")

if __name__ == "__main__":
    main()
