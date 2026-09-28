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
        "view more comments", "ดูความคิดเห็นเพิ่มเติม", "นักลงพุง", "like", "comment",
        "share", "top fan", "see more", "see less", "just now", "all reactions",
        "ผู้ติดตาม", "ถูกใจ", "แชร์", "ความคิดเห็น", "ดูเพิ่มเติม", "ดูน้อยลง", "all reactions:",
        "เขียนความคิดเห็น...", "write a comment...", "subscriber", "ผู้ติดตามตัวยง"
    ]
    
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "-":
            continue
        
        lower = stripped.lower()
        if stripped.isdigit():
            continue
            
        if re.match(r"^(\d+\s*(m|h|d|min|mins|minutes|hours|days|ชม\.|นาที|ชั่วโมง)|about an hour ago|yesterday|เมื่อสักครู่).*$", lower):
            continue
            
        if any(g in lower for g in ["view more comments", "ดูความคิดเห็นเพิ่มเติม", "top fan", "subscriber", "ผู้ติดตามตัวยง"]):
            break
            
        if any(g == lower for g in garbage_keywords):
            continue
            
        cleaned_lines.append(stripped)

    full_text = "\n\n".join(cleaned_lines)
    # ตัดคำว่า See more / See less / ดูเพิ่มเติม / ดูน้อยลง / แก้ไขแล้ว ออกทั้งหมด 100%
    full_text = re.sub(r"(\.\.\.)?\s*(See more|See less|ดูเพิ่มเติม|ดูน้อยลง|แก้ไขแล้ว)", "", full_text, flags=re.IGNORECASE).strip()

    paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
    unique_paragraphs = []
    for p in paragraphs:
        if p not in unique_paragraphs:
            unique_paragraphs.append(p)
            
    result = "\n\n".join(unique_paragraphs).strip()
    
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
        "title": f"📌 โพสต์ใหม่จาก {PAGE_NAME}",
        "url": url,
        "description": f"{formatted_content}\n\n🔗 **[กดตรงนี้เพื่อเปิดดูโพสต์บน Facebook]({url})**",
        "color": 1603570, # สีน้ำเงิน Facebook คมชัด
        "footer": {"text": f"เพจ: {PAGE_NAME} • อัปเดตล่าสุด"}
    }

    if image_url:
        embed["image"] = {"url": image_url}

    payload = {
        "content": f"📢 📌 **มีโพสต์ใหม่จากเพจ {PAGE_NAME}!** @everyone",
        "username": PAGE_NAME,
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
            print(f"กำลังเปิดหน้าเพจ Facebook: [{PAGE_NAME}]...")
            page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4000)

            for step in range(8):
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
                                const textBlocks = [];
                                const dirNodes = clone.querySelectorAll('div[dir="auto"]');
                                dirNodes.forEach(node => {
                                    if (!node.parentElement.closest('div[dir="auto"]')) {
                                        const t = node.innerText.trim();
                                        if (t.length > 10 && !t.includes('นักลงพุง') && !t.includes('ถูกใจ') && !t.includes('แชร์')) {
                                            textBlocks.push(t);
                                        }
                                    }
                                });
                                text = textBlocks.join('\\n\\n');
                            }

                            text =
