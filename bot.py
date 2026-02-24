"""
Telegram News Bot
- Каждый час с 10:00 до 22:00 (Ташкент) проверяет каналы и отправляет новые релевантные новости
- Дубли не отправляет (запоминает уже отправленные)
- Ежедневный дайджест в 19:00 + Топ-5 постов по просмотрам
"""

import asyncio
import logging
import json
import os
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
import telegram
import schedule
import time

# ─────────────────────────────────────────────
# НАСТРОЙКИ
# ─────────────────────────────────────────────

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL")

# Каналы для мониторинга
SOURCE_CHANNELS = [
    "spotuz",
    "RepostUZ",
    "davletovuz",
    "bankmijoz",
    "kurbanoffnet",
    "Bankir",
    "bankirlaruchun",
    "makarenko_channel",
    "na_begu",
    "uzbekistan_online_novosti_uznews",
    "uzbekfintech",
    "soliqnews",
    "centralbankuzbekistan",
    "bankxabar",
    "bankers_uz",
    "FinansistUZ",
    "fiskaltahlil",
    "bhblaw",
    "vsebudethorosho",
]

# Ключевые слова (регистр не важен)
KEYWORDS = [
    # Банки
    "банк", "банки", "банков",
    "markaziy bank", "цб", "центральный банк",
    "тбс банк", "tbc",
    "алиф", "alif",
    "анорбанк", "anorbank",
    "ипотекабанк", "ipotekabank",
    # Кредиты и финансы
    "кредит", "кредиты", "кредитный",
    "рассрочка", "nasiya",
    "bnpl", "halol savdo",
    "muddatli to'lov",
    "факторинг",
    # Исламские финансы
    "исламские финансы",
    "халяльные кредиты", "халяль",
    "мурабаха", "murobaha",
    # Бизнес
    "бизнес", "b2b",
    "кредитная карта", "кредитные карты",
]

# Рабочие часы по Ташкенту (UTC+5)
WORK_HOUR_START = 10   # 10:00 Ташкент = 05:00 UTC
WORK_HOUR_END = 22     # 22:00 Ташкент = 17:00 UTC

# Файл для хранения уже отправленных постов
SENT_FILE = "sent_posts.json"

# Красивые названия каналов
CHANNEL_NAMES = {
    "spotuz": "Spot.uz",
    "RepostUZ": "Repost UZ",
    "davletovuz": "Davletov UZ",
    "bankmijoz": "Bank Mijoz",
    "kurbanoffnet": "Kurbanoff",
    "Bankir": "Bankir.uz",
    "bankirlaruchun": "Bankirlar Uchun",
    "makarenko_channel": "Makarenko",
    "na_begu": "На бегу",
    "uzbekistan_online_novosti_uznews": "UZ News",
    "uzbekfintech": "Uzbek Fintech",
    "soliqnews": "Soliq News",
    "centralbankuzbekistan": "ЦБ Узбекистана",
    "bankxabar": "Bank Xabar",
    "bankers_uz": "Bankers UZ",
    "FinansistUZ": "Finansist UZ",
    "fiskaltahlil": "Fiskal Tahlil",
    "bhblaw": "BHB Law",
    "vsebudethorosho": "Всё будет хорошо",
}

# ─────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(message)s")
logger = logging.getLogger(__name__)


def load_sent() -> set:
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_sent(sent: set):
    sent_list = list(sent)[-5000:]
    with open(SENT_FILE, "w") as f:
        json.dump(sent_list, f)


def is_working_hours() -> bool:
    tashkent_hour = (datetime.now(timezone.utc) + timedelta(hours=5)).hour
    return WORK_HOUR_START <= tashkent_hour < WORK_HOUR_END


def matches_keywords(text: str) -> list:
    text_lower = text.lower()
    return [kw for kw in KEYWORDS if kw.lower() in text_lower]


async def fetch_new_posts(hours_back: int = 1, with_views: bool = False) -> list:
    """Читает посты за последние N часов. with_views=True — собирает просмотры для топа."""
    client = TelegramClient("session_digest", API_ID, API_HASH)
    await client.start()

    results = []
    seen_texts = set()
    since = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    for channel in SOURCE_CHANNELS:
        try:
            entity = await client.get_entity(channel)
            history = await client(GetHistoryRequest(
                peer=entity,
                limit=50,
                offset_date=None,
                offset_id=0,
                max_id=0,
                min_id=0,
                add_offset=0,
                hash=0
            ))

            for msg in history.messages:
                if not msg.message:
                    continue
                if msg.date.replace(tzinfo=timezone.utc) < since:
                    continue
                found_kw = matches_keywords(msg.message)
                if not found_kw:
                    continue

                # Защита от дублей по тексту
                text_key = msg.message[:80].strip().lower()
                if text_key in seen_texts:
                    logger.info(f"⏭ Дубль пропущен из {channel}")
                    continue
                seen_texts.add(text_key)

                # Просмотры (только если запрашиваем для топа)
                views = getattr(msg, "views", 0) or 0

                results.append({
                    "id": f"{channel}_{msg.id}",
                    "channel": channel,
                    "text": msg.message,
                    "date": msg.date,
                    "url": f"https://t.me/{channel}/{msg.id}",
                    "keywords": found_kw,
                    "views": views,
                })

            logger.info(f"✅ {channel}: проверено")

        except Exception as e:
            logger.error(f"❌ Ошибка {channel}: {e}")

    await client.disconnect()
    return results


async def send_news():
    """Проверяет новые посты и отправляет их если они новые."""
    if not is_working_hours():
        tashkent_time = (datetime.now(timezone.utc) + timedelta(hours=5)).strftime("%H:%M")
        logger.info(f"⏰ Сейчас {tashkent_time} по Ташкенту — вне рабочих часов, пропускаем")
        return

    tashkent_time = (datetime.now(timezone.utc) + timedelta(hours=5)).strftime("%H:%M")
    logger.info(f"🔍 Проверка новостей ({tashkent_time} по Ташкенту)...")

    posts = await fetch_new_posts(hours_back=1)
    sent = load_sent()
    new_posts = [p for p in posts if p["id"] not in sent]

    if not new_posts:
        logger.info("📭 Новых релевантных постов нет")
        return

    bot = telegram.Bot(token=BOT_TOKEN)

    for post in new_posts:
        kw_str = ", ".join(post["keywords"][:3])
        first_line = post["text"].split("\n")[0][:120].replace("*", "").replace("_", "").replace("`", "")
        if len(first_line) == 120:
            first_line += "..."

        message = (
            f"🔔 {first_line}\n"
            f"[@{post['channel']}]({post['url']}) · _{kw_str}_"
        )

        try:
            await bot.send_message(
                chat_id=TARGET_CHANNEL,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            sent.add(post["id"])
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")

    save_sent(sent)
    logger.info(f"✅ Отправлено новых постов: {len(new_posts)}")


async def send_daily_digest():
    """Ежедневный дайджест в 19:00 с топ-5 по просмотрам."""
    logger.info("📰 Отправка ежедневного дайджеста...")

    posts = await fetch_new_posts(hours_back=21, with_views=True)  # с 00:00 до 21:00

    if not posts:
        text = "📭 За сегодня не найдено новостей по вашим темам."
        bot = telegram.Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=TARGET_CHANNEL, text=text)
        return

    date_str = (datetime.now(timezone.utc) + timedelta(hours=5)).strftime("%d.%m.%Y")

    # ── Часть 1: Дайджест по каналам ──
    lines = [f"🗞 *{date_str} — Лови новости братан)*\n"]

    by_channel = {}
    for post in posts:
        by_channel.setdefault(post["channel"], []).append(post)

    for channel, ch_posts in by_channel.items():
        ch_name = CHANNEL_NAMES.get(channel, channel)
        lines.append(f"\n*{ch_name}*")
        for post in ch_posts:
            first_line = post["text"].split("\n")[0][:100].replace("*", "").replace("_", "").replace("`", "").replace("[", "").replace("]", "")
            lines.append(f"→ {first_line} [...]({post['url']})\n")

    digest_text = "\n".join(lines)

    # ── Часть 2: Топ-5 по просмотрам ──
    top5 = sorted(posts, key=lambda x: x["views"], reverse=True)[:5]

    top_lines = ["\n🔥 *Топ-5 постов дня по просмотрам*\n"]
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, post in enumerate(top5):
        ch_name = CHANNEL_NAMES.get(post["channel"], post["channel"])
        first_line = post["text"].split("\n")[0][:100].replace("*", "").replace("_", "").replace("`", "").replace("[", "").replace("]", "")
        views_str = f"{post['views']:,}".replace(",", " ")
        top_lines.append(f"{medals[i]} {first_line} [...]({post['url']})")
        top_lines.append(f"    👁 {views_str} просмотров · {ch_name}\n")

    top_text = "\n".join(top_lines)

    # ── Отправка ──
    bot = telegram.Bot(token=BOT_TOKEN)
    full_text = digest_text + top_text

    max_len = 4000
    parts = [full_text[i:i+max_len] for i in range(0, len(full_text), max_len)]
    for part in parts:
        await bot.send_message(
            chat_id=TARGET_CHANNEL,
            text=part,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        await asyncio.sleep(1)

    logger.info("✅ Дайджест с топ-5 отправлен!")


def run_news():
    asyncio.run(send_news())

def run_digest():
    asyncio.run(send_daily_digest())


if __name__ == "__main__":
    logger.info("🤖 Бот запущен!")
    logger.info("📡 Мониторинг каждый час с 10:00 до 22:00 по Ташкенту")
    logger.info("📰 Ежедневный дайджест + Топ-5 в 19:00 по Ташкенту")

    # Проверка каждый час (каждые 60 минут)
    schedule.every(60).minutes.do(run_news)

    # Ежедневный дайджест в 19:00 Ташкент = 14:00 UTC
    schedule.every().day.at("14:00").do(run_digest)

    # Тест — запустить сразу при старте (уберите # чтобы проверить):
    # run_news()
    # run_digest()

    while True:
        schedule.run_pending()
        time.sleep(60)
