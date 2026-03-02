# QUEST — Система учёта опросов

Десктопное приложение для детского коррекционного центра: учёт клиентов, сотрудников и обратной связи (опросов) с аналитикой и AI-ассистентом.

## Стек

| Компонент | Технология |
|-----------|-----------|
| GUI | PyQt6 |
| Графики | PyQt6-Charts |
| ORM | SQLAlchemy 2.0 |
| БД | SQLite (`data/surveys.db`) |
| HTTP | httpx |
| AI | OpenRouter API (стриминг) |
| Excel | openpyxl |
| Тесты | pytest |

## Требования

- Python 3.10+
- pip

## Установка

```bash
cd survey-app
pip install -r requirements.txt
```

## Запуск

```bash
python main.py
```

База данных создаётся автоматически при первом запуске в папке `data/`.

## Импорт данных из Excel

1. Меню **Данные → Импорт из Excel…**
2. Выбрать файл `.xlsx`
3. Дождаться завершения — прогресс отображается в диалоге
4. Все вкладки обновляются автоматически

Формат Excel: строки — опросы, столбцы — ФИО ребёнка, ФИО родителя, тип контакта, дата, удовлетворённость, недопонимание, жалобы, статус ситуации и т.д.

## Экспорт отчёта

**Данные → Экспорт проблемных опросов…** — сохраняет Markdown-файл со всеми опросами, где зафиксированы негативные сигналы (неудовлетворённость, жалобы, нерешённые ситуации).

## AI-ассистент

Вкладка **AI-модуль**:

1. Получить API-ключ на [openrouter.ai](https://openrouter.ai)
2. Вставить ключ в поле **API ключ**, выбрать модель, нажать **Сохранить**
3. Нажать **Загрузить проблемные опросы** — данные из БД попадут в системный промпт
4. Задавать вопросы в поле ввода

Настройки (ключ и модель) сохраняются в `data/config.json`.

## Структура проекта

```
survey-app/
├── main.py                    # Точка входа
├── database.py                # SQLAlchemy engine + SessionLocal
├── models.py                  # ORM-модели (Client, Employee, Survey, …)
├── requirements.txt
│
├── migration/
│   └── import_excel.py        # Парсинг и импорт .xlsx
│
├── services/
│   ├── survey_logic.py        # Бизнес-логика опросов
│   ├── analytics.py           # Расчёт KPI и аналитики
│   ├── export.py              # Генерация Markdown-отчёта
│   ├── ai_service.py          # OpenRouter SSE-стриминг (QThread)
│   └── config_store.py        # Чтение/запись data/config.json
│
├── ui/
│   ├── styles.qss             # Глобальные QSS-стили
│   ├── main_window.py         # QMainWindow, меню, вкладки
│   ├── clients_widget.py      # Список клиентов + добавление
│   ├── client_detail_widget.py# Карточка клиента (инфо, специалисты, опросы)
│   ├── employees_widget.py    # Список сотрудников
│   ├── surveys_widget.py      # Все опросы с фильтрами
│   ├── survey_form_widget.py  # Форма создания/редактирования опроса
│   ├── analytics_widget.py    # Дашборд с KPI и графиками
│   ├── ai_module_widget.py    # AI-чат с контекстом из БД
│   └── migration_dialog.py    # Диалог импорта Excel
│
├── tests/
│   ├── conftest.py            # pytest-фикстуры (in-memory SQLite)
│   ├── test_models.py         # Тесты ORM-моделей
│   ├── test_migration.py      # Тесты импорта Excel
│   └── test_survey_logic.py   # Тесты сервисного слоя
│
└── data/                      # Создаётся автоматически
    ├── surveys.db             # SQLite база данных
    └── config.json            # Настройки AI (API ключ, модель)
```

## Запуск тестов

```bash
cd survey-app
python -m pytest tests/ -v
```

## Цветовые обозначения

| Цвет | Значение |
|------|---------|
| Зелёный | Решено / Удовлетворён |
| Жёлтый | В работе |
| Красный | Не решено / Неудовлетворён |
| Серый | Закрыто / Неактивен |
