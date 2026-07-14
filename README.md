# ewsnotifier

[![CI](https://github.com/poznik/ewsnotifier/actions/workflows/ci.yml/badge.svg)](https://github.com/poznik/ewsnotifier/actions/workflows/ci.yml)

Telegram notifications for Microsoft Exchange (EWS): today's meetings and
unread mail, delivered by two bots.

Читаете по-русски? См. [README.ru.md](README.ru.md).

## What it does

- Polls Exchange over EWS (on-premises servers with NTLM/Basic/Digest auth,
  no autodiscover required) and caches today's calendar plus recent unread mail.
- **Meeting bot**: a reminder shortly before each meeting starts, with a
  "join" button when the location contains a meeting link; `/today` (day
  agenda with free windows between meetings) and `/check` (overlapping
  meetings) commands; an optional daily agenda on weekday mornings.
- **Mail bot**: a message per new unread email with sender, subject and a
  short preview; keyword-triggered mentions (e.g. ping `@nickname` when the
  text contains "urgent").
- Operational alerts: if Exchange authentication breaks (expired password),
  the bot tells the admin chat and retries on a long interval instead of
  silently going stale.
- Notification state survives restarts — no duplicate notification storm
  after a redeploy.

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in the values
python -m notifier
```

## Quick start (Docker / Synology)

1. Copy the project to the host, e.g. `/volume1/docker/notifier`.
2. Create `.env` next to `docker-compose.yml` (start from `.env.example`).
3. Create the state directory and make it writable by the container user
   (`user:` in `docker-compose.yml`, `1026:100` by default — adjust to
   the output of `id <your-user>` on your host):

   ```bash
   mkdir -p data
   ```

4. Start:

   ```bash
   docker compose up -d --build
   ```

On Synology DSM you can instead import `docker-compose.yml` through
Container Manager → Projects. Environment variables set in the UI take
precedence over `.env` values.

The container ships a `HEALTHCHECK`: it turns unhealthy when data has not
been refreshed from Exchange for `HEALTH_MAX_AGE` seconds (default 600).

## Configuration

Values are read from environment variables; missing ones fall back to the
`.env` file in the working directory. On startup every problem is reported
at once with the variable name.

### Required

| Variable | Meaning |
| --- | --- |
| `EWS_SERVER` | Exchange host, e.g. `mail.example.com` |
| `EWS_EMAIL` | Primary SMTP address of the mailbox |
| `EWS_USERNAME` | Login, usually `DOMAIN\user` (see the backslash note below) |
| `EWS_PASSWORD` | Password |
| `UPDATE_INTERVAL` | How often to refresh data from Exchange, seconds |
| `APPOINTMENT_REFRESH_INTERVAL` | How often to check for due meeting reminders, seconds |
| `APPOINTMENT_NOTIFY_INTERVAL` | Remind this many seconds before a meeting starts |
| `MAIL_REFRESH_INTERVAL` | How often to send accumulated mail notifications, seconds |
| `APPOINTMENT_BOT_TOKEN` | Telegram token of the meeting bot |
| `MAIL_BOT_TOKEN` | Telegram token of the mail bot |
| `ALLOWED_CHAT_IDS` | Comma-separated chat ids allowed to interact and notified |
| `LOCAL_TIMEZONE` | IANA timezone for display, e.g. `Europe/Moscow` |

### Optional

| Variable | Default | Meaning |
| --- | --- | --- |
| `EWS_AUTH_TYPE` | `NTLM` | `NTLM`, `BASIC` or `DIGEST` |
| `EWS_VERIFY_SSL` | `true` | TLS certificate verification (see Security) |
| `ADMIN_CHAT_ID` | — | Chat for operational alerts; empty = alert `ALLOWED_CHAT_IDS` |
| `MAIL_LOOKBACK_DAYS` | `7` | Only consider unread mail newer than this many days |
| `MAIL_FETCH_LIMIT` | `100` | Max unread messages fetched per refresh |
| `KEYWORDS` | — | Comma-separated keywords (whole-word match) that trigger a mention |
| `MENTION_TEXT` | — | Text appended on keyword match, e.g. `@nickname` |
| `AGENDA_TIME` | — | `HH:MM` local; send `/today` + `/check` on weekday mornings |
| `WORKDAY_START` | `09:00` | Workday start used for the free window before the first meeting |
| `MASK_PRIVATE_MEETINGS` | `false` | Replace subjects of private meetings with a placeholder |
| `AUTH_RETRY_INTERVAL` | `1800` | Seconds between retries after an Exchange auth failure |
| `STATE_FILE` | `state.json` | Where notification state is persisted (`/data/state.json` in Docker) |
| `HEALTH_FILE` | `/tmp/notifier-healthy` | Freshness marker used by the healthcheck |
| `LOG_LEVEL` | `INFO` | `CRITICAL` … `DEBUG` |

### How to write `DOMAIN\user`

The escaping rules differ between formats — this is the most common setup
mistake:

| Where | Write | Why |
| --- | --- | --- |
| `.env` file | `EWS_USERNAME=DOMAIN\user` | Values are taken literally, no escaping |
| YAML (`docker-compose.yml`) | `EWS_USERNAME: "DOMAIN\\user"` | YAML processes `\\` into `\` |
| Shell | `export EWS_USERNAME='DOMAIN\user'` | Single quotes keep it literal |

## Behaviour details

- Meeting reminders are sent once per meeting; if a meeting is rescheduled
  (either direction), it is announced again.
- All-day events are listed in `/today` under "Весь день" and are excluded
  from reminders and overlap checks.
- Cancelled meetings are ignored.
- On the very first run the existing unread backlog is not blasted into the
  chat — only mail arriving afterwards is announced.
- Long `/today` and `/check` replies are split to fit Telegram's message
  size limit.
- Messages that Telegram rejects permanently are logged and skipped;
  network hiccups and flood control are retried.

## Security

- Keep `EWS_VERIFY_SSL=true`. Disabling verification lets anyone on the
  network path intercept the NTLM credentials; the application logs a
  warning at startup when it is off. For a self-signed corporate CA, point
  `REQUESTS_CA_BUNDLE` at your CA bundle instead.
- Secrets live in `.env` / environment variables only; the file is ignored
  by git and excluded from the Docker image.
- The container runs as a non-root user and only chats listed in
  `ALLOWED_CHAT_IDS` are served.

## Development

```bash
pip install -r requirements.txt
pip install -e ".[dev]"
ruff check notifier tests && ruff format --check notifier tests
mypy notifier
pytest
```

CI runs the same checks on every push and pull request.

## Author

Nikolay Pozharskiy — pozhny@gmail.com — https://github.com/poznik

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).
