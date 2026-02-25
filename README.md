# Диплом — Учебные планы и тесты

Стек: **Django (бекенд) + React (фронтенд)**. PostgreSQL для хранения пользователей, роадмапов, курсов, задач и фидбеков.

## Структура

```
Diploma/
├── backend/          # Django + DRF, PostgreSQL
│   ├── config/       # Настройки проекта
│   └── users/        # Регистрация, авторизация (JWT), модель User
├── frontend/         # React (Vite)
└── design/           # Макеты
```

## Как добавить новую страницу

1. Создать компонент в `frontend/src/pages/`, например `AuthPage.jsx`.
2. В `frontend/src/App.jsx` добавить маршрут:
   ```jsx
   <Route path="/auth" element={<AuthPage />} />
   ```
3. Переход по ссылкам — через `<Link to="/auth">` из `react-router-dom`.

## Как потом подключить бекенд

- В `frontend/vite.config.js` уже заготовлен proxy для API (закомментирован). Раскомментировать и указать порт Django (например 8000).
- Запросы с фронта делать на относительные пути вида `/api/...` — они уйдут на бекенд через proxy в dev. В проде — настроить CORS и базовый URL API в переменных окружения.

## Запуск (Docker)

```bash
docker compose up --build
```

- **Фронтенд:** http://localhost:5173  
- **Бекенд API:** http://localhost:8000  
- **PostgreSQL:** localhost:5432 (логин/пароль в `.env` или в `docker-compose.yml`)

При первом запуске бекенд сам выполняет миграции.

## API (бекенд)

- **Регистрация:** `POST /api/auth/register/` — тело: `{ "email", "password", "password_confirm", "first_name", "last_name" }`
- **Вход (JWT):** `POST /api/auth/token/` — тело: `{ "email", "password" }` → в ответе `access` и `refresh`
- **Обновление токена:** `POST /api/auth/token/refresh/` — тело: `{ "refresh": "<refresh_token>" }`
- **Текущий пользователь:** `GET /api/auth/me/` — заголовок: `Authorization: Bearer <access_token>`
