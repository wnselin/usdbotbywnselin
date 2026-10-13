# usdbotbywnselin

[English](#english) · [Русский](#russian)

---

<a name="english"></a>
## 🇬🇧 English

A simple Telegram bot that sends the current USD/RUB exchange rate to its users
every day at **5:00 AM in their local timezone**. Rate is fetched once a day
from CoinGecko and cached; users are stored in SQLite so restarts don't lose
subscribers.

### Features

- Daily USD/RUB rate delivered at 5:00 AM in each user's own timezone
- Rate is fetched once per day (05:00 MSK) and cached for the rest of the day
- One scheduled job per timezone — scales cleanly across many users
- SQLite storage (async via `aiosqlite`) — subscribers survive restarts
- Automatic daily database backups at 03:00 MSK, with retention
- Respects Telegram rate limits via a configurable delay between messages
- Handles blocked users, retries, and Telegram `RetryAfter` automatically
- Rotating file logs (`bot.log`, 5 MB × 3) and stdout for `journald`
- Graceful shutdown: waits for in-flight broadcasts before closing the DB

### How it works

1. Once a day at **05:00 MSK**, the bot fetches the USD/RUB rate from
   [CoinGecko](https://www.coingecko.com/en/api) and caches it
   (uses `usd-coin` as a proxy for USD, since CoinGecko tracks USDC 1:1 to USD).
2. A user picks a timezone by sending it to the bot (e.g. `Europe/Moscow`).
   The subscription is written to SQLite.
3. One cron job is scheduled per **timezone** (not per user). At 05:00 local
   time, that job broadcasts the cached rate to everyone in that timezone.
4. At 03:00 MSK, the bot snapshots the SQLite database into `backups/`.

### Scale

This bot is designed for **small to medium audiences** — roughly up to a few
thousand users.

- **CoinGecko**: 1 request per day, free tier is more than enough.
- **Telegram**: ~30 messages/second. The `SEND_DELAY` constant spreads sends
  out, so even thousands of users in one timezone are served safely.
- **In-memory timezone map + SQLite**: fine for thousands of users. The
  subscriber list is loaded once at startup and mirrored in memory for fast
  broadcasts; SQLite is used only for durable storage.
- **Single-process only**: the bot keeps scheduled jobs in memory, so running
  multiple instances would double-schedule broadcasts. If you ever need to
  scale beyond one process, move the scheduler state to a shared store (e.g.
  Redis + `apscheduler` job store).

### Requirements

- Python 3.10+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### Installation

```bash
git clone https://github.com/wnselin/usdbotbywnselin.git
cd usdbotbywnselin

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the project root:

```env
BOT_TOKEN=123456789:AAExampleTokenReplaceMe
```

Get the token from [@BotFather](https://t.me/BotFather) with `/newbot`.

Optional variables (defaults are fine for most setups):

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `<project>/bot.db` | Path to the SQLite database |
| `BACKUP_DIR` | `<project>/backups` | Directory for DB snapshots |
| `BACKUP_KEEP` | `7` | Number of recent backups to keep |
| `LOG_PATH` | `<project>/bot.log` | Path to the log file |

### Running

```bash
python main.py
```

### Running as a systemd service

Create `/etc/systemd/system/tgbot.service`:

```ini
[Unit]
Description=tgbot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/tgbot
ExecStart=/opt/tgbot/venv/bin/python /opt/tgbot/main.py
Restart=always
RestartSec=10

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

Any plain text message is interpreted as a timezone name
(`Europe/Moscow`, `Asia/Yekaterinburg`, etc.).

### Data & backups

- `bot.db` — SQLite database with the subscriber list
- `backups/` — timestamped snapshots (`bot_YYYYMMDD_HHMMSS.db.bak`),
  created via SQLite's online backup API for consistency
- `bot.log`, `bot.log.1`, … — rotating application logs

None of these should be committed to Git — see `.gitignore`.

### Notes on rate limits

- **CoinGecko**: 1 request per day → free tier is more than enough.
- **Telegram**: ~30 messages/second. `SEND_DELAY` keeps broadcasts under the
  limit even for large timezones.

### License

MIT

---

<a name="russian"></a>
## 🇷🇺 Русский

Простой Telegram-бот, который присылает актуальный курс доллара к рублю
каждый день в **5:00 утра по местному времени пользователя**. Курс забирается
раз в сутки из CoinGecko и кэшируется, подписчики хранятся в SQLite и не
теряются при перезапуске.

### Возможности

- Ежедневная рассылка курса USD/RUB в 5:00 по часовому поясу каждого пользователя
- Курс забирается один раз в сутки (в 05:00 МСК) и кэшируется на весь день
- Одна задача планировщика на часовой пояс — легко масштабируется на много пользователей
- Подписчики хранятся в SQLite (асинхронно, через `aiosqlite`) — переживают рестарт
- Ежедневный бэкап базы в 03:00 МСК с ограничением по количеству файлов
- Соблюдение лимитов Telegram за счёт настраиваемой задержки между сообщениями
- Обработка заблокированных пользователей, повторов и `RetryAfter`
- Ротация логов (`bot.log`, 5 МБ × 3) + вывод в stdout для `journald`
- Корректная остановка: ждём завершения активных рассылок, потом закрываем БД

### Как это работает

1. Раз в сутки в **05:00 МСК** бот забирает курс USD/RUB с
   [CoinGecko](https://www.coingecko.com/en/api) и кладёт его в кэш
   (используется `usd-coin` как прокси доллара — CoinGecko держит USDC 1:1 к USD).
2. Пользователь указывает свой часовой пояс, отправив боту сообщение
   (например, `Europe/Moscow`). Подписка сохраняется в SQLite.
3. На каждый **часовой пояс** создаётся отдельная cron-задача (не на каждого
   пользователя). В 5:00 по локальному времени она рассылает закэшированный
   курс всем подписчикам этого пояса.
4. В 03:00 МСК бот снимает консистентный снимок базы в папку `backups/`.

### Про масштаб

Бот рассчитан на **небольшую и среднюю аудиторию** — примерно до нескольких
тысяч пользователей.

- **CoinGecko**: 1 запрос в сутки — бесплатного тарифа хватает с огромным запасом.
- **Telegram**: ~30 сообщений в секунду. Константа `SEND_DELAY` размазывает
  отправку, поэтому даже тысячи пользователей в одном поясе обслуживаются безопасно.
- **Память + SQLite**: словарь часовых поясов в памяти + персистентность
  в SQLite — этого достаточно для тысяч пользователей. Список подписчиков
  загружается при старте, SQLite используется только для хранения.
- **Один процесс**: планировщик держит задачи в памяти, поэтому запускать
  несколько инстансов нельзя — это приведёт к двойным рассылкам. Если
  когда-нибудь понадобится масштабирование, задачи надо будет вынести
  в общий стор (например, Redis + job store для `apscheduler`).

### Требования

- Python 3.10+
- Токен Telegram-бота от [@BotFather](https://t.me/BotFather)

### Установка

```bash
git clone https://github.com/wnselin/usdbotbywnselin.git
cd usdbotbywnselin

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Настройка

Создайте файл `.env` в корне проекта:

```env
BOT_TOKEN=123456789:AAExampleTokenReplaceMe
```

Токен получается у [@BotFather](https://t.me/BotFather) командой `/newbot`.

Опциональные переменные (дефолтов хватает для большинства):

| Переменная | По умолчанию | Описание |
|---|---|---|
| `DB_PATH` | `<проект>/bot.db` | Путь к базе SQLite |
| `BACKUP_DIR` | `<проект>/backups` | Папка для бэкапов БД |
| `BACKUP_KEEP` | `7` | Сколько последних бэкапов хранить |
| `LOG_PATH` | `<проект>/bot.log` | Путь к файлу логов |

### Запуск

```bash
python main.py
```

### Запуск как systemd-сервис

Создайте `/etc/systemd/system/tgbot.service`:

```ini
[Unit]
Description=tgbot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/tgbot
ExecStart=/opt/tgbot/venv/bin/python /opt/tgbot/main.py
Restart=always
RestartSec=10

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

### Данные и бэкапы

- `bot.db` — база SQLite со списком подписчиков
- `backups/` — снимки с таймстемпом (`bot_YYYYMMDD_HHMMSS.db.bak`),
  создаются через online backup API SQLite (консистентно и безопасно)
- `bot.log`, `bot.log.1`, … — ротация логов приложения

Ничего из этого не должно попадать в Git — см. `.gitignore`.

### Про лимиты

- **CoinGecko**: 1 запрос в сутки → бесплатного тарифа хватает с огромным запасом.
- **Telegram**: ~30 сообщений в секунду. `SEND_DELAY` держит рассылку в рамках
  лимита даже для больших часовых поясов.

### Лицензия

MIT