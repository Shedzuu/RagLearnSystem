# Backend (Django)

Пока только регистрация и авторизация (JWT). Таблицы в БД: только **User** (приложение `users`).

## Локальный запуск без Docker

1. Создать виртуальное окружение и установить зависимости:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   pip install -r requirements.txt
   ```

2. Создать `.env` из `.env.example`, указать подключение к PostgreSQL (или запустить только БД в Docker: `docker compose up db -d`).

3. Миграции:
   ```bash
   python manage.py migrate
   ```

4. Запуск:
   ```bash
   python manage.py runserver
   ```

## Модели

- **User** (users) — email как логин, first_name, last_name. Единственная таблица помимо служебных Django.