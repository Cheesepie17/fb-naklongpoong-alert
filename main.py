import os
import re
import json
import hashlib
import requests
from playwright.sync_api import sync_playwright

PAGE_URL = "https://www.facebook.com/naklongpoong"
STORAGE_FILE = "last_post.json"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

def send_discord_webhook(content, url, image_url=None):
    if not DISCORD_WEBHOOK_URL:
        print("❌ ไม่พบ DISCORD_WEBHOOK_URL")
        return

    if len(content) > 3800:
        content = content[:3800] + "\n\n...(เนื้อหายาวเกินกำหนด อ่านต่อได้ที่ลิงก์ด้านล่าง)"

    formatted_content = "\n".join([f"> {line}" for line in content.split("\n") if line.strip()])

    embed = {
        "title": "📌 โพสต์ใหม่จาก นักลงพุง",
        "url": url,
        "description": f"{formatted_content}\n\n🔗 **[กดตรงนี้เพื่อเปิดดูโพสต์บน Facebook]({url})**",
        "color": 1603570,
        "footer": {"text": "เพจ: นักลงพุง • อัปเดตล่าสุด"}
    }

    if image_url:
        embed["image"] = {"url": image_url}

    payload = {
        "content": "📢 **มีโพสต์ใหม่จากเพจ นักลงพุง!** @everyone",
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

def get_recent_posts():
    collected_posts = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000}
        )
        page = context.new_page()
        try:
            print("กำลังเปิดหน้าเพจ Facebook...")
            page.goto(PAGE_URL, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(3000)

            for step in range(8):
                # สั่ง JavaScript สกัดเฉพาะเนื้อหาโพสต์แท้ๆ และตัดคอมเมนต์ทิ้งทั้งหมดที่ระดับ DOM
                extracted = page.evaluate("""
                    () => {
                        // 1. ปิด Popup และกาง See more
                        document.querySelectorAll('div[role="dialog"]').forEach(el => el.remove());
                        document.querySelectorAll('div[role="button"], span').forEach(el => {
                            const txt = (el.innerText || '').trim();
                            if (txt === 'See more' || txt === 'ดูเพิ่มเติม') el.click();
                        });

                        const results = [];
                        const feed = document.querySelector('div[role="feed"]') || document.body;
                        const articles = feed.querySelectorAll('div[role="article"], div[data-pagelet^="FeedUnit"]');

                        articles.forEach(art => {
                            // ข้าม article ที่เป็นคอมเมนต์ซ้อนอยู่ข้างใน
                            if (art.parentElement.closest('div[role="article"]')) return;

                            // โคลน Element เพื่อตัดขยะทิ้งโดยไม่กระทบหน้าเว็บจริง
                            const clone = art.cloneNode(true);
                            
                            // ลบส่วนคอมเมนต์, ฟอร์มตอบกลับ, เมนูปุ่ม, ทูลบาร์ ทิ้งทั้งหมด 100%
                            clone.querySelectorAll('form, ul, ol, [role="toolbar"], button, [aria-label*="Comment"], [aria-label*="ความคิดเห็น"], [aria-label*="ตอบกลับ"], [aria-label*="Reply"], [aria-label*="reactions"]').forEach(trash => trash.remove());

                            // เจาะจงดึงเฉพาะกล่องข้อความของเจ้าของโพสต์
                            let text = '';
                            const msgNode = clone.querySelector('div[data-ad-preview="message"], div[data-ad-comet-preview="message"]');
                            if (msgNode) {
                                text = msgNode.innerText.trim();
                            } else {
                                // กรณีไม่มี tag data-ad-preview ให้ดึง dir="auto" ที่อยู่ส่วนบนก่อนถึงรูป
                                const textNodes = Array.from(clone.querySelectorAll('div[dir="auto"], span[dir="auto"]'))
                                    .map(n => n.innerText.trim())
                                    .filter(t => t.length > 10 && !t.includes('นักลงพุง') && !t.includes('ถูกใจ') && !t.includes('แชร์'));
                                text = textNodes.join('\\n\\n');
                            }

                            // ลบคำตกค้าง เช่น See more
                            text = text.replace(/(\\.\\.\\.)?\\s*(See more|See less|ดูเพิ่มเติม)/gi, '').trim();

                            // ดึงรูปภาพประกอบโพสต์
                            let imgUrl = null;
                            const img = art.querySelector('img[src*="fbcdn"]');
                            if (img && !img.src.includes('emoji') && !img.src.includes('rsrc.php') && !img.src.includes('static')) {
                                imgUrl = img.src;
                            }

                            if (text && text.length > 15) {
                                results.push({ text: text, img: imgUrl });
                            }
                        });

                        return results;
                    }
                """)

                # นำโพสต์ที่สกัดได้แบบคลีนๆ มาบันทึก
                for item in extracted:
                    clean_text = item["text"]
                    post_id = hashlib.md5(clean_text.encode("utf-8")).hexdigest()
                    if post_id not in collected_posts:
                        collected_posts[post_id] = {
                            "id": post_id,
                            "clean_text": clean_text,
                            "image_url": item["img"],
                            "url": PAGE_URL
                        }

                print(f"📍 สเต็ปที่ {step+1}: กวาดพบสะสมแล้ว {len(collected_posts)} โพสต์")

                # เลื่อนหน้าจอลงเพื่อโหลดโพสต์ถัดไป
                page.mouse.wheel(0, 2500)
                page.keyboard.press("PageDown")
                page.wait_for_timeout(2000)

                if len(collected_posts) >= 20:
                    break

        except Exception as e:
            print(f"Scraping Error: {e}")
        finally:
            browser.close()
            
    return list(collected_posts.values())

def main():
    recent_posts = get_recent_posts()
    if not recent_posts:
        print("⚠️ ไม่พบโพสต์ หรือโหลดหน้าเว็บไม่สำเร็จ")
        return

    print(f"📊 สรุปกวาดพบโพสต์ที่คลีนแล้ว: {len(recent_posts)} โพสต์")

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
                image_url=post.get("image_url")
            )
            history_ids.append(post["id"])

        history_ids = history_ids[-200:]
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(history_ids, f, ensure_ascii=False, indent=2)
            
        print("💾 บันทึกประวัติสำเร็จ!")
    else:
        print("ℹ️ ไม่มีโพสต์ใหม่ (ส่งครบหมดแล้ว)")

if __name__ == "__main__":
    main()
