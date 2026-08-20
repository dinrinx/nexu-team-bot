# NEXU Team Matcher Bot

Отдельный Telegram-бот для мэтчинга участников NEXU по логике "анкета -> лента -> лайк/пропуск -> взаимный мэтч".

## Что умеет

- Пошагово заполняет анкету через FSM
- Хранит профили, лайки и мэтчи в SQLite
- Показывает ленту анкет без раскрытия контактов до взаимного лайка
- Поддерживает фильтры по чемпионатам, ролям и ролям, которые ищет команда
- Даёт команды `/my`, `/matches`, `/stats`, `/broadcast_team`
- Удаляет связанные лайки и мэтчи при удалении анкеты

## Структура

- `run.py` — точка входа
- `bot/main.py` — роутеры и сценарии бота
- `bot/database.py` — SQLite-репозиторий и модель профиля
- `deploy/nexu-team-bot.service` — шаблон systemd unit
- `tests/test_repository.py` — базовые тесты логики БД

## Локальный запуск

1. Создай виртуальное окружение и установи зависимости:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Подготовь `.env`:

```bash
cp .env.example .env
```

3. Заполни `BOT_TOKEN`.

4. Запусти бота:

```bash
python run.py
```

## Проверки

```bash
python3 -m unittest discover -s tests
python3 -m py_compile run.py bot/*.py
```

## Деплой на VPS

1. Склонировать проект в `/root/nexu-team-bot`
2. Создать `.venv` и установить зависимости
3. Создать `.env` из `.env.example`
4. Скопировать `deploy/nexu-team-bot.service` в `/etc/systemd/system/nexu-team-bot.service`
5. Выполнить:

```bash
systemctl daemon-reload
systemctl enable --now nexu-team-bot.service
systemctl status nexu-team-bot.service
```

## Логи и обновления

Логи:

```bash
journalctl -u nexu-team-bot -f
```

Обновление:

```bash
cd /root/nexu-team-bot
git pull
source .venv/bin/activate
pip install -r requirements.txt
systemctl restart nexu-team-bot.service
```
