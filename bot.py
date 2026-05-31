"""
🎯 Huntly — AI охотник за IT-вакансиями
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand, CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, Message
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import database as db
from agent import chat
from config import TELEGRAM_TOKEN
from scheduler import setup_scheduler, run_job_search_for_user

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ─── Helpers ───

async def agent_reply(message: Message, text: str):
    try:
        await bot.send_chat_action(message.chat.id, "typing")
        user = await db.get_user(message.from_user.id)
        name = (user or {}).get("first_name") or message.from_user.first_name or "коллега"
        history = await db.get_chat_history(message.from_user.id)

        response = await chat(
            user_id=message.from_user.id,
            message=text,
            history=history,
            user_name=name,
        )
        await db.save_message(message.from_user.id, "user", text[:500])
        await db.save_message(message.from_user.id, "assistant", response[:1000])

        if len(response) > 4000:
            for part in [response[i:i+4000] for i in range(0, len(response), 4000)]:
                await message.answer(part, parse_mode="Markdown", disable_web_page_preview=True)
        else:
            await message.answer(response, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"agent_reply error: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)[:200]}")


def main_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔍 Найти вакансии сейчас", callback_data="search_now"))
    builder.add(InlineKeyboardButton(text="👤 Мой профиль", callback_data="my_profile"))
    builder.add(InlineKeyboardButton(text="⭐ Сохранённые", callback_data="saved"))
    builder.add(InlineKeyboardButton(text="📊 Статистика", callback_data="stats"))
    builder.add(InlineKeyboardButton(text="⚙️ Настроить поиск", callback_data="settings"))
    builder.adjust(1)
    return builder.as_markup()


# ─── Commands ───

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await db.ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    user = await db.get_user(message.from_user.id)
    name = message.from_user.first_name or "коллега"

    if user and user.get("skills"):
        level = user.get("experience_level", "middle")
        skills = (user.get("skills") or "")[:50]
        await message.answer(
            f"👋 С возвращением, *{name}*!\n\n"
            f"📋 Профиль: *{level}*, навыки: _{skills}_\n\n"
            "Что делаем?",
            parse_mode="Markdown",
            reply_markup=main_keyboard(),
        )
    else:
        await message.answer(
            f"🎯 Привет, *{name}*! Я *Huntly* — твой AI-помощник в поиске IT-работы.\n\n"
            "Ищу вакансии на:\n"
            "🟡 HH.ru · 🟣 Habr Career\n"
            "🟢 Remotive · 🔵 WeWorkRemotely\n"
            "💼 LinkedIn · 🌐 Indeed и другие\n\n"
            "Фильтрую по твоим навыкам, зарплате и формату.\n"
            "Анализирую каждую вакансию — подходит ли тебе.\n\n"
            "Чтобы начать — расскажи о себе:\n"
            "_«Я Python-разработчик, 3 года опыта, ищу удалёнку от 150к»_",
            parse_mode="Markdown",
        )


@dp.message(Command("search"))
async def cmd_search(message: Message):
    await db.ensure_user(message.from_user.id)
    user = await db.get_user(message.from_user.id)
    if not user or not user.get("skills"):
        await message.answer(
            "⚠️ Сначала расскажи о себе чтобы я знал что искать!\n\n"
            "Напиши например: _«Я Python разработчик, 3 года опыта, ищу удалёнку»_",
            parse_mode="Markdown"
        )
        return

    await message.answer("🔍 Ищу вакансии для тебя... Это займёт 30-60 секунд ⏳")
    count = await run_job_search_for_user(bot, user)
    if count == 0:
        await message.answer(
            "😔 Новых подходящих вакансий не найдено.\n\n"
            "Попробуй:\n"
            "• Расширить список навыков\n"
            "• Снизить минимальную зарплату\n"
            "• Изменить формат работы\n\n"
            "Или используй /ask для ручного поиска!"
        )


@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    await db.ensure_user(message.from_user.id)
    user = await db.get_user(message.from_user.id)
    if not user or not user.get("skills"):
        await message.answer("👤 Профиль не заполнен. Расскажи о себе!")
        return

    format_icons = {"remote": "🏠", "office": "🏢", "hybrid": "🔄", "any": "🌐"}
    level_icons = {"intern": "🌱", "junior": "🟢", "middle": "🔵", "senior": "🟣", "lead": "⭐"}

    work_format = user.get("work_format", "any")
    level = user.get("experience_level", "middle")
    salary_min = user.get("desired_salary_min")
    salary_max = user.get("desired_salary_max")
    currency = user.get("salary_currency", "RUB")

    salary_str = ""
    if salary_min and salary_max:
        salary_str = f"{salary_min:,}–{salary_max:,} {currency}"
    elif salary_min:
        salary_str = f"от {salary_min:,} {currency}"

    lines = [
        "👤 *Твой профиль поиска:*\n",
        f"{level_icons.get(level, '💼')} Уровень: *{level}* ({user.get('experience_years', 0)} лет опыта)",
        f"🛠 Навыки: _{user.get('skills', '')}_ ",
    ]
    if user.get("job_titles"):
        lines.append(f"💼 Должности: _{user['job_titles']}_")
    if salary_str:
        lines.append(f"💰 Зарплата: *{salary_str}*")
    lines.append(f"{format_icons.get(work_format, '🌐')} Формат: *{work_format}*")
    if user.get("location"):
        lines.append(f"📍 Локация: *{user['location']}*")
    if user.get("blacklist"):
        lines.append(f"🚫 Чёрный список: _{user['blacklist']}_")

    await message.answer("\n".join(lines), parse_mode="Markdown")


@dp.message(Command("saved"))
async def cmd_saved(message: Message):
    await db.ensure_user(message.from_user.id)
    jobs = await db.get_saved_jobs(message.from_user.id)
    if not jobs:
        await message.answer("⭐ Сохранённых вакансий нет.\nНайди вакансии через /search!")
        return

    await message.answer(f"⭐ *Сохранённые вакансии* ({len(jobs)} шт.):", parse_mode="Markdown")
    for job in jobs[:8]:
        score = job.get("score", 0)
        applied = "✅ Откликнулся" if job.get("applied") else ""
        text = (
            f"*{job['title']}* — {job.get('company', '')}\n"
            f"💰 {job.get('salary', 'не указана')} | {'⭐' * min(score, 5)}\n"
            f"{applied}"
        )
        if job.get("url"):
            text += f"\n[Открыть]({job['url']})"
        await message.answer(text, parse_mode="Markdown", disable_web_page_preview=True)


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    await db.ensure_user(message.from_user.id)
    stats = await db.get_stats(message.from_user.id)
    await message.answer(
        "📊 *Твоя статистика поиска:*\n\n"
        f"👁 Показано вакансий: *{stats['total_shown']}*\n"
        f"⭐ Сохранено: *{stats['saved']}*\n"
        f"📨 Откликов: *{stats['applied']}*\n"
        f"📈 Средний балл совпадения: *{stats['avg_match_score']}/10*",
        parse_mode="Markdown"
    )


@dp.message(Command("ask"))
async def cmd_ask(message: Message):
    await message.answer(
        "💬 *Ручной поиск*\n\n"
        "Напиши что ищешь и я найду + проанализирую вакансии:\n\n"
        "• _«Найди Senior Python вакансии с зарплатой от 250к»_\n"
        "• _«Ищу удалённую работу фронтенд разработчика»_\n"
        "• _«Подбери вакансии на LinkedIn для DevOps»_",
        parse_mode="Markdown"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🎯 *Huntly — AI охотник за IT-вакансиями*\n\n"
        "📋 *Команды:*\n"
        "/search — запустить поиск вакансий сейчас\n"
        "/profile — мой профиль поиска\n"
        "/saved — сохранённые вакансии\n"
        "/stats — статистика\n"
        "/ask — ручной поиск\n"
        "/help — помощь\n\n"
        "💬 *Просто пиши:*\n"
        "• «Обнови мои навыки: Python, FastAPI, Docker»\n"
        "• «Ищу удалёнку от 200к»\n"
        "• «Проанализируй эту вакансию» + ссылка/текст\n"
        "• «Напиши сопроводительное письмо для этой вакансии»\n"
        "• «Найди фронтенд вакансии на Wellfound»",
        parse_mode="Markdown"
    )


# ─── Callbacks ───

@dp.callback_query(F.data == "search_now")
async def cb_search(callback: CallbackQuery):
    await callback.answer()
    user = await db.get_user(callback.from_user.id)
    if not user or not user.get("skills"):
        await callback.message.answer("⚠️ Сначала заполни профиль — расскажи о своих навыках!")
        return
    await callback.message.answer("🔍 Ищу вакансии... ⏳")
    count = await run_job_search_for_user(bot, user)
    if count == 0:
        await callback.message.answer("😔 Новых вакансий не найдено. Попробуй /ask для ручного поиска.")


@dp.callback_query(F.data == "my_profile")
async def cb_profile(callback: CallbackQuery):
    await callback.answer()
    msg = callback.message
    msg.from_user = callback.from_user
    await cmd_profile(msg)


@dp.callback_query(F.data == "saved")
async def cb_saved(callback: CallbackQuery):
    await callback.answer()
    msg = callback.message
    msg.from_user = callback.from_user
    await cmd_saved(msg)


@dp.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery):
    await callback.answer()
    stats = await db.get_stats(callback.from_user.id)
    await callback.message.answer(
        f"📊 Показано: *{stats['total_shown']}* | Сохранено: *{stats['saved']}* | "
        f"Откликов: *{stats['applied']}*",
        parse_mode="Markdown"
    )


@dp.callback_query(F.data == "settings")
async def cb_settings(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "⚙️ *Настройки поиска*\n\n"
        "Напиши что хочешь изменить:\n\n"
        "• «Навыки: Python, Go, Kubernetes»\n"
        "• «Зарплата от 200к до 350к рублей»\n"
        "• «Только удалённая работа»\n"
        "• «Уровень: senior»\n"
        "• «Локация: Москва»\n"
        "• «Добавь в чёрный список: Рога и Копыта»",
        parse_mode="Markdown"
    )


# ─── Резюме (документ) ───

@dp.message(F.document)
async def handle_document(message: Message):
    await db.ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    doc = message.document
    filename = doc.file_name or "resume.pdf"
    allowed_ext = (".pdf", ".docx", ".txt", ".doc")

    if not any(filename.lower().endswith(ext) for ext in allowed_ext):
        await message.answer("Поддерживаемые форматы: PDF, DOCX, TXT")
        return

    await bot.send_chat_action(message.chat.id, "typing")
    await message.answer("📄 Читаю резюме... ⏳")

    try:
        file = await bot.get_file(doc.file_id)
        file_bytes_io = await bot.download_file(file.file_path)
        file_bytes = file_bytes_io.read()

        from resume_parser import extract_text
        resume_text = await extract_text(file_bytes, filename)

        if not resume_text or len(resume_text) < 100:
            await message.answer("Не удалось прочитать файл. Попробуй DOCX или вставь текст в чат.")
            return

        await db.update_profile(message.from_user.id, resume_text=resume_text)

        from anthropic import AsyncAnthropic
        import json as json_module
        import re as re_module
        client = AsyncAnthropic()

        prompt_text = (
            "Проанализируй резюме IT-специалиста. Извлеки:\n"
            "skills (топ-10 навыков через запятую), level (junior/middle/senior/lead), "
            "years (число лет опыта), titles (должности), summary (2 предложения о специалисте).\n\n"
            "Резюме:\n" + resume_text[:3000] + "\n\n"
            "Ответь ТОЛЬКО валидным JSON без других слов."
        )

        resp = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt_text}]
        )
        resp_text = resp.content[0].text
        match = re_module.search(r'\{[^{}]+\}', resp_text, re_module.DOTALL)

        if match:
            data = json_module.loads(match.group())
            years_raw = str(data.get("years", 0)).replace("+", "").strip()
            years = int(years_raw) if years_raw.isdigit() else 0
            await db.update_profile(
                message.from_user.id,
                skills=data.get("skills", ""),
                experience_level=data.get("level", "middle"),
                experience_years=years,
                job_titles=data.get("titles", ""),
            )
            reply_text = (
                "*Резюме загружено и проанализировано!* ✅\n\n"
                "Навыки: _" + str(data.get("skills", "")) + "_\n"
                "Уровень: *" + str(data.get("level", "")) + "* (" + str(years) + " лет)\n"
                "Должности: _" + str(data.get("titles", "")) + "_\n\n"
                "_" + str(data.get("summary", "")) + "_\n\n"
                "Теперь ищу вакансии именно под тебя!\n"
                "Нажми /search чтобы найти первые."
            )
            await message.answer(reply_text, parse_mode="Markdown")
        else:
            await message.answer("Резюме сохранено! Используй /search для поиска.")

    except Exception as e:
        logger.error(f"Resume upload error: {e}", exc_info=True)
        await message.answer("Ошибка при обработке файла. Вставь текст резюме прямо в чат!")



# ─── Текст ───

@dp.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    await db.ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await agent_reply(message, message.text)


# ─── Startup ───

async def set_bot_commands():
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать"),
        BotCommand(command="search", description="🔍 Найти вакансии сейчас"),
        BotCommand(command="profile", description="👤 Мой профиль поиска"),
        BotCommand(command="saved", description="⭐ Сохранённые вакансии"),
        BotCommand(command="stats", description="📊 Статистика поиска"),
        BotCommand(command="ask", description="💬 Ручной поиск"),
        BotCommand(command="help", description="Помощь"),
    ])


async def main():
    await db.init_db()
    await set_bot_commands()
    setup_scheduler(bot)
    logger.info("🎯 Huntly Bot started!")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
