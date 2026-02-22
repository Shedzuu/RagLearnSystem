# Диплом — Учебные планы и тесты

Стек (планируется): **Django (бекенд) + React (фронтенд)**.

## Структура

```
Diploma/
├── backend/          # Django — пока пусто, подключится позже
├── frontend/         # React (Vite) — страницы и UI
│   └── src/
│       ├── pages/    # Одна папка = одна страница (LandingPage, потом Auth, Dashboard и т.д.)
│       ├── components/
│       ├── App.jsx   # Роуты: новые страницы добавлять в <Route path="..." element={...} />
│       └── main.jsx
└── design/           # Макеты (landing, uploading и др.)
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

Фронтенд: http://localhost:5173
