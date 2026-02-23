"""
Telegram News Bot
- Каждый час с 11:00 до 21:00 (Ташкент) проверяет каналы и отправляет новые релевантные новости
- Дубли не отправляет (запоминает уже отправленные)
- Ежедневный дайджест в 19:00
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
]

# Ключевые слова (регистр не важен)
KEYWORDS = [
    "банк", "банки", "банков",
    "кредит", "кредиты", "кредитный",
    "бизнес", "b2b",
    "рассрочка", "bnpl",
    "кредитная карта", "кредитные карты",
    "tbc", "алиф", "alif",
    "анорбанк", "anorbank",
    "ипотекабанк", "ipotekabank",
]

# Рабочие часы по Ташкенту (UTC+5)
WORK_HOUR_START = 11   # 11:00 Ташкент = 06:00 UTC
WORK_HOUR_END = 21     # 21:00 Ташкент = 16:00 UTC

# Файл для хранения уже отправленных постов
SENT_FILE = "sent_posts.json"

# ─────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(message)s")
logger = logging.getLogger(__name__)


def load_sent() -> set:
    """Загружает список уже отправленных постов."""
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_sent(sent: set):
    """Сохраняет список отправленных постов."""
    # Храним только последние 5000 чтобы файл не разрастался
    sent_list = list(sent)[-5000:]
    with open(SENT_FILE, "w") as f:
        json.dump(sent_list, f)


def is_working_hours() -> bool:
    """Проверяет что сейчас рабочие часы по Ташкенту."""
    tashkent_hour = (datetime.now(timezone.utc) + timedelta(hours=5)).hour
    return WORK_HOUR_START <= tashkent_hour < WORK_HOUR_END


def matches_keywords(text: str) -> list:
    """Возвращает список найденных ключевых слов."""
    text_lower = text.lower()
    return [kw for kw in KEYWORDS if kw.lower() in text_lower]


async def fetch_new_posts(hours_back: int = 1) -> list:
    """Читает посты за последние N часов."""
    client = TelegramClient("session_digest", API_ID, API_HASH)
    await client.start()

    results = []
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
                if found_kw:
                    results.append({
                        "id": f"{channel}_{msg.id}",
                        "channel": channel,
                        "text": msg.message,
                        "date": msg.date,
                        "url": f"https://t.me/{channel}/{msg.id}",
                        "keywords": found_kw,
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
        text = post["text"][:400].replace("*", "").replace("_", "").replace("`", "")
        if len(post["text"]) > 400:
            text += "..."
        kw_str = ", ".join(post["keywords"][:3])

        message = (
            f"🔔 *Новость из @{post['channel']}*\n"
            f"🔑 _{kw_str}_\n\n"
            f"{text}\n\n"
            f"[→ Открыть пост]({post['url']})"
        )

        try:
            await bot.send_message(
                chat_id=TARGET_CHANNEL,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            sent.add(post["id"])
            await asyncio.sleep(2)  # пауза между сообщениями
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")

    save_sent(sent)
    logger.info(f"✅ Отправлено новых постов: {len(new_posts)}")


async def send_daily_digest():
    """Ежедневный дайджест в 19:00."""
    logger.info("📰 Отправка ежедневного дайджеста...")

    posts = await fetch_new_posts(hours_back=24)

    if not posts:
        text = "📭 За сегодня не найдено новостей по вашим темам."
    else:
        date_str = (datetime.now(timezone.utc) + timedelta(hours=5)).strftime("%d.%m.%Y")
        lines = [f"📰 *Итоги дня — {date_str}*\nВсего новостей: *{len(posts)}*\n" + "─" * 30]

        by_channel = {}
        for post in posts:
            by_channel.setdefault(post["channel"], []).append(post)

        for channel, ch_posts in by_channel.items():
            lines.append(f"\n📢 *@{channel}* ({len(ch_posts)})")
            for post in ch_posts[:5]:  # максимум 5 постов с канала
                t = post["text"][:200].replace("*", "").replace("_", "").replace("`", "")
                if len(post["text"]) > 200:
                    t += "..."
                lines.append(f"• {t}\n[→ пост]({post['url']})")

        text = "\n".join(lines)

    bot = telegram.Bot(token=BOT_TOKEN)
    max_len = 4000
    parts = [text[i:i+max_len] for i in range(0, len(text), max_len)]
    for part in parts:
        await bot.send_message(
            chat_id=TARGET_CHANNEL,
            text=part,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        await asyncio.sleep(1)

    logger.info("✅ Дайджест отправлен!")


def run_news():
    asyncio.run(send_news())

def run_digest():
    asyncio.run(send_daily_digest())


if __name__ == "__main__":
    logger.info("🤖 Бот запущен!")
    logger.info("📡 Мониторинг каждый час с 11:00 до 21:00 по Ташкенту")
    logger.info("📰 Ежедневный дайджест в 19:00 по Ташкенту")

    # Проверка каждый час (каждые 60 минут)
    schedule.every(60).minutes.do(run_news)

    # Ежедневный дайджест в 19:00 Ташкент = 14:00 UTC
    schedule.every().day.at("14:00").do(run_digest)

    # Тест — запустить сразу при старте (уберите # чтобы проверить):
    # run_news()

    while True:
        schedule.run_pending()
        time.sleep(60)
