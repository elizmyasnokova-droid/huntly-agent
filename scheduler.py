"""
Scheduler — периодический поиск и отправка вакансий.
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from config import TIMEZONE
import database as db

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone=TIMEZONE)


def _format_job_message(job: dict, score: int, analysis: str) -> str:
    """Форматировать сообщение о вакансии."""
    source_icons = {
        "HH.ru": "🟡", "Remotive": "🟢", "WeWorkRemotely": "🔵",
        "Habr Career": "🟣", "LinkedIn": "💼"
    }
    icon = source_icons.get(job.get("source", ""), "💼")
    score_bar = "🟩" * (score // 2) + "⬜" * (5 - score // 2)

    lines = [
        f"{icon} *{job['title']}*",
        f"🏢 {job.get('company', 'Компания не указана')}",
    ]
    if job.get("salary"):
        lines.append(f"💰 {job['salary']}")
    if job.get("location"):
        lines.append(f"📍 {job['location']}")
    if job.get("schedule"):
        lines.append(f"🕐 {job['schedule']}")

    lines.append(f"\n{score_bar} Соответствие: *{score}/10*")

    if analysis:
        lines.append(f"\n{analysis[:300]}")

    if job.get("url"):
        lines.append(f"\n[Открыть вакансию]({job['url']})")

    return "\n".join(lines)


async def analyze_job_for_user(job: dict, user: dict) -> tuple[int, str]:
    """Оценить вакансию относительно резюме и профиля пользователя."""
    from anthropic import AsyncAnthropic
    import json as _json
    import re as _re
    client = AsyncAnthropic()

    skills = user.get("skills", "")
    level = user.get("experience_level", "middle")
    salary_min = user.get("desired_salary_min", 0) or 0
    work_format = user.get("work_format", "any")
    resume_text = user.get("resume_text", "")

    if resume_text and len(resume_text) > 200:
        candidate_info = (
            "Резюме кандидата:\n" + resume_text[:1500] + "\n\n"
            "Уровень: " + level + ", формат: " + work_format +
            ", мин. зарплата: " + str(salary_min)
        )
    else:
        candidate_info = (
            "Кандидат: " + level + ", навыки: " + skills +
            ", зарплата от " + str(salary_min) + ", формат: " + work_format
        )

    job_info = (
        "Вакансия: " + job.get("title", "") + "\n"
        "Компания: " + job.get("company", "") + "\n"
        "Зарплата: " + (job.get("salary") or "не указана") + "\n"
        "Опыт: " + job.get("experience", "") + "\n"
        "Формат: " + job.get("schedule", "") + "\n"
        "Описание: " + job.get("description", "")[:600]
    )

    prompt = (
        candidate_info + "\n\n"
        "Оцени насколько эта вакансия подходит кандидату:\n" +
        job_info + "\n\n"
        "Ответь ТОЛЬКО JSON:\n"
        '{"score": 7, "summary": "Вывод в 1-2 предложения"}\n'
        "score: 1=совсем не подходит, 10=идеально"
    )

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        match = _re.search(r'\{[^{}]+\}', text, _re.DOTALL)
        if match:
            data = _json.loads(match.group())
            return int(data.get("score", 5)), str(data.get("summary", ""))
    except Exception as e:
        logger.warning(f"Job analysis error: {e}")

    return 5, ""


async def run_job_search_for_user(bot, user: dict):
    """Запустить поиск вакансий для конкретного пользователя."""
    from job_fetcher import fetch_all_jobs

    user_id = user["user_id"]
    skills = user.get("skills", "")
    job_titles = user.get("job_titles", "") or skills.split(",")[0].strip()
    salary_from = user.get("desired_salary_min")
    work_format = user.get("work_format", "any")
    blacklist = [b.strip().lower() for b in (user.get("blacklist") or "").split(",") if b.strip()]

    # Определяем уровень опыта для HH.ru
    level_map = {
        "intern": "noExperience",
        "junior": "between1And3",
        "middle": "between3And6",
        "senior": "moreThan6",
        "lead": "moreThan6",
    }
    experience = level_map.get(user.get("experience_level", "middle"), "between3And6")

    query = job_titles or "Python разработчик"
    remote_only = work_format == "remote"

    jobs = await fetch_all_jobs(
        query=query,
        salary_from=salary_from,
        remote_only=remote_only,
        experience=experience,
    )

    sent_count = 0
    for job in jobs:
        # Пропускаем уже отправленные
        if await db.is_job_sent(user_id, job["id"]):
            continue

        # Фильтр по чёрному списку
        job_text = f"{job.get('title','')} {job.get('company','')}".lower()
        if any(bl in job_text for bl in blacklist if bl):
            continue

        # Анализируем вакансию
        score, summary = await analyze_job_for_user(job, user)

        # Отправляем только хорошие вакансии (score >= 5)
        if score < 5:
            await db.mark_job_sent(user_id, job["id"], job["source"], job["title"], job["company"], score)
            continue

        # Формируем и отправляем сообщение
        message = _format_job_message(job, score, summary)
        try:
            await bot.send_message(
                user_id, message,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            await db.mark_job_sent(user_id, job["id"], job["source"], job["title"], job["company"], score)
            sent_count += 1

            if sent_count >= 5:  # Не более 5 вакансий за раз
                break

        except Exception as e:
            logger.warning(f"Failed to send job to {user_id}: {e}")

    if sent_count > 0:
        logger.info(f"Sent {sent_count} jobs to user {user_id}")
    return sent_count


async def search_all_users(bot):
    """Поиск вакансий для всех активных пользователей."""
    users = await db.get_active_users()
    logger.info(f"Job search for {len(users)} users")
    for user in users:
        try:
            await run_job_search_for_user(bot, user)
        except Exception as e:
            logger.error(f"Search failed for user {user['user_id']}: {e}")


def setup_scheduler(bot):
    # Поиск вакансий каждые 6 часов
    scheduler.add_job(
        search_all_users,
        IntervalTrigger(hours=6),
        args=[bot],
        id="job_search",
        replace_existing=True,
    )
    # Утренний дайджест в 9:00
    scheduler.add_job(
        search_all_users,
        CronTrigger(hour=9, minute=0),
        args=[bot],
        id="morning_digest",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler: поиск вакансий каждые 6 часов + утром в 9:00")
    return scheduler
