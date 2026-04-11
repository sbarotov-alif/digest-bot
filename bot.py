"""
Telegram News Bot
- Каждый час с 10:00 до 22:00 (Ташкент) проверяет каналы и отправляет новые релевантные новости
- Дубли не отправляет (запоминает уже отправленные)
- Ежедневный дайджест в 19:00 + Топ-5 постов по просмотрам
- Узбекские тексты автоматически переводятся на русский
"""

import asyncio
import logging
import json
import os
import re
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
    "банк", "банки", "банков",
    "markaziy bank", "цб", "центральный банк",
    "тбс банк", "tbc",
    "алиф", "alif",
    "анорбанк", "anorbank",
    "ипотекабанк", "ipotekabank",
    "кредит", "кредиты", "кредитный",
    "рассрочка", "nasiya",
    "bnpl", "halol savdo",
    "muddatli to'lov",
    "факторинг",
    "исламские финансы",
    "халяльные кредиты", "халяль",
    "мурабаха", "murobaha",
    "бизнес", "b2b",
    "кредитная карта", "кредитные карты",
]

# Рабочие часы по Ташкенту (UTC+5)
WORK_HOUR_START = 10
WORK_HOUR_END = 22

# Группы для саммари (ID → название)
SUMMARY_GROUPS = {}

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



def get_first_line(text: str, max_len: int = 120) -> str:
    """Берёт первую строку текста и обрезает до max_len символов."""
    line = text.split("\n")[0][:max_len]
    line = line.replace("*", "").replace("_", "").replace("`", "")
    return line


def linkify_last_word(text: str, url: str) -> str:
    """Вставляет ссылку внутрь последнего слова текста."""
    words = text.rstrip().split(" ")
    if not words:
        return f"[текст]({url})"
    last = words[-1].rstrip(".,!?;:")
    punct = words[-1][len(last):]
    words[-1] = f"[{last}]({url}){punct}"
    return " ".join(words)


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


async def fetch_new_posts(hours_back: int = 1) -> list:
    """Читает посты за последние N часов."""
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

                text_key = msg.message[:80].strip().lower()
                if text_key in seen_texts:
                    continue
                seen_texts.add(text_key)

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


async def fetch_group_messages(group_id: int, hours_back: int = 21) -> list:
    """Читает сообщения из группы за последние N часов."""
    client = TelegramClient("session_digest", API_ID, API_HASH)
    await client.start()

    messages = []
    since = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    try:
        entity = await client.get_entity(group_id)
        history = await client(GetHistoryRequest(
            peer=entity,
            limit=200,
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
            messages.append(msg.message)

    except Exception as e:
        logger.error(f"❌ Ошибка чтения группы {group_id}: {e}")

    await client.disconnect()
    return messages




async def send_group_summaries():
    """Отправляет саммари всех групп в 19:05."""
    logger.info("💬 Отправка саммари групп...")

    date_str = (datetime.now(timezone.utc) + timedelta(hours=5)).strftime("%d.%m.%Y")
    bot = telegram.Bot(token=BOT_TOKEN)

    # Заголовок
    await bot.send_message(
        chat_id=TARGET_CHANNEL,
        text=f"💬 *Саммари чатов за {date_str}*",
        parse_mode="Markdown",
    )
    await asyncio.sleep(2)

    for group_id, group_name in SUMMARY_GROUPS.items():
        logger.info(f"📖 Читаю {group_name}...")
        messages = await fetch_group_messages(group_id, hours_back=21)

        if not messages:
            logger.info(f"📭 {group_name}: сообщений нет")
            continue

        summary = summarize_group(group_name, messages)

        text = f"*{group_name}*\n\n{summary}"

        try:
            await bot.send_message(
                chat_id=TARGET_CHANNEL,
                text=text,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            logger.info(f"✅ Саммари отправлен: {group_name}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки саммари {group_name}: {e}")

        await asyncio.sleep(3)

    logger.info("✅ Все саммари отправлены!")


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
        text = post["text"]

        first_line = get_first_line(text)

        # Ссылка внутри последнего слова
        first_line_linked = linkify_last_word(first_line, post["url"])

        message = f"{first_line_linked}"

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

    posts = await fetch_new_posts(hours_back=21)

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
            text = post["text"]
            first_line = get_first_line(text, max_len=100)
            first_line_linked = linkify_last_word(f"→ {first_line}", post["url"])

    digest_text = "\n".join(lines)

    # ── Часть 2: Топ-5 по просмотрам ──
    top5 = sorted(posts, key=lambda x: x["views"], reverse=True)[:5]
    top_lines = ["\n🔥 *Топ-5 постов дня по просмотрам*\n"]
    for i, post in enumerate(top5):
        ch_name = CHANNEL_NAMES.get(post["channel"], post["channel"])
        text = post["text"]
        first_line = get_first_line(text, max_len=100)
        first_line_linked = linkify_last_word(first_line, post["url"])
        views_str = f"{post['views']:,}".replace(",", " ")
        top_lines.append(f"{i+1}. {first_line_linked}")
        top_lines.append(f"    {views_str} просмотров · {ch_name}\n")

    top_text = "\n".join(top_lines)

    bot = telegram.Bot(token=BOT_TOKEN)
    max_len = 4000

    # Сначала отправляем дайджест
    for part in [digest_text[i:i+max_len] for i in range(0, len(digest_text), max_len)]:
        await bot.send_message(
            chat_id=TARGET_CHANNEL,
            text=part,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        await asyncio.sleep(1)

    # Пауза между сообщениями
    await asyncio.sleep(3)

    # Затем топ-5 отдельным сообщением
    for part in [top_text[i:i+max_len] for i in range(0, len(top_text), max_len)]:
        await bot.send_message(
            chat_id=TARGET_CHANNEL,
            text=part,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        await asyncio.sleep(1)

    logger.info("✅ Дайджест и топ-5 отправлены отдельными сообщениями!")


def run_news():
    asyncio.run(send_news())

def run_digest():
    asyncio.run(send_daily_digest())

def run_summaries():
    asyncio.run(send_group_summaries())


if __name__ == "__main__":
    logger.info("🤖 Бот запущен!")
    logger.info("📡 Мониторинг каждый час с 10:00 до 22:00 по Ташкенту")
    logger.info("📰 Дайджест + Топ-5 в 19:00, Саммари чатов в 19:05 по Ташкенту")

    schedule.every(60).minutes.do(run_news)
    schedule.every().day.at("14:00").do(run_digest)    # 19:00 Ташкент
    schedule.every().day.at("14:05").do(run_summaries) # 19:05 Ташкент

    # Тест — запустить сразу при старте (уберите # чтобы проверить):
    # run_news()
    # run_digest()
    # run_summaries()

    while True:
        schedule.run_pending()
        time.sleep(60)
