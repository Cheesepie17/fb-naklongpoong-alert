import os
import re
import json
import hashlib
import requests
from playwright.sync_api import sync_playwright

PAGE_URL = "https://www.facebook.com/naklongpoong"
STORAGE_FILE = "last_post.json"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
AVATAR_URL = "https://media.discordapp.net/attachments/1001883395724415080/1552413471352692907/606397074_122176730570788275_2696545743468565014_n.jpg?ex=6ab58536&is=6ab433b6&hm=1bfaf4ba9e49a50d194f4ea754982091ee51f055c97e54adebf4bec25e83d35f&=&format=webp&width=640&height=640"

def clean_facebook_text(raw_text):
    """ทำความสะอาดข้อความ ลบปุ่มและสถิติต่างๆ ของ Facebook ออก"""
    lines = raw_text.split("\n")
    cleaned_lines = []
    
    garbage_keywords = [
        "นักลงพุง", "like", "comment", "share", "top fan", "see more", 
        "just now", "all reactions", "ผู้ติดตาม", "ถูกใจ", "แชร์", "ความคิดเห็น",
        "ดูเพิ่มเติม", "all reactions:", "เขียนความคิดเห็น...", "write a comment..."
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
        if any(g == lower_line or lower_line.startswith(g) for g in garbage_keywords):
            continue
            
        cleaned_lines.append(stripped)
    
    cleaned_text = "\n\n".join(cleaned_lines)
    cleaned_text = re.sub(r"(\.\.\.)?\s*(See more|ดูเพิ่มเติม)", "", cleaned_text, flags=re.IGNORECASE)
    return cleaned_text.strip()

def send_discord_webhook(content, url, image_url=None):
    if not DISCORD_WEBHOOK_URL:
        print("❌ ไม่พบ DISCORD_WEBHOOK_URL")
        return

    if len(content) > 3800:
        content = content[:3800] + "\n\n...(เนื้อหายาวเกินกำหนด อ่านต่อได้ที่ลิงก์ด้านล่าง)"

    formatted_content = "\n".join([f"> {line}" for line in content.split("\n") if line.strip()])

    embed = {
        "title": "📌 โพสต์จาก นักลงพุง",
        "url": url,
        "description": f"{formatted_content}\n\n🔗 **[กดตรงนี้เพื่อเปิดดูโพสต์บน Facebook]({url})**",
        "color": 1603570,
        "footer": {"text": "เพจ: นักลงพุง"}
    }

    if image_url:
        embed["image"] = {"url": image_url}

    payload = {
        "content": "📢 **โพสต์จากเพจ นักลงพุง!** @everyone",
        "username": "นักลงพุง",
        "avatar_url": AVATAR_URL,
        "embeds": [embed]
    }
    
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if res.status_code in [200, 204]:
            print("✅ ส่งโพสต์เข้า Discord สำเร็จ!")
        else:
            print(f"❌ ส่งไม่สำเร็จ: HTTP {res.status_code}")
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการส่ง Discord: {e}")

def get_recent_posts():
    posts_data = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        page = context.new_page()
        try:
            print("กำลังเปิดหน้าเว็บ Facebook...")
            page.goto(PAGE_URL, wait_until="networkidle", timeout=40000)
            page.wait_for_timeout(3000)
            
            # เลื่อนหน้าจอลง 5 ครั้ง เพื่อโหลดโพสต์ย้อนหลังขึ้นมาให้ครบ
            for scroll_idx in range(5):
                page.evaluate("window.scrollBy(0, 2000)")
                page.wait_for_timeout(1500)

            # กางข้อความ See more ทั้งหมด
            page.evaluate("""
                () => {
                    const elements = document.querySelectorAll('div[role="button"], span');
                    elements.forEach(el => {
                        const txt = (el.innerText || '').trim();
                        if (txt === 'See more' || txt === 'ดูเพิ่มเติม') {
                            el.click();
                        }
                    });
                }
            """)
            page.wait_for_timeout(1500)

            posts = page.locator('div[role="feed"] > div, div[role="article"]')
            count = posts.count()
            print(f"พบโพสต์ทั้งหมด {count} โพสต์ กำลังประมวลผล...")
            
            for i in range(count):
                post_elem = posts.nth(i)
                raw_text = post_elem.inner_text().strip()
                clean_text = clean_facebook_text(raw_text)
                
                if len(clean_text) > 40:
                    post_id = hashlib.md5(clean_text.encode("utf-8")).hexdigest()
                    if post_id not in [p["id"] for p in posts_data]:
                        image_url = None
                        imgs = post_elem.locator('img')
                        for img_idx in range(imgs.count()):
                            src = imgs.nth(img_idx).get_attribute("src")
                            if src and "fbcdn" in src and "emoji" not in src and "rsrc.php" not in src:
                                image_url = src
                                break

                        posts_data.append({
                            "id": post_id,
                            "clean_text": clean_text,
                            "image_url": image_url,
                            "url": PAGE_URL
                        })
                # ดึงสูงสุด 8 โพสต์ย้อนหลัง
                if len(posts_data) >= 8:
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
        print(f"🔔 พบโพสต์ที่ยังไม่ได้ส่ง {len(new_posts_found)} โพสต์ กำลังส่งเข้า Discord...")
        for post in new_posts_found:
            send_discord_webhook(
                content=post["clean_text"], 
                url=post["url"], 
                image_url=post.get("image_url")
            )
            history_ids.append(post["id"])

        # เก็บประวัติ 50 โพสต์
        history_ids = history_ids[-50:]
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(history_ids, f, ensure_ascii=False, indent=2)
    else:
        print("ℹ️ ไม่มีโพสต์ใหม่")

if __name__ == "__main__":
    main()
