Notifier Telegram Bot
=====================

Внимание
--------
Чистый **vibecode** на gpt-5.2-codex.

Описание
--------
Проект опрашивает Exchange по EWS, кэширует встречи на сегодня и непрочитанные
письма, а затем отправляет уведомления в Telegram через два бота:
- APPOINTMENT_BOT: уведомления о встречах.
- MAIL_BOT: уведомления о почте.

Структура проекта
-----------------
- `notifier/` — исходный код
  - `app.py` — циклы обновления/оповещений, формат сообщений, команды
  - `ews_client.py` — подключение к Exchange и загрузка данных
  - `config.py` — загрузка настроек из `.env`
  - `models.py` — модели встреч и писем
  - `cache.py` — кэш и флаги оповещений
  - `utils.py` — форматирование дат, Markdown, превью
- `requirements.txt` — зависимости
- `.env.example` — пример настроек
- `Dockerfile`, `docker-compose.yml` — контейнеризация

Настройки (переменные среды и .env)
-----------------------------------
Приложение читает параметры из переменных среды. Если переменная не задана,
берется значение из файла `.env` (если он есть).

Обязательные параметры:
- `EWS_SERVER` — адрес сервера Exchange
- `EWS_EMAIL` — основной SMTP адрес почтового ящика
- `EWS_USERNAME` — логин (например, `DOMAIN\\user`) или `name@domain.com` для некоторых серверов
- `EWS_PASSWORD` — пароль
- `EWS_AUTH_TYPE` — тип авторизации (обычно `NTLM`)
- `EWS_VERIFY_SSL` — проверка SSL сертификата (`true`/`false`)

- `UPDATE_INTERVAL` — как часто обновлять данные из Exchange (сек)
- `APPOINTMENT_REFRESH_INTERVAL` — как часто проверять оповещения по встречам (сек)
- `APPOINTMENT_NOTIFY_INTERVAL` — за сколько секунд до встречи прислать оповещение
- `MAIL_REFRESH_INTERVAL` — как часто оповещать по почте (сек)

- `APPOINTMENT_BOT_TOKEN` — токен бота для встреч
- `MAIL_BOT_TOKEN` — токен бота для почты

- `ALLOWED_CHAT_IDS` — список разрешенных чатов через запятую
- `ADMIN_CHAT_ID` — ID администратора

- `LOCAL_TIMEZONE` — локальный часовой пояс (IANA, например `Europe/Moscow`)
- `KEYWORDS` — ключевые слова для упоминания (через запятую, опционально)
- `MENTION_TEXT` — текст упоминания, например `#warning` или `@nickname` (опционально)
- `AGENDA_TIME` — время ежедневной сводки (локальное, `HH:MM`, опционально).
  Если задано, бот в рабочие дни (Пн–Пт) отправляет два сообщения: `/today` и `/check`.
  При неудачной отправке выполняется до 10 попыток с интервалом 1 минута.
- `LOG_LEVEL` — уровень логов (`INFO`, `WARNING`, ...)

Запуск локально
---------------
1. Создать виртуальное окружение и установить зависимости:
   - `python -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -r requirements.txt`
2. Скопировать `.env.example` в `.env` и заполнить значения (или задать
   переменные среды).
3. Запустить:
   - `python -m notifier`

Запуск в Docker на Synology (DSM 7.3)
--------------------------------------
Вариант через Container Manager:
1. Скопируйте проект на NAS, например в `/volume1/docker/notifier`.
2. Создайте `.env` на основе `.env.example` в этой папке, либо задайте
   переменные среды в настройках контейнера. В `docker-compose.yml` все
   параметры указаны как `${VAR}`, поэтому переменные среды имеют приоритет,
   а значения из `.env` используются как fallback.
3. В Container Manager: "Проекты" → "Создать" → "Импортировать" и выберите
   `docker-compose.yml`.
4. Запустите проект.

Вариант через CLI:
- `docker compose up -d --build`
  (переменные берутся из `.env`, а при наличии переменных среды — из них)

Пример задания строковых значений в `docker-compose.yml`:
```yaml
services:
  notifier:
    environment:
      EWS_USERNAME: "DOMAIN\\user"
      LOCAL_TIMEZONE: "Europe/Moscow"
      MENTION_TEXT: "@nickname"
      KEYWORDS: "urgent,asap"
      AGENDA_TIME: "06:10"
```

Остановка:
- `docker compose down`

Примечания
----------
- Все даты/время хранятся в UTC и отображаются в `LOCAL_TIMEZONE`.
- Команда `/today` доступна только в чатах из `ALLOWED_CHAT_IDS`.
- Оповещения о встречах, почте и ежедневная сводка запускаются только после
  первого успешного обновления данных из Exchange.
- При ошибке авторизации в Exchange обновления прекращаются, ошибка остается
  в логах.

Автор
--------------
Nikolay Pozharskiy (vibecode)
pozhny@gmail.com  
https://github.com/poznik
