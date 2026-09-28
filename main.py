import os
import re
import json
import hashlib
import requests
from playwright.sync_api import sync_playwright

PAGE_NAME = "นักลงพุง"
PAGE_URL = "https://www.facebook.com/naklongpoong"
STORAGE_FILE = "last_post.json"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
FB_COOKIES_RAW = os.environ.get("FB_COOKIES")

def clean_and_deduplicate_text(raw_text):
    lines = raw_text.split("\n")
    cleaned_lines = []
    
    garbage_keywords = [
        "view more comments", "ดูความคิดเห็นเพิ่มเติม", "นักลงพุง",
        "like", "comment", "share", "top fan", "see more", "see less", "just now", "all reactions",
        "ผู้ติดตาม", "ถูกใจ", "แชร์", "ความคิดเห็น", "ดูเพิ่มเติม", "all reactions:",
        "เขียนความคิดเห็น...", "write a comment...", "subscriber", "ผู้ติดตามตัวยง",
        "ดูน้อยลง", "แก้ไขแล้ว"
    ]
    
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "-":
            continue
        lower = stripped.lower()
        if stripped.isdigit():
            continue
        # กรองเวลา เช่น 1 ชม., 5 นาที, Yesterday
        if re.match(r"^(\d+\s*(m|h|d|min|mins|minutes|hours|days|ชม\.|นาที|ชั่วโมง)|about an hour ago|yesterday|เมื่อสักครู่).*$", lower):
            continue
        # ถ้าเริ่มเข้าสู่ส่วนคอมเมนต์ให้หยุดทันที
        if any(c in lower for c in ["view more comments", "ดูความคิดเห็นเพิ่มเติม", "top fan", "subscriber", "ผู้ติดตามตัวยง"]):
            break
        if any(g == lower or lower.startswith(g) for g in garbage_keywords):
            continue
        
        # ป้องกันบรรทัดซ้ำติดกัน
        if not cleaned_lines or cleaned_lines[-1] != stripped:
            cleaned_lines.append(stripped)
            
    full_text = "\n\n".join(cleaned_lines)
    # ลบเศษคำปุ่ม Facebook ที่อาจติดมาท้ายประโยค
    full_text = re.sub(r"(\.\.\.)?\s*(See more|See less|ดูเพิ่มเติม|ดูน้อยลง|แก้ไขแล้ว)", "", full_text, flags=re.IGNORECASE).strip()
    return full_text

def send_discord_webhook(content, url, image_url=None):
    if not DISCORD_WEBHOOK_URL:
        print("[ERROR] ไม่พบค่า DISCORD_WEBHOOK_URL ใน Secrets")
        return False

    # ตัดข้อความหากยาวเกินโควต้า Discord
    if len(content) > 3500:
        content = content[:3500] + "\n\n...(เนื้อหายาวเกินกำหนด อ่านต่อฉบับเต็มได้ที่ลิงก์ด้านล่าง)"

    # ใส่แถบ Quote หน้าข้อความเพื่อความสวยงามและอ่านง่าย
    formatted_content = "\n".join([f"> {line}" for line in content.split("\n") if line.strip()])

    embed = {
        "title": f"📌 โพสต์ใหม่จาก {PAGE_NAME}",
        "url": url,
        "description": f"{formatted_content}\n\n🔗 **[กดตรงนี้เพื่อเปิดดูโพสต์บน Facebook]({url})**",
        "color": 1603570,
        "footer": {"text": f"เพจ: {PAGE_NAME} • อัปเดตล่าสุด"}
    }

    if image_url:
        embed["image"] = {"url": image_url}

    payload = {
        "content": f"📢 **มีโพสต์ใหม่จากเพจ {PAGE_NAME}!** @everyone",
        "username": PAGE_NAME,
        "embeds": [embed]
    }
    
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if res.status_code in [200, 204]:
            print(f"[SUCCESS] แจ้งเตือนเข้า Discord สำเร็จ: {content[:35]}...")
            return True
        else:
            print(f"[FAILED] ส่ง Discord ไม่สำเร็จ: HTTP {res.status_code}")
            return False
    except Exception as e:
        print(f"[ERROR] เกิดข้อผิดพลาดในการยิง Discord: {e}")
        return False

def get_recent_posts():
    collected_posts = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        
        # ใส่ Cookies ถ้ามีตั้งไว้ใน GitHub Secrets
        if FB_COOKIES_RAW:
            try:
                cookies = json.loads(FB_COOKIES_RAW)
                context.add_cookies(cookies)
                print("[INFO] โหลด Facebook Cookies เข้าสู่ระบบสำเร็จ")
            except Exception as e:
                print(f"[WARNING] แปลงค่า Cookies ไม่สำเร็จ: {e}")

        page = context.new_page()

        try:
            print(f"[INFO] กำลังเปิดหน้าเพจ: {PAGE_URL}")
            page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4000)

            # กวาดข้อมูล 5 รอบ เพื่อให้ได้โพสต์ครบถ้วน
            for step in range(5):
                extracted = page.evaluate("""
                    () => {
                        // ปิดป๊อปอัปบังจอ
                        document.querySelectorAll('div[role="dialog"]').forEach(el => el.remove());
                        
                        // กดปุ่ม 'ดูเพิ่มเติม' / 'See more'
                        document.querySelectorAll('div[role="button"], span').forEach(el => {
                            const txt = (el.innerText || '').trim();
                            if (txt === 'See more' || txt === 'ดูเพิ่มเติม') {
                                try { el.click(); } catch(e) {}
                            }
                        });

                        const results = [];
                        const feed = document.querySelector('div[role="feed"]') || document.body;
                        const articles = feed.querySelectorAll('div[role="article"], div[data-pagelet^="FeedUnit"]');

                        articles.forEach(art => {
                            if (art.parentElement.closest('div[role="article"]')) return;

                            const clone = art.cloneNode(true);
                            // ลบส่วนกล่องพิมพ์คอมเมนต์และปุ่มต่างๆ
                            clone.querySelectorAll('form, ul, ol, [role="toolbar"], button, [aria-label*="Comment"], [aria-label*="ความคิดเห็น"], [aria-label*="ตอบกลับ"], [aria-label*="Reply"], [aria-label*="reactions"]').forEach(trash => trash.remove());

                            let text = '';
                            const msgNode = clone.querySelector('div[data-ad-preview="message"], div[data-ad-comet-preview="message"]');
                            if (msgNode) {
                                text = msgNode.innerText.trim();
                            } else {
                                // เลือกเฉพาะ div ข้อความชั้นนอกสุด ป้องกันข้อความซ้ำ
                                const textNodes = Array.from(clone.querySelectorAll('div[dir="auto"], span[dir="auto"]'))
                                    .filter(node => !node.parentElement.closest('div[dir="auto"]'))
                                    .map(n => n.innerText.trim())
                                    .filter(t => t.length > 5);
                                text = textNodes.join('\\n\\n');
                            }

                            // ค้นหารูปภาพประกอบโพสต์
                            let imgUrl = null;
                            const img = art.querySelector('img[src*="fbcdn"]');
                            if (img && !img.src.includes('emoji') && !img.src.includes('rsrc.php') && !img.src.includes('static')) {
                                imgUrl = img.src;
                            }

                            if (text && text.length > 10) {
                                results.push({ text: text, img: imgUrl });
                            }
                        });

                        return results;
                    }
                """)

                for item in extracted:
                    clean_text = clean_and_deduplicate_text(item["text"])
                    if not clean_text or len(clean_text) < 10:
                        continue
                        
                    post_id = hashlib.md5(clean_text.encode("utf-8")).hexdigest()
                    if post_id not in collected_posts:
                        collected_posts[post_id] = {
                            "id": post_id,
                            "clean_text": clean_text,
                            "image_url": item["img"],
                            "url": PAGE_URL
                        }

                page.mouse.wheel(0, 1800)
                page.keyboard.press("PageDown")
                page.wait_for_timeout(2000)

                if len(collected_posts) >= 15:
                    break

        except Exception as e:
            print(f"[ERROR] เกิดข้อผิดพลาดระหว่างดึงข้อมูล: {e}")
        finally:
            context.close()
            browser.close()
            
    return list(collected_posts.values())

def main():
    recent_posts = get_recent_posts()
    if not recent_posts:
        print("[WARNING] ไม่พบโพสต์ใหม่ หรือ Facebook บล็อกการเข้าถึง")
        return

    print(f"[INFO] ตรวจพบโพสต์ทั้งหมดในหน้าเพจ: {len(recent_posts)} โพสต์")

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

    # ตรวจสอบหาโพสต์ใหม่ (เรียงจากเก่าไปใหม่ เพื่อให้แจ้งเตือนตามลำดับเวลา)
    new_posts_found = []
    for post in reversed(recent_posts):
        if post["id"] not in history_ids:
            new_posts_found.append(post)

    if new_posts_found:
        print(f"[INFO] พบ {len(new_posts_found)} โพสต์ใหม่ กำลังส่งเข้า Discord...")
        for post in new_posts_found:
            send_discord_webhook(
                content=post["clean_text"], 
                url=post["url"], 
                image_url=post.get("image_url")
            )
            history_ids.append(post["id"])

        # เก็บประวัติล่าสุด 200 รายการ
        history_ids = history_ids[-200:]
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(history_ids, f, ensure_ascii=False, indent=2)
            
        print("[INFO] บันทึกประวัติโพสต์ลงไฟล์ last_post.json สำเร็จ")
    else:
        print("[INFO] ไม่มีโพสต์ใหม่ (ส่งแจ้งเตือนไปครบหมดแล้ว)")

if __name__ == "__main__":
    main()
