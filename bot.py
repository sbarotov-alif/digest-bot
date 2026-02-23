"""
Telegram Digest Bot
Читает каналы, фильтрует по ключевым словам, отправляет дайджест каждый день в 19:00
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
import telegram
import schedule
import time
import os

# ─────────────────────────────────────────────
# НАСТРОЙКИ — заполните своими данными
# ─────────────────────────────────────────────

API_ID = int(os.environ.get("API_ID", "ВАШ_API_ID"))
API_HASH = os.environ.get("API_HASH", "ВАШ_API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_BOT_TOKEN")
TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL", "@ВАШ_КАНАЛ_ДЛЯ_ДАЙДЖЕСТА")

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

# Время отправки (UTC+5 Ташкент = 19:00 → UTC 14:00)
SEND_TIME_UTC = "14:00"

# ─────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(message)s")
logger = logging.getLogger(__name__)


def matches_keywords(text: str) -> list[str]:
    """Возвращает список найденных ключевых слов в тексте."""
    text_lower = text.lower()
    found = [kw for kw in KEYWORDS if kw.lower() in text_lower]
    return found


async def fetch_posts() -> list[dict]:
    """Читает посты за последние 24 часа из всех каналов."""
    client = TelegramClient("session_digest", API_ID, API_HASH)
    await client.start()

    results = []
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    for channel in SOURCE_CHANNELS:
        try:
            entity = await client.get_entity(channel)
            history = await client(GetHistoryRequest(
                peer=entity,
                limit=100,
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
                        "channel": channel,
                        "text": msg.message,
                        "date": msg.date,
                        "url": f"https://t.me/{channel}/{msg.id}",
                        "keywords": found_kw,
                    })

            logger.info(f"✅ {channel}: обработано {len(history.messages)} постов")

        except Exception as e:
            logger.error(f"❌ Ошибка при чтении {channel}: {e}")

    await client.disconnect()
    return results


def build_digest(posts: list[dict]) -> str:
    """Формирует текст дайджеста."""
    if not posts:
        return "📭 За сегодня не найдено новостей по вашим темам."

    date_str = datetime.now().strftime("%d.%m.%Y")
    lines = [f"📰 *Дайджест за {date_str}*\n"]
    lines.append(f"Найдено постов: *{len(posts)}*\n")
    lines.append("─" * 30 + "\n")

    # Группируем по каналам
    by_channel = {}
    for post in posts:
        ch = post["channel"]
        by_channel.setdefault(ch, []).append(post)

    for channel, channel_posts in by_channel.items():
        lines.append(f"\n📢 *@{channel}* ({len(channel_posts)} пост(ов))\n")
        for post in channel_posts:
            # Обрезаем длинный текст
            text = post["text"][:300].replace("*", "").replace("_", "").replace("`", "")
            if len(post["text"]) > 300:
                text += "..."
            kw_str = ", ".join(post["keywords"][:3])
            lines.append(f"🔑 _{kw_str}_")
            lines.append(f"{text}")
            lines.append(f"[→ Открыть пост]({post['url']})\n")

    return "\n".join(lines)


async def send_digest():
    """Основная функция: собирает посты и отправляет дайджест."""
    logger.info("🚀 Запуск сбора дайджеста...")

    posts = await fetch_posts()
    digest_text = build_digest(posts)

    bot = telegram.Bot(token=BOT_TOKEN)

    # Telegram лимит — 4096 символов. Разбиваем если нужно.
    max_len = 4000
    if len(digest_text) <= max_len:
        await bot.send_message(
            chat_id=TARGET_CHANNEL,
            text=digest_text,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
    else:
        parts = [digest_text[i:i+max_len] for i in range(0, len(digest_text), max_len)]
        for part in parts:
            await bot.send_message(
                chat_id=TARGET_CHANNEL,
                text=part,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            await asyncio.sleep(1)

    logger.info(f"✅ Дайджест отправлен! Постов: {len(posts)}")


def run_digest():
    asyncio.run(send_digest())


if __name__ == "__main__":
    logger.info(f"🤖 Бот запущен. Дайджест будет отправляться в {SEND_TIME_UTC} UTC (19:00 Ташкент)")

    # Запуск по расписанию
    schedule.every().day.at(SEND_TIME_UTC).do(run_digest)

    # Раскомментируйте строку ниже чтобы запустить СРАЗУ для теста:
    run_digest()

    while True:
        schedule.run_pending()
        time.sleep(60)
