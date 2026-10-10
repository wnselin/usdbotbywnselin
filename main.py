import asyncio
import os
import aiohttp
import pytz
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

# load environment variables
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env file")

# in-memory storage: {user_id: "Europe/Moscow"}
user_timezones: dict[int, str] = {}

# rate cache: {"value": float | None, "date": "YYYY-MM-DD" | None}
rate_cache: dict = {"value": None, "date": None}

# refresh schedule is anchored to this timezone
REFRESH_TZ = pytz.timezone("Europe/Moscow")
REFRESH_HOUR = 5
REFRESH_MINUTE = 0

# delay between outgoing messages (seconds); telegram allows ~30 msg/sec
SEND_DELAY = 0.5

# protects the broadcast loop from overlapping runs
_broadcast_lock = asyncio.Lock()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()


class UserState(StatesGroup):
    waiting_for_timezone = State()


# fetch USD/RUB from coingecko (usdc as usd proxy)
async def fetch_usd_rub() -> float | None:
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": "usd-coin", "vs_currencies": "rub"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("usd-coin", {}).get("rub")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


# refresh the cache once per day at 05:00 MSK
async def refresh_rate_cache() -> None:
    rate = await fetch_usd_rub()
    if rate is None:
        print("Failed to refresh rate cache: API returned nothing")
        return
    now_msk = pytz.utc.localize(
        __import__("datetime").datetime.utcnow()
    ).astimezone(REFRESH_TZ)
    rate_cache["value"] = rate
    rate_cache["date"] = now_msk.strftime("%d.%m.%Y")
    print(f"Rate cache refreshed: {rate:.2f} RUB on {rate_cache['date']}")


# build the message text from the cache (fills cache if empty)
async def build_rate_message() -> str:
    if rate_cache["value"] is None:
        await refresh_rate_cache()

    if rate_cache["value"] is None:
        return "⚠️ Не удалось получить актуальный курс. Попробуйте позже."

    return (
        f"💰 <b>Курс USD/RUB на {rate_cache['date']}</b>\n\n"
        f"Текущий курс: <b>{rate_cache['value']:.2f} ₽</b>"
    )


# send to a single user with retry on rate-limit
async def send_to_user(user_id: int, text: str) -> bool:
    try:
        await bot.send_message(user_id, text, parse_mode="HTML")
        return True
    except TelegramRetryAfter as e:
        # telegram asked us to wait; respect it and retry once
        print(f"Rate limited, waiting {e.retry_after}s for user {user_id}")
        await asyncio.sleep(e.retry_after)
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
            return True
        except Exception as e2:
            print(f"Retry failed for {user_id}: {e2}")
            return False
    except TelegramForbiddenError:
        user_timezones.pop(user_id, None)
        print(f"User {user_id} blocked the bot, removed from broadcast list")
        return False
    except Exception as e:
        print(f"Failed to send to {user_id}: {e}")
        return False


# broadcast cached rate to all users in a given timezone
async def broadcast_to_timezone(tz_name: str) -> None:
    async with _broadcast_lock:
        text = await build_rate_message()

        # snapshot the recipients for this timezone
        recipients = [
            uid for uid, tz in user_timezones.items() if tz == tz_name
        ]
        print(f"Broadcasting to {len(recipients)} users in {tz_name}")

        for i, user_id in enumerate(recipients):
            await send_to_user(user_id, text)
            # small pause between messages to stay under telegram limits
            if i < len(recipients) - 1:
                await asyncio.sleep(SEND_DELAY)

        print(f"Broadcast to {tz_name} finished")


# manual trigger for testing
# @dp.message(Command("test"))
# async def cmd_test(message: types.Message) -> None:
    # text = await build_rate_message()
    # await message.answer(text, parse_mode="HTML")


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
        tz = pytz.timezone(tz_input)
    except pytz.UnknownTimeZoneError:
        await message.answer(
            "❌ Не удалось распознать часовой пояс. Попробуйте еще раз, например: "
            "<code>Europe/Moscow</code>",
            parse_mode="HTML",
        )
        return

    user_timezones[message.from_user.id] = tz_input

    # one job per timezone: everyone in it is served by a single broadcast
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

    await message.answer(
        f"✅ Часовой пояс сохранен!",
        parse_mode="HTML",
    )


async def main() -> None:
    # one daily cache refresh at 05:00 MSK
    scheduler.add_job(
        refresh_rate_cache,
        trigger="cron",
        hour=REFRESH_HOUR,
        minute=REFRESH_MINUTE,
        id="refresh_rate",
        replace_existing=True,
        timezone=REFRESH_TZ,
    )
    scheduler.start()

    # fill cache on startup
    await refresh_rate_cache()

    print("Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())