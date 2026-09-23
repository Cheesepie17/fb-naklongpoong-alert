import os
import re
import json
import hashlib
import requests
from playwright.sync_api import sync_playwright

PAGE_URL = "https://www.facebook.com/naklongpoong"
STORAGE_FILE = "last_post.json"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

def clean_facebook_text(raw_text):
    """ทำความสะอาดข้อความ ลบปุ่มและสถิติต่างๆ ของ Facebook ออก"""
    lines = raw_text.split("\n")
    cleaned_lines = []
    
    garbage_keywords = [
        "นักลงพุง", "like", "comment", "share", "top fan", "see more", 
        "just now", "all reactions", "ผู้ติดตาม", "ถูกใจ", "แชร์", "ความคิดเห็น"
    ]
    
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "-":
            continue
        
        lower_line = stripped.lower()
        
        if stripped.isdigit():
            continue
            
        if re.match(r"^\d+\s*(m|h|d|min|mins|minutes|hours|days|ชม\.|นาที).*$", lower_line):
            continue
            
        if any(g == lower_line for g in garbage_keywords):
            continue
            
        cleaned_lines.append(stripped)
    
    cleaned_text = "\n\n".join(cleaned_lines)
    cleaned_text = re.sub(r"\.\.\.\s*(See more|ดูเพิ่มเติม)", "...", cleaned_text, flags=re.IGNORECASE)
    return cleaned_text.strip()

def send_discord_webhook(content, url):
    """ส่งข้อความรูปแบบ Embed ที่ปรับแต่งให้อ่านง่ายบนธีมสีขาว (Light Mode)"""
    if not DISCORD_WEBHOOK_URL:
        print("❌ ไม่พบ DISCORD_WEBHOOK_URL")
        return

    # จัดย่อหน้าข้อความให้อ่านง่ายในกล่อง Blockquote
    preview = content[:400]
    formatted_content = "\n".join([f"> {line}" for line in preview.split("\n") if line.strip()])
    
    if len(content) > 400:
        formatted_content += "\n> \n> *(... มีเนื้อหาต่อ)*"

    payload = {
        "content": "📢 **มีโพสต์ใหม่จากเพจ นักลงพุง!** @everyone",
        "username": "นักลงพุง Feed",
        "avatar_url": "https://img.icons8.com/color/512/facebook-new.png",
        "embeds": [
            {
                "title": "📌 สรุปเนื้อหาโพสต์ล่าสุด",
                "url": url,
                "description": f"{formatted_content}\n\n🔗 **[กดตรงนี้เพื่อเปิดดูโพสต์เต็มบน Facebook]({url})**",
                "color": 1603570,  # Facebook Blue (#1877F2) คมชัดที่สุดบนพื้นหลังสีขาว
                "footer": {
                    "text": "เพจ: นักลงพุง • อัปเดตล่าสุด"
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
    """ดึงข้อมูลโพสต์และทำความสะอาดเนื้อหา"""
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
            
            page.evaluate("window.scrollBy(0, 1500)")
            page.wait_for_timeout(2000)

            posts = page.locator('div[role="feed"] > div, div[role="article"]')
            count = posts.count()
            
            for i in range(count):
                raw_text = posts.nth(i).inner_text().strip()
                clean_text = clean_facebook_text(raw_text)
                
                if len(clean_text) > 30:
                    post_id = hashlib.md5(clean_text.encode("utf-8")).hexdigest()
                    if post_id not in [p["id"] for p in posts_data]:
                        posts_data.append({
                            "id": post_id,
                            "clean_text": clean_text,
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

    new_posts_found = []
    for post in reversed(recent_posts):
        if post["id"] not in history_ids:
            new_posts_found.append(post)

    if new_posts_found:
        print(f"🔔 ตรวจพบโพสต์ใหม่ {len(new_posts_found)} โพสต์ กำลังส่งเข้า Discord...")
        for post in new_posts_found:
            send_discord_webhook(content=post["clean_text"], url=post["url"])
            history_ids.append(post["id"])

        history_ids = history_ids[-30:]
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(history_ids, f, ensure_ascii=False, indent=2)
    else:
        print("ℹ️ ไม่มีโพสต์ใหม่")

if __name__ == "__main__":
    main()
