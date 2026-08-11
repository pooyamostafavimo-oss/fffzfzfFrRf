#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بات اخبار اقتصادی جهان -> کانال تلگرام
هر بار اجرا: فیدهای RSS اقتصادی رو چک می‌کنه، خبرهای جدید رو پیدا می‌کنه،
عکس خبر (در صورت وجود) رو می‌گیره و با کپشن فارسی تو کانال تلگرام پست می‌کنه.
خبرهایی که قبلاً پست شدن تو فایل posted.json ذخیره می‌شن تا تکراری پست نشن.
"""

import os
import re
import json
import time
import html
import feedparser
import requests

# ---------------------------------------------------------------------------
# تنظیمات
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ["BOT_TOKEN"]          # از GitHub Secrets خونده می‌شه
CHANNEL_ID = os.environ["CHANNEL_ID"]        # مثلاً @my_econ_news یا -100xxxxxxxxxx
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]  # کلید رایگان از aistudio.google.com/app/apikey

GEMINI_MODEL = "gemini-flash-lite-latest"   # alias همیشه‌به‌روز گوگل به جدیدترین مدل flash-lite پایدار
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

POSTED_FILE = "posted.json"
MAX_POSTED_HISTORY = 500     # حداکثر تعداد لینک ذخیره‌شده (برای جلوگیری از بزرگ شدن فایل)
MAX_POSTS_PER_RUN = 5        # حداکثر تعداد پستی که تو هر اجرا فرستاده می‌شه
MAX_CANDIDATES_PER_RUN = 25  # حداکثر تعداد خبری که تو هر اجرا به Gemini برای بررسی فرستاده می‌شه (برای رعایت quota رایگان)

# فیدهای RSS اخبار اقتصادی جهانی (رایگان و بدون نیاز به کلید API)
# نکته: بلومبرگ، رویترز و فارکس‌فکتوری دیگه فید RSS رسمی و رایگان ندارن،
# پس به‌جاشون از منابع معتبر معادل استفاده شده (CNBC برای بلومبرگ،
# MarketWatch/Dow Jones برای رویترز، Investing.com Forex برای فارکس‌فکتوری)
RSS_FEEDS = [
    "https://feeds.a.dj.com/rss/RSSWorldNews.xml",             # وال استریت ژورنال (WSJ) - اخبار جهانی
    "https://moxie.foxbusiness.com/google-publisher/economy.xml",  # فاکس بیزینس - اقتصاد
    "https://moxie.foxbusiness.com/google-publisher/markets.xml",  # فاکس بیزینس - بازارها
    "https://www.cnbc.com/id/20910258/device/rss/rss.html",    # CNBC اقتصاد (جایگزین بلومبرگ)
    "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain",  # MarketWatch/Dow Jones (جایگزین رویترز)
    "https://www.investing.com/rss/news_285.rss",              # Investing.com فارکس (جایگزین فارکس‌فکتوری)
]


def ask_gemini(title, summary):
    """
    از Gemini می‌خواد که بگه خبر مهمه یا نه، و اگه مهمه عنوان/خلاصه رو
    به فارسی روان ترجمه کنه. خروجی: dict یا None (در صورت خطا)
    """
    prompt = f"""تو یه دستیار خبری اقتصادی هستی. این خبر رو بررسی کن:

عنوان: {title}
خلاصه: {summary}

فقط اگه این خبر واقعاً برای عموم اقتصادی مهمه (مثلاً تصمیمات بانک مرکزی،
نرخ بهره، تورم، نوسان شدید بازار سهام/ارز/طلا/نفت، بحران اقتصادی، تصمیمات
مهم دولت‌ها یا شرکت‌های بزرگ) اون رو مهم علامت بزن؛ خبرهای عادی و کم‌اهمیت
مهم نیستن.

فقط یک خروجی JSON خام (بدون ```json و بدون توضیح اضافه) با این ساختار بده:
{{"important": true یا false, "title_fa": "ترجمه روان فارسی عنوان", "summary_fa": "خلاصه روان فارسی در حداکثر ۲ جمله"}}
"""
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        resp = requests.post(GEMINI_URL, json=body, timeout=30)
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = text.strip().strip("```").replace("json\n", "", 1).strip()
        return json.loads(text)
    except Exception as e:
        print(f"⚠️ خطا در تماس با Gemini: {e}")
        return None


def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_posted(posted_list):
    trimmed = posted_list[-MAX_POSTED_HISTORY:]
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def clean_html(raw):
    """حذف تگ‌های HTML از خلاصه خبر"""
    text = re.sub(r"<[^>]+>", "", raw or "")
    return html.unescape(text).strip()


def extract_image(entry):
    """تلاش برای پیدا کردن لینک عکس خبر از entry فید RSS"""
    if "media_content" in entry and entry.media_content:
        return entry.media_content[0].get("url")
    if "media_thumbnail" in entry and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url")
    if "links" in entry:
        for link in entry.links:
            if link.get("type", "").startswith("image"):
                return link.get("href")
    match = re.search(r'<img[^>]+src="([^"]+)"', entry.get("summary", ""))
    if match:
        return match.group(1)
    return None


PINNED_PRICE_LINK = "https://t.me/Tala_Dollar_ir/1153"
CHANNEL_HANDLE = "@Tala_Dollar_ir"


def send_to_telegram(title_fa, link, summary_fa, image_url):
    caption = f"📌 <b>{html.escape(title_fa)}</b>\n\n"
    caption += f'<b>💰 برای مشاهده قیمت لحظه‌ای <a href="{PINNED_PRICE_LINK}">اینجا</a> کلیک کنید</b>\n\n'
    if summary_fa:
        short_summary = summary_fa[:500] + ("..." if len(summary_fa) > 500 else "")
        caption += f"{html.escape(short_summary)}\n\n"
    caption += f'🔗 <a href="{link}">مشاهده خبر اصلی (انگلیسی)</a>\n\n'
    caption += CHANNEL_HANDLE

    if image_url:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": CHANNEL_ID,
            "photo": image_url,
            "caption": caption[:1024],
            "parse_mode": "HTML",
        }
        resp = requests.post(url, data=payload, timeout=30)
        if resp.status_code == 200 and resp.json().get("ok"):
            return True
        print(f"⚠️ ارسال با عکس ناموفق بود، تلاش بدون عکس... ({resp.text[:200]})")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": caption[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, data=payload, timeout=30)
    if resp.status_code == 200 and resp.json().get("ok"):
        return True
    print(f"❌ ارسال پیام ناموفق بود: {resp.text[:300]}")
    return False


def main():
    posted = load_posted()
    posted_set = set(posted)
    new_posts_count = 0
    candidates_checked = 0

    for feed_url in RSS_FEEDS:
        if new_posts_count >= MAX_POSTS_PER_RUN or candidates_checked >= MAX_CANDIDATES_PER_RUN:
            break
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"⚠️ خطا در خوندن فید {feed_url}: {e}")
            continue

        for entry in feed.entries:
            if new_posts_count >= MAX_POSTS_PER_RUN or candidates_checked >= MAX_CANDIDATES_PER_RUN:
                break

            link = entry.get("link")
            title = entry.get("title", "")
            if not link or not title:
                continue
            if link in posted_set:
                continue

            summary = clean_html(entry.get("summary", ""))
            candidates_checked += 1

            result = ask_gemini(title, summary)
            if not result or not result.get("important"):
                posted.append(link)
                posted_set.add(link)
                continue

            title_fa = result.get("title_fa", title)
            summary_fa = result.get("summary_fa", "")
            image_url = extract_image(entry)

            print(f"📤 در حال پست: {title_fa}")
            success = send_to_telegram(title_fa, link, summary_fa, image_url)

            posted.append(link)
            posted_set.add(link)
            if success:
                new_posts_count += 1
                time.sleep(2)

    save_posted(posted)
    print(f"✅ پایان اجرا. بررسی‌شده: {candidates_checked} | پست‌شده: {new_posts_count}")


if __name__ == "__main__":
    main()
