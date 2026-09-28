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
    raw_text = re.sub(r"(\.\.\.)?\s*(See more|See less|ดูเพิ่มเติม|ดูน้อยลง|แก้ไขแล้ว)", "", raw_text, flags=re.IGNORECASE)
    
    lines = [line.strip() for line in raw_text.split("\n") if line.strip() and line.strip() != "-"]
    garbage_keywords = [
        "view more comments", "ดูความคิดเห็นเพิ่มเติม", PAGE_NAME.lower(),
        "like", "comment", "share", "top fan", "see more", "see less", "just now", "all reactions",
        "ผู้ติดตาม", "ถูกใจ", "แชร์", "ความคิดเห็น", "ดูเพิ่มเติม", "all reactions:",
        "เขียนความคิดเห็น...", "write a comment...", "subscriber", "ผู้ติดตามตัวยง",
        "ดูน้อยลง", "แก้ไขแล้ว"
    ]
    
    cleaned_lines = []
    for line in lines:
        lower = line.lower()
        if line.isdigit():
            continue
        if re.match(r"^(\d+\s*(m|h|d|min|mins|minutes|hours|days|ชม\.|นาที|ชั่วโมง)|about an hour ago|yesterday|เมื่อสักครู่).*$", lower):
            continue
        if any(c in lower for c in ["view more comments", "ดูความคิดเห็นเพิ่มเติม", "top fan", "subscriber", "ผู้ติดตามตัวยง"]):
            break
        if any(g == lower or lower.startswith(g) for g in garbage_keywords):
            continue
        
        if not cleaned_lines:
            cleaned_lines.append(line)
        else:
            if line == cleaned_lines[-1] or line in cleaned_lines[-1]:
                continue
            if cleaned_lines[-1] in line:
                cleaned_lines[-1] = line
            else:
                cleaned_lines.append(line)
                
    full_text = "\n\n".join(cleaned_lines)
    
    # ตรวจสอบหากข้อความเบิ้ลซ้ำ 2 ท่อนเหมือนกันเป๊ะ (A + A)
    half = len(full_text) // 2
    if half > 15:
        first_half = full_text[:half].strip()
        second_half = full_text[half:].strip()
        if first_half == second_half:
            full_text = first_half

    return full_text.strip()

def send_discord_webhook(content, url, image_url=None):
    if not DISCORD_WEBHOOK_URL:
        print("[ERROR] ไม่พบค่า DISCORD_WEBHOOK_URL ใน Secrets")
        return False

    if len(content) > 3500:
        content = content[:3500] + "\n\n...(เนื้อหายาวเกินกำหนด อ่านต่อฉบับเต็มได้ที่ลิงก์ด้านล่าง)"

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

            for step in range(5):
                page.evaluate("""() => {
                    document.querySelectorAll('div[role="button"], span').forEach(el => {
                        const txt = (el.innerText || '').trim();
                        if (txt === 'See more' || txt === 'ดูเพิ่มเติม') {
                            try { el.click(); } catch(e) {}
                        }
                    });
                }""")
                page.wait_for_timeout(1500)

                extracted = page.evaluate("""
                    () => {
                        document.querySelectorAll('div[role="dialog"]').forEach(el => el.remove());
                        const feed = document.querySelector('div[role="feed"]') || document.body;
                        
                        // เลือกเฉพาะการ์ดโพสต์ชั้นนอกสุด ไม่เอาการ์ดคอมเมนต์
                        const articles = Array.from(feed.querySelectorAll('div[role="article"], div[data-pagelet^="FeedUnit"]'))
                            .filter(el => !el.parentElement.closest('div[role="article"]'));
                        
                        const results = [];
                        articles.forEach(art => {
                            const clone = art.cloneNode(true);
                            clone.querySelectorAll('form, ul, ol, [role="toolbar"], button, [aria-label*="Comment"], [aria-label*="ความคิดเห็น"], [aria-label*="ตอบกลับ"], [aria-label*="Reply"], [aria-label*="reactions"]').forEach(trash => trash.remove());

                            let msgEl = clone.querySelector('div[data-ad-rendering-role="story_message"]') ||
                                        clone.querySelector('div[data-ad-preview="message"]') ||
                                        clone.querySelector('div[data-ad-comet-preview="message"]');
                            
                            let text = '';
                            if (msgEl) {
                                text = msgEl.innerText.trim();
                            } else {
                                const rawBlocks = Array.from(clone.querySelectorAll('div[dir="auto"]'))
                                    .map(n => n.innerText.trim())
                                    .filter(t => t.length > 5 && !t.includes('ถูกใจ') && !t.includes('แชร์'));
                                
                                const uniqueBlocks = rawBlocks.filter((block, idx) => {
                                    return !rawBlocks.some((other, otherIdx) => otherIdx !== idx && other.includes(block) && other.length > block.length);
                                });
                                text = uniqueBlocks.join('\\n\\n');
                            }

                            // ค้นหารูปภาพโพสต์จริง (ข้ามอิโมจิ)
                            let imgUrl = null;
                            const allImgs = Array.from(art.querySelectorAll('img'));
                            for (const img of allImgs) {
                                const src = img.src || '';
                                if (!src || src.startsWith('data:')) continue;
                                if (src.includes('emoji') || src.includes('rsrc.php') || src.includes('static.xx.fbcdn') || src.includes('/rsrc/')) continue;
                                
                                const w = img.naturalWidth || img.width || 0;
                                const h = img.naturalHeight || img.height || 0;
                                const isPhoto = img.closest('a') && (img.closest('a').href.includes('/photo') || img.closest('a').href.includes('/photos'));
                                
                                if (isPhoto || (src.includes('fbcdn') && (w > 80 || h > 80 || w === 0))) {
                                    imgUrl = src;
                                    break;
                                }
                            }

                            let postLink = null;
                            const linkNode = art.querySelector('a[href*="/posts/"], a[href*="/photo/"], a[href*="/photos/"], a[href*="permalink"]');
                            if (linkNode && linkNode.href) {
                                postLink = linkNode.href.split('?')[0];
                            }

                            if (text && text.length > 10) {
                                results.push({ text: text, img: imgUrl, link: postLink });
                            }
                        });
                        return results;
                    }
                """)

                for item in extracted:
                    clean_text = clean_and_deduplicate_text(item["text"])
                    if not clean_text or len(clean_text) < 10:
                        continue
                    
                    # สร้าง Hash ที่แม่นยำจากหัวข้อ 50 ตัวอักษรแรก
                    clean_signature = re.sub(r"[^\w\dก-๙]+", "", clean_text)[:50]
                    post_id = hashlib.md5(clean_signature.encode("utf-8")).hexdigest()

                    if post_id in collected_posts:
                        if len(clean_text) > len(collected_posts[post_id]["clean_text"]):
                            collected_posts[post_id]["clean_text"] = clean_text
                        if item["img"] and not collected_posts[post_id].get("image_url"):
                            collected_posts[post_id]["image_url"] = item["img"]
                    else:
                        collected_posts[post_id] = {
                            "id": post_id,
                            "clean_text": clean_text,
                            "image_url": item["img"],
                            "url": item.get("link") or PAGE_URL
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

        history_ids = history_ids[-200:]
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(history_ids, f, ensure_ascii=False, indent=2)
            
        print("[INFO] บันทึกประวัติโพสต์ลงไฟล์ last_post.json สำเร็จ")
    else:
        print("[INFO] ไม่มีโพสต์ใหม่ (ส่งแจ้งเตือนไปครบหมดแล้ว)")

if __name__ == "__main__":
    main()
