import asyncio
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

# ---------- setup ----------
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_PATH = os.getenv("LOG_PATH", os.path.join(BASE_DIR, "bot.log"))
LOG_MAX_BYTES = 5_000_000
LOG_BACKUPS = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            LOG_PATH,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUPS,
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env file")

DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "bot.db"))
BACKUP_DIR = os.getenv("BACKUP_DIR", os.path.join(BASE_DIR, "backups"))
BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "7"))

# rate cache: {"value": float | None, "date": "YYYY-MM-DD" | None}
rate_cache: dict = {"value": None, "date": None}

# in-memory mirror of the DB for fast broadcast lookups: {user_id: "Europe/Moscow"}
user_timezones: dict[int, str] = {}

# single shared DB connection, opened in main()
_db: aiosqlite.Connection | None = None

REFRESH_TZ = ZoneInfo("Europe/Moscow")
REFRESH_HOUR = 5
REFRESH_MINUTE = 0

BACKUP_HOUR = 3
BACKUP_MINUTE = 0

SEND_DELAY = 0.5

_broadcast_lock = asyncio.Lock()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()


class UserState(StatesGroup):
    waiting_for_timezone = State()


# ---------- db helpers ----------
def db() -> aiosqlite.Connection:
    """Return the active DB connection or raise if not initialized."""
    if _db is None:
        raise RuntimeError("Database is not initialized")
    return _db


# ---------- database ----------
async def db_init() -> None:
    """Open the connection and create the users table if missing."""
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id    INTEGER PRIMARY KEY,
            timezone   TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    await _db.commit()
    logger.info("Database initialized at %s", DB_PATH)


async def db_close() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("Database connection closed")


async def db_load_users() -> dict[int, str]:
    async with db().execute("SELECT user_id, timezone FROM users") as cursor:
        rows = await cursor.fetchall()
    return {int(row["user_id"]): row["timezone"] for row in rows}


async def db_upsert_user(user_id: int, tz_name: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await db().execute(
        """
        INSERT INTO users (user_id, timezone, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            timezone   = excluded.timezone,
            updated_at = excluded.updated_at
        """,
        (user_id, tz_name, now, now),
    )
    await db().commit()


async def db_delete_user(user_id: int) -> None:
    await db().execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    await db().commit()


async def db_backup() -> None:
    """Create a consistent snapshot of the SQLite database using the backup API."""
    if _db is None:
        logger.warning("Backup skipped: DB not initialized")
        return
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(BACKUP_DIR, f"bot_{stamp}.db.bak")

        # online backup API: consistent snapshot, safe under WAL
        target = await aiosqlite.connect(dst)
        try:
            await _db.backup(target)
        finally:
            await target.close()

        logger.info("Database backed up to %s", dst)
        _prune_backups()
    except Exception:
        logger.exception("Database backup failed")


def _prune_backups() -> None:
    """Keep only the newest BACKUP_KEEP files in BACKUP_DIR."""
    try:
        files = sorted(
            (
                f for f in os.listdir(BACKUP_DIR)
                if f.startswith("bot_") and f.endswith(".db.bak")
            ),
            reverse=True,
        )
        for old in files[BACKUP_KEEP:]:
            try:
                os.remove(os.path.join(BACKUP_DIR, old))
                logger.info("Removed old backup %s", old)
            except OSError:
                logger.warning("Failed to remove old backup %s", old)
    except FileNotFoundError:
        pass


# ---------- rate fetching ----------
async def fetch_usd_rub() -> float | None:
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": "usd-coin", "vs_currencies": "rub"}
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=timeout) as resp:
                if resp.status != 200:
                    logger.warning("CoinGecko returned status %s", resp.status)
                    return None
                data = await resp.json()
                return data.get("usd-coin", {}).get("rub")
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error("Failed to fetch rate: %s", e)
        return None


async def refresh_rate_cache() -> None:
    rate = await fetch_usd_rub()
    if rate is None:
        logger.warning("Rate cache refresh skipped: no data")
        return
    now_msk = datetime.now(timezone.utc).astimezone(REFRESH_TZ)
    rate_cache["value"] = rate
    rate_cache["date"] = now_msk.strftime("%d.%m.%Y")
    logger.info("Rate cache refreshed: %.2f RUB on %s", rate, rate_cache["date"])


async def build_rate_message() -> str:
    today = datetime.now(timezone.utc).astimezone(REFRESH_TZ).strftime("%d.%m.%Y")
    if rate_cache["value"] is None or rate_cache["date"] != today:
        await refresh_rate_cache()

    if rate_cache["value"] is None:
        return "⚠️ Не удалось получить актуальный курс. Попробуйте позже."

    return (
        f"💰 <b>Курс USD/RUB на {rate_cache['date']}</b>\n\n"
        f"Текущий курс: <b>{rate_cache['value']:.2f} ₽</b>"
    )


# ---------- sending ----------
async def send_to_user(user_id: int, text: str) -> bool:
    try:
        await bot.send_message(user_id, text, parse_mode="HTML")
        return True
    except TelegramRetryAfter as e:
        logger.warning("Rate limited, waiting %ss for user %s", e.retry_after, user_id)
        await asyncio.sleep(e.retry_after)
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
            return True
        except Exception as e2:
            logger.error("Retry failed for %s: %s", user_id, e2)
            return False
    except TelegramForbiddenError:
        user_timezones.pop(user_id, None)
        await db_delete_user(user_id)
        logger.info("User %s blocked the bot, removed", user_id)
        return False
    except Exception as e:
        logger.error("Failed to send to %s: %s", user_id, e)
        return False


async def broadcast_to_timezone(tz_name: str) -> None:
    async with _broadcast_lock:
        recipients = [uid for uid, tz in user_timezones.items() if tz == tz_name]
        if not recipients:
            logger.info("No recipients in %s, skipping", tz_name)
            return

        text = await build_rate_message()
        logger.info("Broadcasting to %d users in %s", len(recipients), tz_name)

        for i, user_id in enumerate(recipients):
            await send_to_user(user_id, text)
            if i < len(recipients) - 1:
                await asyncio.sleep(SEND_DELAY)

        logger.info("Broadcast to %s finished", tz_name)


# ---------- handlers ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    await message.answer(
        "👋 Я буду присылать курс доллара к рублю каждый день в 5:00 утра.\n\n"
        "Сначала укажи свой часовой пояс. Например: <code>Europe/Moscow</code>, "
        "<code>Europe/Kyiv</code> или <code>Asia/Yekaterinburg</code>.",
        parse_mode="HTML",
    )


@dp.message(F.text)
async def handle_timezone(message: types.Message, state: FSMContext) -> None:
    tz_input = (message.text or "").strip()

    if tz_input.startswith("/"):
        await message.answer(
            "Пожалуйста, введите часовой пояс, например: <code>Europe/Moscow</code>",
            parse_mode="HTML",
        )
        return

    try:
        tz = ZoneInfo(tz_input)
    except Exception:
        await message.answer(
            "❌ Не удалось распознать часовой пояс. Попробуйте еще раз, например: "
            "<code>Europe/Moscow</code>",
            parse_mode="HTML",
        )
        return

    user_id = message.from_user.id
    user_timezones[user_id] = tz_input
    await db_upsert_user(user_id, tz_input)

    # one job per timezone: idempotent, safe to call repeatedly
    scheduler.add_job(
        broadcast_to_timezone,
        trigger="cron",
        hour=REFRESH_HOUR,
        minute=REFRESH_MINUTE,
        args=[tz_input],
        id=f"tz_{tz_input}",
        replace_existing=True,
        timezone=tz,
    )

    await message.answer("✅ Часовой пояс сохранен!", parse_mode="HTML")


# ---------- main ----------
def restore_jobs_from_db() -> None:
    """Recreate one cron job per distinct timezone found in the DB."""
    tz_names = set(user_timezones.values())
    for tz_name in tz_names:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            logger.warning("Skipping unknown timezone from DB: %s", tz_name)
            continue
        scheduler.add_job(
            broadcast_to_timezone,
            trigger="cron",
            hour=REFRESH_HOUR,
            minute=REFRESH_MINUTE,
            args=[tz_name],
            id=f"tz_{tz_name}",
            replace_existing=True,
            timezone=tz,
        )
        logger.info("Restored job for timezone %s", tz_name)


async def main() -> None:
    global user_timezones

    # init DB and load users into memory
    await db_init()
    user_timezones = await db_load_users()
    logger.info("Loaded %d users from DB", len(user_timezones))

    # global daily rate refresh at 05:00 MSK
    scheduler.add_job(
        refresh_rate_cache,
        trigger="cron",
        hour=REFRESH_HOUR,
        minute=REFRESH_MINUTE,
        id="refresh_rate",
        replace_existing=True,
        timezone=REFRESH_TZ,
    )

    # daily DB backup at 03:00 MSK
    scheduler.add_job(
        db_backup,
        trigger="cron",
        hour=BACKUP_HOUR,
        minute=BACKUP_MINUTE,
        id="db_backup",
        replace_existing=True,
        timezone=REFRESH_TZ,
    )

    # restore per-timezone broadcasts
    restore_jobs_from_db()

    scheduler.start()

    # fill cache on startup
    await refresh_rate_cache()

    logger.info("Bot is running...")
    try:
        await dp.start_polling(bot)
    finally:
        # stop scheduling new jobs and wait for running ones to finish
        scheduler.shutdown(wait=True)
        await db_close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception:
        logger.exception("Fatal error")
        raise