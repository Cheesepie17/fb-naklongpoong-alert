import os
import re
import json
import hashlib
import requests
from playwright.sync_api import sync_playwright

PAGE_URL = "https://www.facebook.com/naklongpoong"
STORAGE_FILE = "last_post.json"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
RUN_MODE = os.environ.get("RUN_MODE", "normal").strip().lower()

def is_yesterday_post(raw_text):
    lower = raw_text.lower()
    keywords = ["yesterday", "เมื่อวาน", "1 d", "1d", "1 day", "24h", "20h", "21h", "22h", "23h"]
    return any(k in lower for k in keywords)

def clean_facebook_text(raw_text):
    """ทำความสะอาดข้อความ ลบปุ่ม สถิติ และคอมเมนต์ของลูกเพจออก"""
    lines = raw_text.split("\n")
    cleaned_lines = []
    
    garbage_exact = [
        "นักลงพุง", "like", "comment", "share", "top fan", "see more", "see less",
        "just now", "all reactions", "ผู้ติดตาม", "ถูกใจ", "แชร์", "ความคิดเห็น",
        "ดูเพิ่มเติม", "all reactions:", "เขียนความคิดเห็น...", "write a comment...",
        "view more comments", "ดูความคิดเห็นเพิ่มเติม", "subscriber", "ผู้ติดตามตัวยง"
    ]
    
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "-":
            continue
        
        lower = stripped.lower()
        if stripped.isdigit():
            continue
        if re.match(r"^(\d+\s*(m|h|d|min|mins|minutes|hours|days|ชม\.|นาที)|about an hour ago|yesterday|เมื่อสักครู่).*$", lower):
            continue
        # ถ้าเจอกล่องเริ่มคอมเมนต์ ให้ตัดส่วนล่างทิ้งทั้งหมด
        if any(c in lower for c in ["view more comments", "ดูความคิดเห็นเพิ่มเติม", "top fan", "subscriber", "ผู้ติดตามตัวยง"]):
            break
        if any(g == lower or lower.startswith(g) for g in garbage_exact):
            continue
            
        cleaned_lines.append(stripped)
    
    cleaned_text = "\n\n".join(cleaned_lines)
    cleaned_text = re.sub(r"(\.\.\.)?\s*(See more|See less|ดูเพิ่มเติม)", "", cleaned_text, flags=re.IGNORECASE)
    return cleaned_text.strip()

def send_discord_webhook(content, url, image_url=None, title="📌 โพสต์จาก นักลงพุง"):
    if not DISCORD_WEBHOOK_URL:
        print("❌ ไม่พบ DISCORD_WEBHOOK_URL")
        return

    if len(content) > 3800:
        content = content[:3800] + "\n\n...(เนื้อหายาวเกินกำหนด อ่านต่อได้ที่ลิงก์ด้านล่าง)"

    formatted_content = "\n".join([f"> {line}" for line in content.split("\n") if line.strip()])

    embed = {
        "title": title,
        "url": url,
        "description": f"{formatted_content}\n\n🔗 **[กดตรงนี้เพื่อเปิดดูโพสต์บน Facebook]({url})**",
        "color": 1603570,  # สีน้ำเงิน Facebook คมชัดบนพื้นขาว
        "footer": {"text": "เพจ: นักลงพุง • อัปเดตล่าสุด"}
    }

    if image_url:
        embed["image"] = {"url": image_url}

    payload = {
        "content": f"📢 **{title}!** @everyone",
        "username": "นักลงพุง",
        "embeds": [embed]
    }
    
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if res.status_code in [200, 204]:
            print(f"✅ ส่งโพสต์เข้า Discord สำเร็จ: {content[:30]}...")
        else:
            print(f"❌ ส่งไม่สำเร็จ: HTTP {res.status_code}")
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการส่ง Discord: {e}")

def get_recent_posts(mode="normal"):
    """กวาดเก็บโพสต์แบบสดๆ ทุกรอบที่เลื่อนหน้าจอ (Progressive Scraping)"""
    collected_posts = {}
    scroll_steps = 12 if mode == "yesterday" else 7
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000}
        )
        page = context.new_page()
        try:
            print(f"กำลังเปิดหน้าเพจ Facebook (โหมด: {mode})...")
            page.goto(PAGE_URL, wait_until="networkidle", timeout=40000)
            page.wait_for_timeout(3000)

            for step in range(scroll_steps):
                # 1. ปิดป๊อปอัป Login ถ้ามีโผล่มาบัง
                try:
                    close_btn = page.locator('div[aria-label="Close"], div[aria-label="ปิด"], div[role="dialog"] div[role="button"]')
                    if close_btn.count() > 0:
                        close_btn.first.click(timeout=1000)
                except Exception:
                    pass

                # 2. กางปุ่ม See more เพื่อดึงข้อความเต็ม
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
                page.wait_for_timeout(1000)

                # 3. กวาดเก็บโพสต์ในหน้าจอปัจจุบัน
                posts = page.locator('div[role="feed"] > div, div[role="article"]')
                count = posts.count()
                
                for i in range(count):
                    post_elem = posts.nth(i)
                    raw_text = post_elem.inner_text().strip()
                    
                    if mode == "yesterday" and not is_yesterday_post(raw_text):
                        continue

                    clean_text = clean_facebook_text(raw_text)
                    if len(clean_text) > 40:
                        post_id = hashlib.md5(clean_text.encode("utf-8")).hexdigest()
                        if post_id not in collected_posts:
                            image_url = None
                            imgs = post_elem.locator('img')
                            for img_idx in range(imgs.count()):
                                src = imgs.nth(img_idx).get_attribute("src")
                                if src and "fbcdn" in src and "emoji" not in src and "rsrc.php" not in src:
                                    image_url = src
                                    break

                            collected_posts[post_id] = {
                                "id": post_id,
                                "clean_text": clean_text,
                                "image_url": image_url,
                                "url": PAGE_URL
                            }

                # 4. เลื่อนจอลงเพื่อกวาดเพิ่ม
                page.evaluate("window.scrollBy(0, 1800)")
                page.wait_for_timeout(1500)

        except Exception as e:
            print(f"Scraping Error: {e}")
        finally:
            browser.close()
            
    return list(collected_posts.values())

def main():
    recent_posts = get_recent_posts(mode=RUN_MODE)
    if not recent_posts:
        print("⚠️ ไม่พบโพสต์ หรือโหลดหน้าเว็บไม่สำเร็จ")
        return

    print(f"📊 สรุปกวาดพบโพสต์ทั้งหมด: {len(recent_posts)} โพสต์")

    # โหมดดึงเมื่อวาน
    if RUN_MODE == "yesterday":
        print("📅 กำลังส่งโพสต์ของเมื่อวานเข้า Discord...")
        for post in reversed(recent_posts):
            send_discord_webhook(
                content=post["clean_text"],
                url=post["url"],
                image_url=post.get("image_url"),
                title="📅 [ย้อนหลังเมื่อวาน] โพสต์จาก นักลงพุง"
            )
        return

    # โหมดปกติตรวจจับอัตโนมัติ
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
        print(f"🔔 ตรวจพบโพสต์ใหม่ที่ยังไม่ได้ส่ง {len(new_posts_found)} โพสต์ กำลังส่งเข้า Discord...")
        for post in new_posts_found:
            send_discord_webhook(
                content=post["clean_text"], 
                url=post["url"], 
                image_url=post.get("image_url"),
                title="📌 มีโพสต์ใหม่จากเพจ นักลงพุง"
            )
            history_ids.append(post["id"])

        history_ids = history_ids[-100:]
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(history_ids, f, ensure_ascii=False, indent=2)
    else:
        print("ℹ️ ไม่มีโพสต์ใหม่")

if __name__ == "__main__":
    main()
