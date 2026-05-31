"""
Поиск рефералов — люди готовые порекомендовать в свои компании.
Источники: публичные Telegram-каналы, веб-поиск.
"""
import asyncio
import logging
import re
import aiohttp
from datetime import datetime

logger = logging.getLogger(__name__)

# Популярные публичные Telegram-каналы с рефералами
REFERRAL_CHANNELS = [
    "referalsIT",        # Рефералы IT
    "refer_me_it",       # Refer me IT
    "it_referrals",      # IT Referrals
    "devjobs_referrals", # Dev Jobs Referrals
    "remote_referral",   # Remote Referral
    "tech_referral_ru",  # Tech Referral RU
    "jobs_for_friends",  # Jobs for Friends
]

REFERRAL_KEYWORDS = [
    "реферал", "referral", "refer", "рекомендация", "порекомендую",
    "invite", "инвайт", "реферер", "referrer", "refer me",
    "могу порекомендовать", "ready to refer", "happy to refer",
    "дам реферал", "дать реферал"
]


async def fetch_telegram_channel(channel: str, limit: int = 20) -> list[dict]:
    """
    Парсим публичный Telegram-канал через web preview (t.me/s/channel).
    Не требует API ключей.
    """
    url = f"https://t.me/s/{channel}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")

        posts = []
        messages = soup.find_all("div", class_="tgme_widget_message_wrap")

        for msg in messages[:limit]:
            text_elem = msg.find("div", class_="tgme_widget_message_text")
            if not text_elem:
                continue

            text = text_elem.get_text(separator=" ", strip=True)
            if len(text) < 30:
                continue

            # Проверяем что пост о рефералах
            text_lower = text.lower()
            if not any(kw in text_lower for kw in REFERRAL_KEYWORDS):
                continue

            # Ссылка на пост
            link_elem = msg.find("a", class_="tgme_widget_message_date")
            post_url = link_elem.get("href", "") if link_elem else ""

            # Дата
            date_elem = msg.find("time")
            date_str = date_elem.get("datetime", "")[:10] if date_elem else ""

            posts.append({
                "source": f"Telegram @{channel}",
                "text": text[:500],
                "url": post_url,
                "date": date_str,
                "channel": channel,
            })

        return posts

    except Exception as e:
        logger.debug(f"Telegram channel {channel} parse error: {e}")
        return []


async def search_referrals_telegram(query: str = "", company: str = "") -> list[dict]:
    """Поиск рефералов во всех Telegram-каналах."""
    tasks = [fetch_telegram_channel(ch) for ch in REFERRAL_CHANNELS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_posts = []
    for result in results:
        if isinstance(result, list):
            all_posts.extend(result)

    # Фильтруем по компании если указана
    if company:
        company_lower = company.lower()
        all_posts = [p for p in all_posts if company_lower in p["text"].lower()]

    # Фильтруем по запросу
    if query:
        query_lower = query.lower()
        all_posts = [p for p in all_posts if query_lower in p["text"].lower()]

    return all_posts[:15]


async def search_referrals_web(company: str = "", position: str = "") -> list[dict]:
    """
    Поиск рефералов через веб — Reddit, LinkedIn, Habr.
    Возвращает поисковые запросы для агента.
    """
    searches = []

    if company:
        searches.append({
            "platform": "LinkedIn",
            "query": f"{company} referral program employee refer candidate site:linkedin.com",
            "description": f"Сотрудники {company} готовые дать реферал",
            "tip": f"Найди сотрудников {company} в LinkedIn и напиши им с просьбой о реферале"
        })
        searches.append({
            "platform": "Reddit",
            "query": f"{company} employee referral site:reddit.com",
            "description": f"Обсуждения рефералов {company} на Reddit",
            "tip": f"Поищи тред '{company} referral' на reddit.com/r/cscareerquestions"
        })
        searches.append({
            "platform": "Blind / Teamblind",
            "query": f"{company} referral teamblind.com",
            "description": f"Анонимные отзывы и рефералы {company}",
            "tip": f"На teamblind.com есть тред '{company} referrals' где сотрудники предлагают рефералы"
        })

    if position:
        searches.append({
            "platform": "Habr Career",
            "query": f"реферал {position} site:career.habr.com",
            "description": f"Рефералы для {position} на Habr",
            "tip": "На Habr Career есть раздел с рекомендациями"
        })

    return searches


def parse_referral_offer(text: str) -> dict:
    """Извлечь структурированные данные из поста о реферале."""
    companies = re.findall(
        r'\b(Google|Yandex|Яндекс|VK|Mail\.ru|Сбер|Тинькофф|Tinkoff|'
        r'Озон|Ozon|Авито|Avito|Wildberries|Kaspersky|JetBrains|'
        r'Luxoft|EPAM|Wrike|Miro|Revolut|Booking|Amazon|Microsoft|'
        r'Meta|Apple|Netflix|Uber|Airbnb|Spotify)\b',
        text, re.IGNORECASE
    )

    positions = re.findall(
        r'\b(developer|разработчик|engineer|инженер|backend|frontend|'
        r'fullstack|devops|qa|analyst|аналитик|manager|менеджер|'
        r'data scientist|ml engineer|python|java|golang|ios|android)\b',
        text, re.IGNORECASE
    )

    # Ищем контакт
    contact = re.findall(r'@[\w]+', text)

    return {
        "companies": list(set(companies)),
        "positions": list(set(positions)),
        "contact": contact[0] if contact else "",
        "has_bonus": any(w in text.lower() for w in ["бонус", "bonus", "$", "reward"]),
    }


# Известные Telegram-каналы с вакансиями и рефералами
KNOWN_REFERRAL_RESOURCES = [
    {
        "name": "Refer.me",
        "url": "https://refer.me",
        "description": "Платформа для поиска рефералов в IT компаниях мира",
        "type": "platform",
    },
    {
        "name": "Teamblind",
        "url": "https://www.teamblind.com",
        "description": "Анонимная сеть где сотрудники предлагают рефералы",
        "type": "platform",
    },
    {
        "name": "LinkedIn (Refer)",
        "url": "https://www.linkedin.com",
        "description": "Найди Alumni своего университета в целевой компании",
        "type": "platform",
    },
    {
        "name": "r/cscareerquestions",
        "url": "https://reddit.com/r/cscareerquestions",
        "description": "Reddit — часто постят офферы рефералов в топ компании",
        "type": "community",
    },
    {
        "name": "r/devops / r/golang / r/python",
        "url": "https://reddit.com/r/devops",
        "description": "Профессиональные сообщества где предлагают рефералы",
        "type": "community",
    },
    {
        "name": "Telegram: @it_jobs_ru",
        "url": "https://t.me/it_jobs_ru",
        "description": "Русскоязычный канал с вакансиями и рефералами",
        "type": "telegram",
    },
    {
        "name": "Telegram: @remote_it_jobs",
        "url": "https://t.me/remote_it_jobs",
        "description": "Удалённые IT вакансии, иногда с рефералами",
        "type": "telegram",
    },
    {
        "name": "Levels.fyi Community",
        "url": "https://www.levels.fyi",
        "description": "Зарплаты и иногда рефералы в топ компании",
        "type": "platform",
    },
]


async def get_referral_guide(company: str = "", skills: str = "") -> dict:
    """Сгенерировать гайд по получению реферала."""
    tips = []

    if company:
        tips.extend([
            f"1. Найди сотрудников {company} в LinkedIn через Alumni своего вуза",
            f"2. Поищи '{company} referral' на Teamblind.com — там анонимно предлагают рефералы",
            f"3. Зайди на {company} Engineering Blog — там часто упоминают hiring",
            f"4. Reddit r/cscareerquestions: напиши пост 'Looking for {company} referral'",
        ])
    else:
        tips.extend([
            "1. Заполни профиль на refer.me — платформе для поиска рефералов",
            "2. Напиши в Telegram группы: 'Ищу реферала в [компания], [стек]'",
            "3. LinkedIn: найди Alumni своего вуза в целевых компаниях",
            "4. Hackathons и митапы — лучшее место познакомиться с будущим рефером",
        ])

    message_template = (
        "Привет! Меня зовут [имя], я [должность] с [N] годами опыта в [стек].\n"
        "Вижу что ты работаешь в [компания] — я очень заинтересован в позиции [должность].\n"
        "Было бы здорово если ты мог бы меня порекомендовать.\n"
        "Готов рассказать подробнее о своём опыте. Спасибо!"
    )

    return {
        "tips": tips,
        "message_template": message_template,
        "resources": KNOWN_REFERRAL_RESOURCES,
    }
