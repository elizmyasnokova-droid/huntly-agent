"""
Huntly Agent — Claude как карьерный советник.
"""
import json
import logging
from anthropic import AsyncAnthropic
import database as db

logger = logging.getLogger(__name__)
client = AsyncAnthropic()

SYSTEM_PROMPT = """Ты — Huntly, умный карьерный советник и охотник за вакансиями в IT.
Ты помогаешь разработчикам находить идеальную работу.

════════════════════════════════════════
🎯 ТВОЯ РАБОТА
════════════════════════════════════════

1. **Настройка профиля** — помогаешь пользователю заполнить профиль:
   навыки, опыт, зарплатные ожидания, формат работы, локацию

2. **Поиск вакансий** — используешь инструменты для поиска на HH.ru,
   Remotive, WeWorkRemotely, Habr Career и через веб

3. **Анализ вакансии** — оцениваешь насколько вакансия подходит:
   • Совпадение навыков (%)
   • Соответствие зарплате
   • Уровень позиции
   • Красные флаги в описании

4. **Помощь с откликом** — составляешь сопроводительное письмо
   под конкретную вакансию и резюме пользователя

════════════════════════════════════════
📊 АНАЛИЗ ВАКАНСИИ
════════════════════════════════════════

При анализе вакансии давай структурированный ответ:

✅ **Соответствие**: X/10
📋 **Плюсы**: [список]
⚠️ **Минусы/риски**: [список]
💰 **Зарплата**: [оценка относительно рынка]
🚩 **Красные флаги**: [если есть]
📝 **Вывод**: [подходит/не подходит/стоит рассмотреть]

════════════════════════════════════════
💬 СТИЛЬ
════════════════════════════════════════

• Дружелюбный, как опытный коллега
• Конкретные советы, не общие фразы
• Честен если вакансия не подходит
• Мотивирует не сдаваться в поиске
• Отвечаешь на языке пользователя"""

TOOLS = [
    {
        "name": "get_profile",
        "description": "Получить профиль пользователя — навыки, опыт, требования",
        "input_schema": {
            "type": "object",
            "properties": {"user_id": {"type": "integer"}},
            "required": ["user_id"],
        },
    },
    {
        "name": "update_profile",
        "description": "Обновить профиль пользователя",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer"},
                "skills": {"type": "string", "description": "Навыки через запятую: Python, Django, PostgreSQL"},
                "experience_years": {"type": "integer"},
                "experience_level": {"type": "string", "enum": ["intern", "junior", "middle", "senior", "lead", "principal"]},
                "desired_salary_min": {"type": "integer", "description": "Минимальная зарплата"},
                "desired_salary_max": {"type": "integer", "description": "Максимальная зарплата"},
                "salary_currency": {"type": "string", "default": "RUB"},
                "work_format": {"type": "string", "enum": ["remote", "office", "hybrid", "any"]},
                "location": {"type": "string"},
                "languages": {"type": "string", "description": "Языки: ru, en"},
                "job_titles": {"type": "string", "description": "Желаемые должности через запятую"},
                "blacklist": {"type": "string", "description": "Компании/технологии которых избегать"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "search_jobs",
        "description": "Найти вакансии по запросу на всех платформах",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос (должность + навыки)"},
                "sources": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["hh", "remotive", "wwr", "habr"]},
                    "description": "Источники для поиска",
                },
                "salary_from": {"type": "integer"},
                "remote_only": {"type": "boolean", "default": False},
                "experience": {
                    "type": "string",
                    "enum": ["noExperience", "between1And3", "between3And6", "moreThan6"],
                },
                "area": {"type": "string", "description": "Код региона HH.ru (113=Россия, 1=Москва, 2=СПб)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "save_job",
        "description": "Сохранить вакансию в избранное пользователя",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer"},
                "job_id": {"type": "string"},
                "source": {"type": "string"},
                "title": {"type": "string"},
                "company": {"type": "string"},
                "url": {"type": "string"},
                "salary": {"type": "string"},
                "description": {"type": "string"},
                "score": {"type": "integer", "description": "Оценка соответствия 1-10"},
            },
            "required": ["user_id", "job_id", "title", "company"],
        },
    },
    {
        "name": "get_saved_jobs",
        "description": "Получить сохранённые вакансии пользователя",
        "input_schema": {
            "type": "object",
            "properties": {"user_id": {"type": "integer"}},
            "required": ["user_id"],
        },
    },
    {
        "name": "get_stats",
        "description": "Статистика поиска пользователя",
        "input_schema": {
            "type": "object",
            "properties": {"user_id": {"type": "integer"}},
            "required": ["user_id"],
        },
    },
    {
        "name": "web_search_jobs",
        "description": "Поиск вакансий через веб на LinkedIn, Indeed, Glassdoor и других сайтах",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос"},
                "site": {"type": "string", "description": "linkedin.com, indeed.com, glassdoor.com, wellfound.com, etc"},
            },
            "required": ["query"],
        },
    },
]


async def execute_tool(name: str, input_data: dict) -> str:
    try:
        if name == "get_profile":
            user = await db.get_user(input_data["user_id"])
            if not user or not user.get("skills"):
                return json.dumps({"message": "Профиль не заполнен. Нужно указать навыки и опыт."})
            return json.dumps(user, ensure_ascii=False, default=str)

        elif name == "update_profile":
            user_id = input_data.pop("user_id")
            await db.update_profile(user_id, **input_data)
            return json.dumps({"success": True, "message": "Профиль обновлён ✅"})

        elif name == "search_jobs":
            from job_fetcher import fetch_all_jobs
            jobs = await fetch_all_jobs(
                query=input_data["query"],
                sources=input_data.get("sources"),
                salary_from=input_data.get("salary_from"),
                remote_only=input_data.get("remote_only", False),
                experience=input_data.get("experience"),
                area=input_data.get("area", "113"),
            )
            if not jobs:
                return json.dumps({"message": "Вакансии не найдены. Попробуй другой запрос."})
            # Возвращаем первые 10 для анализа
            return json.dumps(jobs[:10], ensure_ascii=False, default=str)

        elif name == "save_job":
            user_id = input_data.pop("user_id")
            await db.save_job(
                user_id=user_id,
                job_id=input_data["job_id"],
                source=input_data.get("source", ""),
                title=input_data["title"],
                company=input_data["company"],
                url=input_data.get("url", ""),
                salary=input_data.get("salary", ""),
                description=input_data.get("description", ""),
                score=input_data.get("score", 0),
            )
            return json.dumps({"success": True, "message": f"Вакансия '{input_data['title']}' сохранена"})

        elif name == "get_saved_jobs":
            jobs = await db.get_saved_jobs(input_data["user_id"])
            if not jobs:
                return json.dumps({"message": "Сохранённых вакансий нет"})
            return json.dumps(jobs[:10], ensure_ascii=False, default=str)

        elif name == "get_stats":
            stats = await db.get_stats(input_data["user_id"])
            return json.dumps(stats, ensure_ascii=False)

        elif name == "web_search_jobs":
            # Используем веб-поиск через Claude
            site = input_data.get("site", "")
            site_str = f"site:{site} " if site else ""
            query = f"{site_str}{input_data['query']} вакансия IT jobs 2025"
            return json.dumps({
                "query": query,
                "message": f"Выполни поиск: {query} — найди актуальные вакансии и опиши их"
            })

        return f"Инструмент '{name}' не найден"
    except Exception as e:
        logger.error(f"Tool '{name}' error: {e}", exc_info=True)
        return json.dumps({"error": str(e)})


async def chat(
    user_id: int,
    message: str,
    history: list[dict],
    user_name: str = None,
) -> str:
    name = user_name or "коллега"
    system = (
        SYSTEM_PROMPT
        + f"\n\n[ПОЛЬЗОВАТЕЛЬ: имя={name}, user_id={user_id}]"
        "\nОбращайся по имени. Используй user_id во всех инструментах."
        "\nПомни историю разговора."
    )

    messages = history + [{"role": "user", "content": message}]

    for _ in range(6):
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            return "".join(b.text for b in response.content if hasattr(b, "text")).strip()

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info(f"Tool: {block.name}")
                    result = await execute_tool(block.name, block.input)
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    return "Произошла ошибка. Попробуй ещё раз."
