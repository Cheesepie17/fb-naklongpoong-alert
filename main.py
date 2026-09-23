import os
import json
import hashlib
import requests
from playwright.sync_api import sync_playwright

PAGE_URL = "https://www.facebook.com/naklongpoong"
STORAGE_FILE = "last_post.json"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

def send_discord_webhook(content, url):
    """ส่งแจ้งเตือนเข้า Discord พร้อมแท็ก @everyone ให้เด้งบน iPhone"""
    if not DISCORD_WEBHOOK_URL:
        print("❌ ไม่พบ DISCORD_WEBHOOK_URL")
        return

    payload = {
        "content": "📢 **มีโพสต์ใหม่จากเพจ นักลงพุง!** @everyone",
        "username": "นักลงพุง Notifier",
        "avatar_url": "https://img.icons8.com/color/512/facebook-new.png",
        "embeds": [
            {
                "title": "🔗 กดเพื่อเปิดอ่านโพสต์บน Facebook",
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
        res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if res.status_code in [200, 204]:
            print("✅ ส่งแจ้งเตือนเข้า Discord สำเร็จ!")
        else:
            print(f"❌ ส่งไม่สำเร็จ: HTTP {res.status_code}")
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการส่ง Discord: {e}")

def get_recent_posts():
    """ดึงข้อมูลโพสต์ย้อนหลัง 5 โพสต์ล่าสุดจากหน้าเพจ"""
    posts_data = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        try:
            page.goto(PAGE_URL, wait_until="networkidle", timeout=35000)
            page.wait_for_timeout(3000)
            
            # เลื่อนหน้าจอลงเพื่อโหลดโพสต์ย้อนหลัง
            page.evaluate("window.scrollBy(0, 1500)")
            page.wait_for_timeout(2000)

            posts = page.locator('div[role="feed"] > div, div[role="article"]')
            count = posts.count()
            
            # กวาดตรวจ 5 โพสต์ล่าสุด
            for i in range(count):
                text = posts.nth(i).inner_text().strip()
                # กรองเอาเฉพาะกล่องที่มีข้อความโพสต์จริง
                if len(text) > 30:
                    post_id = hashlib.md5(text.encode("utf-8")).hexdigest()
                    if post_id not in [p["id"] for p in posts_data]:
                        preview_text = text[:350] + ("..." if len(text) > 350 else "")
                        posts_data.append({
                            "id": post_id,
                            "preview": preview_text,
                            "full_text": text,
                            "url": PAGE_URL
                        })
                if len(posts_data) >= 5:
                    break
        except Exception as e:
            print(f"Scraping Error: {e}")
        finally:
            browser.close()
            
    return posts_data

def main():
    recent_posts = get_recent_posts()
    if not recent_posts:
        print("⚠️ ไม่พบโพสต์ หรือโหลดหน้าเว็บไม่สำเร็จ")
        return

    # 1. โหลดประวัติโพสต์ที่เคยแจ้งเตือนแล้ว
    history_ids = []
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    history_ids = data
                elif isinstance(data, dict) and "full_text" in data:
                    old_id = hashlib.md5(data["full_text"].encode("utf-8")).hexdigest()
                    history_ids = [old_id]
        except Exception:
            history_ids = []

    # 2. ค้นหาโพสต์ใหม่ที่ยังไม่เคยส่ง
    new_posts_found = []
    for post in reversed(recent_posts):  # เรียงจากโพสต์เก่าไปใหม่
        if post["id"] not in history_ids:
            new_posts_found.append(post)

    # 3. ส่งแจ้งเตือนเฉพาะโพสต์ใหม่
    if new_posts_found:
        print(f"🔔 ตรวจพบโพสต์ใหม่ {len(new_posts_found)} โพสต์ กำลังส่งเข้า Discord...")
        for post in new_posts_found:
            send_discord_webhook(content=post["preview"], url=post["url"])
            history_ids.append(post["id"])

        # บันทึกประวัติ 30 โพสต์ล่าสุดลงไฟล์
        history_ids = history_ids[-30:]
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(history_ids, f, ensure_ascii=False, indent=2)
    else:
        print("ℹ️ ไม่มีโพสต์ใหม่ (ทุกโพสต์เคยส่งแจ้งเตือนไปแล้ว)")

if __name__ == "__main__":
    main()
