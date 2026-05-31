"""
Job fetcher — получение вакансий из разных источников.
"""
import asyncio
import hashlib
import logging
import aiohttp
import feedparser
from typing import Optional
from config import HH_USER_AGENT

logger = logging.getLogger(__name__)

HH_API = "https://api.hh.ru"
REMOTIVE_API = "https://remotive.com/api/remote-jobs"
WWR_RSS = "https://weworkremotely.com/remote-jobs.rss"
HABR_RSS = "https://career.habr.com/vacancies/rss"


def _make_id(source: str, raw_id) -> str:
    return f"{source}_{raw_id}"


# ─── HH.ru ───

async def fetch_hh(query: str, area: str = "1", salary_from: int = None,
                    experience: str = None, per_page: int = 10) -> list[dict]:
    """
    Поиск вакансий на HH.ru.
    area: 1=Москва, 2=СПб, 113=Россия, 0=Весь мир
    experience: noExperience, between1And3, between3And6, moreThan6
    """
    params = {
        "text": query,
        "area": area,
        "per_page": per_page,
        "order_by": "publication_time",
        "search_field": "name",
    }
    if salary_from:
        params["salary"] = salary_from
        params["only_with_salary"] = "true"
    if experience:
        params["experience"] = experience

    headers = {"User-Agent": HH_USER_AGENT, "Accept": "application/json"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{HH_API}/vacancies",
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"HH.ru returned {resp.status}")
                    return []
                data = await resp.json()

        jobs = []
        for item in data.get("items", []):
            salary = item.get("salary")
            salary_str = ""
            if salary:
                s_from = salary.get("from")
                s_to = salary.get("to")
                currency = salary.get("currency", "RUB")
                if s_from and s_to:
                    salary_str = f"{s_from:,}–{s_to:,} {currency}"
                elif s_from:
                    salary_str = f"от {s_from:,} {currency}"
                elif s_to:
                    salary_str = f"до {s_to:,} {currency}"

            jobs.append({
                "id": _make_id("hh", item["id"]),
                "source": "HH.ru",
                "title": item.get("name", ""),
                "company": item.get("employer", {}).get("name", ""),
                "location": item.get("area", {}).get("name", ""),
                "salary": salary_str,
                "experience": item.get("experience", {}).get("name", ""),
                "schedule": item.get("schedule", {}).get("name", ""),
                "url": item.get("alternate_url", ""),
                "description": item.get("snippet", {}).get("requirement", "") or "",
                "published": item.get("published_at", "")[:10],
                "remote": "удалённ" in str(item.get("schedule", {}).get("name", "")).lower(),
            })
        logger.info(f"HH.ru: got {len(jobs)} jobs for '{query}'")
        return jobs
    except Exception as e:
        logger.error(f"HH.ru fetch error: {e}")
        return []


async def fetch_hh_detail(job_url_id: str) -> Optional[str]:
    """Получить полное описание вакансии с HH.ru."""
    raw_id = job_url_id.replace("hh_", "")
    headers = {"User-Agent": HH_USER_AGENT, "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{HH_API}/vacancies/{raw_id}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        desc = data.get("description", "")
        # Убираем HTML теги
        import re
        desc = re.sub(r'<[^>]+>', ' ', desc)
        desc = re.sub(r'\s+', ' ', desc).strip()
        return desc[:3000]
    except Exception as e:
        logger.error(f"HH detail error: {e}")
        return None


# ─── Remotive (удалённые вакансии) ───

async def fetch_remotive(query: str, category: str = "software-dev") -> list[dict]:
    """Удалённые вакансии с Remotive.com (бесплатный API)."""
    params = {"category": category, "search": query, "limit": 20}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                REMOTIVE_API,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

        jobs = []
        for item in data.get("jobs", []):
            import re
            desc = re.sub(r'<[^>]+>', ' ', item.get("description", ""))
            desc = re.sub(r'\s+', ' ', desc).strip()[:500]

            jobs.append({
                "id": _make_id("remotive", item["id"]),
                "source": "Remotive",
                "title": item.get("title", ""),
                "company": item.get("company_name", ""),
                "location": item.get("candidate_required_location", "Worldwide"),
                "salary": item.get("salary", ""),
                "experience": "",
                "schedule": "Удалённо",
                "url": item.get("url", ""),
                "description": desc,
                "published": item.get("publication_date", "")[:10],
                "remote": True,
            })
        logger.info(f"Remotive: got {len(jobs)} jobs")
        return jobs
    except Exception as e:
        logger.error(f"Remotive fetch error: {e}")
        return []


# ─── WeWorkRemotely ───

async def fetch_wwr(query: str = "") -> list[dict]:
    """Вакансии с WeWorkRemotely через RSS."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://weworkremotely.com/remote-jobs.rss",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                content = await resp.read()

        feed = feedparser.parse(content)
        jobs = []
        query_lower = query.lower()

        for entry in feed.entries[:50]:
            title = entry.get("title", "")
            summary = entry.get("summary", "")

            # Фильтр по запросу
            if query_lower and query_lower not in title.lower() and query_lower not in summary.lower():
                continue

            job_id = hashlib.md5(entry.get("link", title).encode()).hexdigest()[:12]

            import re
            desc = re.sub(r'<[^>]+>', ' ', summary)
            desc = re.sub(r'\s+', ' ', desc).strip()[:400]

            # Парсим компанию из title (обычно "Company: Title")
            parts = title.split(": ", 1)
            company = parts[0] if len(parts) > 1 else ""
            title_clean = parts[1] if len(parts) > 1 else title

            jobs.append({
                "id": _make_id("wwr", job_id),
                "source": "WeWorkRemotely",
                "title": title_clean,
                "company": company,
                "location": "Remote",
                "salary": "",
                "experience": "",
                "schedule": "Удалённо",
                "url": entry.get("link", ""),
                "description": desc,
                "published": "",
                "remote": True,
            })

        logger.info(f"WWR: got {len(jobs)} jobs")
        return jobs[:15]
    except Exception as e:
        logger.error(f"WWR fetch error: {e}")
        return []


# ─── Habr Career ───

async def fetch_habr(query: str, per_page: int = 10) -> list[dict]:
    """Вакансии с Habr Career."""
    try:
        params = {"q": query, "type": "all"}
        headers = {"User-Agent": HH_USER_AGENT, "Accept": "application/json"}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://career.habr.com/api/frontend/vacancies",
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Habr returned {resp.status}")
                    return []
                data = await resp.json()

        jobs = []
        for item in data.get("list", [])[:per_page]:
            salary = item.get("salary", {})
            salary_str = ""
            if salary:
                s_from = salary.get("from")
                s_to = salary.get("to")
                currency = salary.get("currency", "RUB")
                if s_from and s_to:
                    salary_str = f"{s_from:,}–{s_to:,} {currency}"
                elif s_from:
                    salary_str = f"от {s_from:,} {currency}"
                elif s_to:
                    salary_str = f"до {s_to:,} {currency}"

            jobs.append({
                "id": _make_id("habr", item.get("id", "")),
                "source": "Habr Career",
                "title": item.get("title", ""),
                "company": item.get("company", {}).get("title", ""),
                "location": item.get("location", {}).get("title", "Россия"),
                "salary": salary_str,
                "experience": item.get("qualification", ""),
                "schedule": "Удалённо" if item.get("remoteWork") else "Офис",
                "url": f"https://career.habr.com/vacancies/{item.get('id', '')}",
                "description": item.get("description", "")[:400],
                "published": item.get("publishedAt", "")[:10],
                "remote": bool(item.get("remoteWork")),
            })

        logger.info(f"Habr: got {len(jobs)} jobs")
        return jobs
    except Exception as e:
        logger.error(f"Habr fetch error: {e}")
        return []


# ─── Агрегатор ───

async def fetch_all_jobs(
    query: str,
    sources: list[str] = None,
    salary_from: int = None,
    remote_only: bool = False,
    experience: str = None,
    area: str = "113",  # Россия
) -> list[dict]:
    """Собрать вакансии из всех источников."""
    if sources is None:
        sources = ["hh", "remotive", "wwr", "habr"]

    tasks = []
    if "hh" in sources:
        tasks.append(fetch_hh(query, area=area, salary_from=salary_from, experience=experience))
    if "remotive" in sources:
        tasks.append(fetch_remotive(query))
    if "wwr" in sources:
        tasks.append(fetch_wwr(query))
    if "habr" in sources:
        tasks.append(fetch_habr(query))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_jobs = []
    for result in results:
        if isinstance(result, list):
            all_jobs.extend(result)
        elif isinstance(result, Exception):
            logger.error(f"Job fetch error: {result}")

    # Фильтр по формату
    if remote_only:
        all_jobs = [j for j in all_jobs if j.get("remote")]

    return all_jobs
