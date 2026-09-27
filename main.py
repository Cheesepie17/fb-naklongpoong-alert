import os
import re
import json
import hashlib
import requests
from playwright.sync_api import sync_playwright

PAGE_URL = "https://www.facebook.com/naklongpoong"
STORAGE_FILE = "last_post.json"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
FB_COOKIES_RAW = os.environ.get("FB_COOKIES")

def clean_and_deduplicate_text(raw_text):
    """ทำความสะอาดข้อความ ลบคำขยะ และตัดย่อหน้าที่เบิ้ลซ้ำออก 100%"""
    lines = raw_text.split("\n")
    cleaned_lines = []
    
    garbage_keywords = [
        "view more comments", "ดูความคิดเห็นเพิ่มเติม", "นักลงพุง", "like", "comment",
        "share", "top fan", "see more", "see less", "just now", "all reactions",
        "ผู้ติดตาม", "ถูกใจ", "แชร์", "ความคิดเห็น", "ดูเพิ่มเติม", "all reactions:",
        "เขียนความคิดเห็น...", "write a comment...", "subscriber", "ผู้ติดตามตัวยง"
    ]
    
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "-":
            continue
        
        lower = stripped.lower()
        if stripped.isdigit():
            continue
            
        # ตัดบรรทัดเวลา
        if re.match(r"^(\d+\s*(m|h|d|min|mins|minutes|hours|days|ชม\.|นาที|ชั่วโมง)|about an hour ago|yesterday|เมื่อสักครู่).*$", lower):
            continue
            
        # ถ้าเจอปุ่มคอมเมนต์ให้หยุดตัดส่วนล่างทิ้งทั้งหมด
        if any(g in lower for g in ["view more comments", "ดูความคิดเห็นเพิ่มเติม", "top fan", "subscriber", "ผู้ติดตามตัวยง"]):
            break
            
        # ตัดคำขยะเดี่ยวๆ
        if any(g == lower for g in garbage_keywords):
            continue
            
        cleaned_lines.append(stripped)

    # รวมเป็นข้อความ
    full_text = "\n\n".join(cleaned_lines)
    full_text = re.sub(r"(\.\.\.)?\s*(See more|See less|ดูเพิ่มเติม)", "", full_text, flags=re.IGNORECASE).strip()

    # --- ระบบตัดย่อหน้าและประโยคที่เบิ้ลซ้ำ (Deduplication) ---
    paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
    unique_paragraphs = []
    for p in paragraphs:
        if p not in unique_paragraphs:
            unique_paragraphs.append(p)
            
    result = "\n\n".join(unique_paragraphs).strip()
    
    # กรณีข้อความยาวท่อนแรกซ้ำกับท่อนหลังเป๊ะๆ (เช่น duplicate จาก DOM)
    half_len = len(result) // 2
    if half_len > 30 and result[:half_len].strip() == result[half_len:].strip():
        result = result[:half_len].strip()
        
    return result

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

        if FB_COOKIES_RAW:
            try:
                cookies = json.loads(FB_COOKIES_RAW)
                context.add_cookies(cookies)
                print("🔑 ใส่ Cookies การล็อกอิน Facebook สำเร็จ!")
            except Exception as e:
                print(f"⚠️ ใส่ Cookies ไม่สำเร็จ: {e}")

        page = context.new_page()
        try:
            print("กำลังเปิดหน้าเพจ Facebook...")
            page.goto(PAGE_URL, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(3000)

            for step in range(8):
                # สกัดข้อความเฉพาะจุด ไม่ดึงแท็กลูกซ้ำซ้อน
                extracted = page.evaluate("""
                    () => {
                        document.querySelectorAll('div[role="dialog"]').forEach(el => el.remove());
                        document.querySelectorAll('div[role="button"], span').forEach(el => {
                            const txt = (el.innerText || '').trim();
                            if (txt === 'See more' || txt === 'ดูเพิ่มเติม') el.click();
                        });

                        const results = [];
                        const feed = document.querySelector('div[role="feed"]') || document.body;
                        const articles = feed.querySelectorAll('div[role="article"], div[data-pagelet^="FeedUnit"]');

                        articles.forEach(art => {
                            if (art.parentElement.closest('div[role="article"]')) return;

                            const clone = art.cloneNode(true);
                            clone.querySelectorAll('form, ul, ol, [role="toolbar"], button, [aria-label*="Comment"], [aria-label*="ความคิดเห็น"], [aria-label*="ตอบกลับ"], [aria-label*="Reply"], [aria-label*="reactions"]').forEach(trash => trash.remove());

                            let text = '';
                            const msgNode = clone.querySelector('div[data-ad-preview="message"], div[data-ad-comet-preview="message"]');
                            if (msgNode) {
                                text = msgNode.innerText.trim();
                            } else {
                                // ดึงเฉพาะ container ข้อความหลัก ไม่ดึงแท็กลูกทั้งหมด
                                const textBlocks = [];
                                const dirNodes = clone.querySelectorAll('div[dir="auto"]');
                                dirNodes.forEach(node => {
                                    // ข้ามถ้าเป็น child ของ div[dir="auto"] อื่นเพื่อกันข้อความเบิ้ล
                                    if (!node.parentElement.closest('div[dir="auto"]')) {
                                        const t = node.innerText.trim();
                                        if (t.length > 10 && !t.includes('นักลงพุง') && !t.includes('ถูกใจ') && !t.includes('แชร์')) {
                                            textBlocks.push(t);
                                        }
                                    }
                                });
                                text = textBlocks.join('\\n\\n');
                            }

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

                for item in extracted:
                    clean_text = clean_and_deduplicate_text(item["text"])
                    if len(clean_text) > 15:
                        # สร้าง ID จากข้อความ 80 ตัวอักษรแรก เพื่อความเสถียรไม่ให้ส่งซ้ำ
                        clean_signature = re.sub(r"\s+", "", clean_text[:80])
                        post_id = hashlib.md5(clean_signature.encode("utf-8")).hexdigest()
                        
                        if post_id not in collected_posts:
                            collected_posts[post_id] = {
                                "id": post_id,
                                "clean_text": clean_text,
                                "image_url": item["img"],
                                "url": PAGE_URL
                            }

                print(f"📍 สเต็ปที่ {step+1}: กวาดพบสะสม {len(collected_posts)} โพสต์")

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
        print(f"🔔 ตรวจพบโพสต์ใหม่ {len(new_posts_found)} โพสต์ กำลังส่งเข้า Discord...")
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
