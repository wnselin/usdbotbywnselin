# CryptoFiatMonitoring Bot

<a name="english"></a>
## 🇬🇧 English

A simple Telegram bot that sends the current USD/RUB exchange rate to its users
every day at **5:00 AM in their local timezone**.

### Features

- Daily USD/RUB rate delivered at 5:00 AM in each user's own timezone
- Rate is fetched once per day (05:00 MSK) and cached for the rest of the day
- One scheduled job per timezone — scales to many users without hitting API limits
- Respects Telegram rate limits via a configurable delay between messages
- Handles blocked users, retries, and Telegram `RetryAfter` automatically
- Minimal dependencies, no database required

### How it works

1. Once a day at **05:00 MSK**, the bot fetches the USD/RUB rate from
   [CoinGecko](https://www.coingecko.com/en/api) and stores it in memory
   (uses `usd-coin` as a proxy for USD, since CoinGecko tracks USDC 1:1 to USD).
2. Each user picks their own timezone by sending it to the bot (e.g. `Europe/Moscow`).
3. A separate cron job is scheduled per timezone and fires at 05:00 local time.
4. All users in that timezone get the cached rate, sent one by one with a small delay.

### Requirements

- Python 3.10+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### Installation

```bash
git clone https://github.com/wnselin/usdbotbywnselin
cd usdbotbywnselin
```
Install theese requirements: aiogram, aiohttp, pytz, apscheduler, python-dotenv

### Configuration

Create a `.env` file in the project root:

```env
BOT_TOKEN=123456789:AAExampleTokenReplaceMe
```

Get the token from [@BotFather](https://t.me/BotFather) with `/newbot`.

### Running

```bash
python3 main.py
```

### Running as a systemd service

Create `/etc/systemd/system/tgbot.service`:

```ini
[Unit]
Description=tgbot

[Service]
WorkingDirectory=/opt/tgbot
ExecStart=/opt/tgbot/venv/bin/python /opt/tgbot/main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
systemctl daemon-reload
systemctl enable --now tgbot
systemctl status tgbot
```

Logs:

```bash
journalctl -u tgbot -f
```

### Bot commands

| Command | Description |
|---|---|
| `/start` | Greeting and timezone prompt |

Any text message is interpreted as a timezone name (`Europe/Moscow`, `Asia/Yekaterinburg`, etc.).

### Notes on rate limits

- **CoinGecko**: 1 request per day → free tier is more than enough.
- **Telegram**: ~30 messages/second. The `SEND_DELAY` constant spreads messages
  out so even thousands of users in the same timezone are served safely.

### License

MIT

---

<a name="russian"></a>
## 🇷🇺 Русский

Простой Telegram-бот, который присылает актуальный курс доллара к рублю
каждый день в **5:00 утра по местному времени пользователя**.

### Возможности

- Ежедневная рассылка курса USD/RUB в 5:00 по часовому поясу каждого пользователя
- Курс забирается один раз в сутки (в 05:00 МСК) и кэшируется на весь день
- Одна задача планировщика на часовой пояс — легко масштабируется на много пользователей
- Соблюдение лимитов Telegram за счёт настраиваемой задержки между сообщениями
- Обработка заблокированных пользователей, повторов и `RetryAfter`
- Минимум зависимостей, база данных не нужна

### Как это работает

1. Раз в сутки в **05:00 МСК** бот забирает курс USD/RUB с
   [CoinGecko](https://www.coingecko.com/en/api) и кладёт его в память
   (используется `usd-coin` как прокси доллара — CoinGecko держит USDC 1:1 к USD).
2. Пользователь указывает свой часовой пояс, отправив боту сообщение
   (например, `Europe/Moscow`).
3. На каждый часовой пояс создаётся отдельная cron-задача, срабатывающая в 5:00
   по локальному времени.
4. Все пользователи в этом поясе получают закэшированный курс, сообщения
   отправляются по одному с небольшой паузой.

### Требования

- Python 3.10+
- Токен Telegram-бота от [@BotFather](https://t.me/BotFather)

### Установка

```bash
git clone https://github.com/wnselin/usdbotbywnselin
cd usdbotbywnselin
```
Установите эти зависимости: aiogram, aiohttp, pytz, apscheduler, python-dotenv

### Настройка

Создайте файл `.env` в корне проекта:

```env
BOT_TOKEN=123456789:AAExampleTokenReplaceMe
```

Токен получается у [@BotFather](https://t.me/BotFather) командой `/newbot`.

### Запуск

```bash
python3 main.py
```

### Запуск как systemd-сервис

Создайте `/etc/systemd/system/tgbot.service`:

```ini
[Unit]
Description=tgbot

[Service]
WorkingDirectory=/opt/tgbot
ExecStart=/opt/tgbot/venv/bin/python /opt/tgbot/main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Включите и запустите:

```bash
systemctl daemon-reload
systemctl enable --now tgbot
systemctl status tgbot
```

Логи:

```bash
journalctl -u tgbot -f
```

### Команды бота

| Команда | Описание |
|---|---|
| `/start` | Приветствие и запрос часового пояса |

Любое текстовое сообщение интерпретируется как название часового пояса
(`Europe/Moscow`, `Asia/Yekaterinburg` и т.д.).

### Про лимиты

- **CoinGecko**: 1 запрос в сутки → бесплатного тарифа хватает с огромным запасом.
- **Telegram**: ~30 сообщений в секунду. Константа `SEND_DELAY` размазывает
  отправку, поэтому даже тысячи пользователей в одном поясе обслуживаются безопасно.

### Лицензия

MIT
