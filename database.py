"""
Database — профили, вакансии, история отправок.
"""
import json
import aiosqlite
from datetime import datetime
from typing import Optional
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id         INTEGER PRIMARY KEY,
                username        TEXT,
                first_name      TEXT,
                skills          TEXT,
                experience_years INTEGER DEFAULT 0,
                experience_level TEXT DEFAULT 'junior',
                desired_salary_min INTEGER,
                desired_salary_max INTEGER,
                salary_currency  TEXT DEFAULT 'RUB',
                work_format      TEXT DEFAULT 'any',
                location         TEXT,
                languages        TEXT DEFAULT 'ru',
                job_titles       TEXT,
                blacklist        TEXT,
                resume_text      TEXT,
                active           INTEGER DEFAULT 1,
                search_interval  INTEGER DEFAULT 360,
                created_at       TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sent_jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                job_id      TEXT NOT NULL,
                source      TEXT NOT NULL,
                title       TEXT,
                company     TEXT,
                score       INTEGER DEFAULT 0,
                applied     INTEGER DEFAULT 0,
                saved       INTEGER DEFAULT 0,
                sent_at     TEXT DEFAULT (datetime('now')),
                UNIQUE(user_id, job_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS saved_jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                job_id      TEXT NOT NULL,
                source      TEXT,
                title       TEXT,
                company     TEXT,
                url         TEXT,
                salary      TEXT,
                description TEXT,
                score       INTEGER DEFAULT 0,
                notes       TEXT,
                applied     INTEGER DEFAULT 0,
                saved_at    TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        await db.commit()


# ─── Users ───

async def ensure_user(user_id: int, username: str = None, first_name: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?,?,?)",
            (user_id, username, first_name)
        )
        await db.commit()


async def get_user(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as c:
            row = await c.fetchone()
    return dict(row) if row else None


async def update_profile(user_id: int, **fields):
    allowed = {
        "skills", "experience_years", "experience_level", "desired_salary_min",
        "desired_salary_max", "salary_currency", "work_format", "location",
        "languages", "job_titles", "blacklist", "resume_text", "active", "search_interval"
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return
    set_clause = ", ".join(f"{k}=?" for k in updates)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE users SET {set_clause} WHERE user_id=?",
            [*updates.values(), user_id]
        )
        await db.commit()


async def get_active_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE active=1 AND skills IS NOT NULL"
        ) as c:
            rows = await c.fetchall()
    return [dict(r) for r in rows]


# ─── Sent jobs (дедупликация) ───

async def is_job_sent(user_id: int, job_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM sent_jobs WHERE user_id=? AND job_id=?",
            (user_id, job_id)
        ) as c:
            return await c.fetchone() is not None


async def mark_job_sent(user_id: int, job_id: str, source: str,
                         title: str = None, company: str = None, score: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT OR IGNORE INTO sent_jobs (user_id, job_id, source, title, company, score) VALUES (?,?,?,?,?,?)",
                (user_id, job_id, source, title, company, score)
            )
            await db.commit()
        except Exception:
            pass


async def get_sent_count(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM sent_jobs WHERE user_id=?", (user_id,)
        ) as c:
            return (await c.fetchone())[0]


# ─── Saved jobs ───

async def save_job(user_id: int, job_id: str, source: str, title: str,
                    company: str, url: str, salary: str, description: str, score: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO saved_jobs
               (user_id, job_id, source, title, company, url, salary, description, score)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, job_id, source, title, company, url, salary, description, score)
        )
        await db.commit()


async def get_saved_jobs(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM saved_jobs WHERE user_id=? ORDER BY score DESC, saved_at DESC",
            (user_id,)
        ) as c:
            rows = await c.fetchall()
    return [dict(r) for r in rows]


async def mark_applied(user_id: int, job_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE saved_jobs SET applied=1 WHERE user_id=? AND job_id=?",
            (user_id, job_id)
        )
        await db.execute(
            "UPDATE sent_jobs SET applied=1 WHERE user_id=? AND job_id=?",
            (user_id, job_id)
        )
        await db.commit()


async def get_stats(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM sent_jobs WHERE user_id=?", (user_id,)
        ) as c:
            total_shown = (await c.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM saved_jobs WHERE user_id=?", (user_id,)
        ) as c:
            saved = (await c.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM saved_jobs WHERE user_id=? AND applied=1", (user_id,)
        ) as c:
            applied = (await c.fetchone())[0]
        async with db.execute(
            "SELECT AVG(score) FROM sent_jobs WHERE user_id=? AND score > 0", (user_id,)
        ) as c:
            avg_score = (await c.fetchone())[0] or 0
    return {
        "total_shown": total_shown,
        "saved": saved,
        "applied": applied,
        "avg_match_score": round(avg_score, 1),
    }


# ─── Chat history ───

async def get_chat_history(user_id: int, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT role, content FROM chat_history WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ) as c:
            rows = await c.fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def save_message(user_id: int, role: str, content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?,?,?)",
            (user_id, role, content)
        )
        await db.execute(
            """DELETE FROM chat_history WHERE user_id=? AND id NOT IN
               (SELECT id FROM chat_history WHERE user_id=? ORDER BY created_at DESC LIMIT 40)""",
            (user_id, user_id)
        )
        await db.commit()
