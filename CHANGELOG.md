# Changelog

## 1.0.0 — 2026-07-14

First public-ready release. The result of a full architecture and code
audit of the original generated codebase.

### Reliability

- Exchange authentication failures no longer stop updates silently: the
  bot alerts the admin chat (`ADMIN_CHAT_ID`, defaults to the meeting
  notification chats) and retries every `AUTH_RETRY_INTERVAL` (30 min by
  default, kept long to avoid domain account lockout). Recovery is
  announced too, as are 10+ consecutive refresh failures.
- Notification state (`notified` flags, agenda date) is persisted to
  `STATE_FILE` and survives restarts: no more re-notifying every unread
  email and re-sending the agenda after each redeploy. On the very first
  run the existing unread backlog is baselined silently.
- Background tasks are supervised: an unexpected crash shuts the process
  down with a non-zero exit code so Docker restarts it.
- Docker `HEALTHCHECK` based on data freshness; container runs as a
  non-root user; base image pinned; log rotation and memory limit in
  docker-compose.

### Telegram delivery

- Error handling matches the real python-telegram-bot exception
  hierarchy: flood control (`RetryAfter`) is honoured with the announced
  delay, permanent errors (`BadRequest`, `Forbidden`) are not retried,
  network errors keep exponential backoff. Both bots use `AIORateLimiter`.
- Messages are marked "notified" only after a send attempt; transient
  failures are retried on the next tick instead of being lost.
- Long `/today` and `/check` replies are split under Telegram's 4096
  character limit.

### Correctness

- All-day events: fetched explicitly, shown in `/today` as "Весь день",
  excluded from reminders and `/check` overlap detection; date-typed
  values from exchangelib no longer risk an `AttributeError`.
- Cancelled meetings are skipped; private meetings can be masked with
  `MASK_PRIVATE_MEETINGS=true`.
- Meeting reminders fire again when a meeting is rescheduled in either
  direction (previously only when moved later).
- Meeting-link extraction strips trailing punctuation (`<https://…>` no
  longer produces a broken "join" button).
- Unread mail is fetched with a date window (`MAIL_LOOKBACK_DAYS`) and a
  limit (`MAIL_FETCH_LIMIT`), without full HTML bodies — a large unread
  backlog no longer hammers Exchange every minute.
- Mail notifications are sent oldest-first; an empty day in `/today` says
  so explicitly; the workday start for "free window" hints is
  configurable (`WORKDAY_START`); newline-containing subjects no longer
  break MarkdownV2.

### Configuration & docs

- All configuration problems are reported at once, with variable names
  and human-readable messages; intervals are validated to be positive.
- `ADMIN_CHAT_ID` is now optional; `MENTION_TEXT` defaults to empty.
- `.env.example` fixed: `EWS_USERNAME=DOMAIN\user` with a single
  backslash (dotenv reads values literally); README documents the
  backslash rules per format.
- English README (`README.md`) with the Russian version preserved as
  `README.ru.md`; security notes on TLS verification.

### Tooling

- Packaging via `pyproject.toml`; Docker builds from fully pinned
  `requirements.txt`.
- Test suite (pytest, 100+ tests), ruff + mypy, GitHub Actions CI,
  Dependabot.
