# План разработки: Система учёта и анализа клиентских опросов

## Контекст проекта

Десктопное приложение на PyQt6 для детского коррекционного центра. Учёт, анализ и контроль качества клиентских опросов. Миграция данных из Excel-файла (67 клиентов, ~93 опроса, период 2022–2026). Один пользователь, локальный запуск.

**Стек**: Python + PyQt6 (GUI), SQLAlchemy + SQLite (БД), httpx (AI-запросы), openpyxl (миграция Excel).

**Системный промпт для AI-модуля**: прилагается в файле `System-Prompt.txt`.

---

## Структура проекта

```
survey-app/
├── main.py                      # Точка входа — QApplication, инициализация БД, запуск окна
├── database.py                  # SQLAlchemy engine, SessionLocal, Base
├── models.py                    # Все ORM-модели
├── system_prompt.txt            # Системный промпт для AI-модуля
│
├── ui/                          # PyQt6 виджеты (только UI, без бизнес-логики)
│   ├── main_window.py           # QMainWindow с QTabWidget
│   ├── clients_widget.py        # Список клиентов + диалог добавления/редактирования
│   ├── client_detail_widget.py  # Карточка клиента + хронология опросов
│   ├── employees_widget.py      # Список сотрудников + форма
│   ├── surveys_widget.py        # Таблица опросов с фильтрами
│   ├── survey_form_widget.py    # QDialog — полная форма опроса
│   ├── analytics_widget.py      # Дашборд + графики
│   └── ai_module_widget.py      # AI-чат, выбор модели, редактор промпта
│
├── services/                    # Бизнес-логика (без PyQt6)
│   ├── survey_logic.py          # Автоматическая логика статусов
│   ├── analytics.py             # Расчёт аналитики
│   ├── export.py                # Экспорт в markdown
│   └── ai_service.py            # OpenRouter API (QThread worker)
│
└── migration/                   # Утилиты (запускаются один раз)
    └── import_excel.py          # Миграция из Опросы.xlsx
```

---

## Фаза 1. Инициализация проекта и БД

### 1.1 Модели данных (SQLAlchemy)

#### Таблица `employees`

| Поле | Тип | Описание |
|------|-----|----------|
| id | Integer, PK | ID сотрудника |
| full_name | String(200) | ФИО |
| position | Enum | Логопед / Дефектолог / Психолог / Нейропсихолог / СИ / Администратор |
| status | Enum, default="active" | Активен / Не работает |

#### Таблица `clients`

| Поле | Тип | Описание |
|------|-----|----------|
| id | Integer, PK | ID клиента |
| child_name | String(200) | ФИО ребёнка |
| parent_name | String(200) | ФИО родителя |
| start_date | Date | Дата начала занятий |
| status | Enum, default="active" | Активен / Завершён |

#### Связующая таблица `client_employees` (M2M)

| Поле | Тип |
|------|-----|
| client_id | FK → clients.id |
| employee_id | FK → employees.id |

#### Таблица `surveys`

| Поле | Тип | Описание |
|------|-----|----------|
| id | Integer, PK | ID опроса |
| client_id | FK → clients.id | Клиент |
| contact_date | Date | Дата контакта |
| contact_type | Enum | planned_1 / planned_2 / planned_3 / additional |
| conducted_by | String(200), default="Я" | Кто провёл |
| comment_text | Text | Текст опроса |
| satisfaction | Enum, nullable | satisfied / unsatisfied |
| misunderstanding | Enum, default="no" | yes / no |
| complaint_employee | Boolean, default=False | Жалоба на сотрудника |
| complaint_employee_text | Text | Суть жалобы |
| complaint_conditions | Boolean, default=False | Жалоба на условия |
| complaint_conditions_text | Text | Описание проблемы |
| situation_status | Enum, nullable | in_progress / resolved / unresolved / closed |
| resolution_result | Text | Результат урегулирования |
| non_resolution_reason | Text | Причина неурегулирования |

#### Связующие таблицы

| Таблица | Поля |
|---------|------|
| `survey_complaint_employees` | survey_id FK, employee_id FK |
| `survey_specialists_snapshot` | survey_id FK, employee_id FK |

### 1.2 Задачи фазы 1

1. Создать структуру папок проекта
2. Написать `database.py` — SQLAlchemy engine + SessionLocal
3. Написать `models.py` — все ORM-модели по схеме выше
4. Написать `main.py` — QApplication, `Base.metadata.create_all()`, запуск главного окна
5. Создать пустой `ui/main_window.py` с QMainWindow + QTabWidget (заглушки вкладок)
6. Проверить: приложение запускается, БД создаётся

---

## Фаза 2. Миграция данных из Excel

### 2.1 Структура файла Опросы.xlsx

| Колонка | Содержимое |
|---------|-----------|
| A (0) | № п/п |
| B (1) | Клиент (ФИО ребёнка) |
| C (2) | № п/п (опрос 1) |
| D (3) | Дата 1 опроса |
| E (4) | Текст 1 опроса |
| F (5) | № п/п (опрос 2) |
| G (6) | Дата 2 опроса |
| H (7) | Текст 2 опроса |
| I (8) | № п/п (опрос 3) |
| J (9) | Дата 3 опроса |
| K (10) | Текст 3 опроса |

**Статистика**: 67 клиентов (строки 2–75), 58 первых / 23 вторых / 12 третьих опросов, период март 2022 — март 2026.

### 2.2 Парсинг текстов опросов

Тексты содержат структурированную информацию в свободной форме:
```
Опрос направлен по WhatsApp 20.11.25 в 11:36.
[20.11.25 12:19] Андрей (Злата Дорохина 4г): Добрый день!
```

Можно извлечь: имя родителя (regex-паттерн `[дата] ИмяРодителя (ИмяРебёнка):`), канал связи.

### 2.3 Задачи фазы 2

1. Написать `migration/import_excel.py` — чтение openpyxl, создание клиентов и опросов
2. Реализовать извлечение имени родителя из текстов (regex)
3. Парсинг дат в форматах DD.MM.YY и DD.MM.YYYY
4. Идемпотентная миграция (пропускать уже существующих клиентов)
5. Генерировать отчёт: создано / пропущено / ошибок

---

## Фаза 3. Сервисный слой и бизнес-логика

### 3.1 `services/survey_logic.py`

```python
def auto_update_status(survey):
    """
    Правила:
    1. satisfaction == "unsatisfied"
       ИЛИ misunderstanding == "yes"
       ИЛИ complaint_employee == True
       ИЛИ complaint_conditions == True
       → situation_status = "in_progress" (если был None)

    2. resolution_result заполнен → situation_status = "resolved"
    3. non_resolution_reason заполнен → situation_status = "unresolved"
    """

def create_survey(session, client_id, data) -> Survey

def update_survey(session, survey, data) -> Survey

def create_planned_surveys(session, client_id):
    """При создании клиента — создать 3 плановых шаблона"""

def get_contact_count(session, client_id) -> int
```

### 3.2 `services/analytics.py`

| Метрика | Логика |
|---------|--------|
| % удовлетворённых | COUNT(satisfied) / COUNT(not null) * 100 |
| Конфликты «В процессе» | COUNT(situation_status=in_progress) |
| Среднее контактов до урегулирования | AVG по клиентам со status=resolved |
| Жалобы по сотрудникам | JOIN survey_complaint_employees GROUP BY employee |
| Повторные обращения | Клиенты с COUNT(surveys) > 3 |

### 3.3 Задачи фазы 3

1. Реализовать `survey_logic.py` полностью
2. Реализовать `analytics.py` — все метрики
3. Реализовать `export.py` — формирование markdown-файла неудовлетворённых ОС
4. Написать тесты для `auto_update_status` (без PyQt6)

---

## Фаза 4. UI — основные виджеты

### 4.1 Навигация (`ui/main_window.py`)

QMainWindow с QTabWidget, вкладки:
- Клиенты
- Сотрудники
- Опросы
- Аналитика
- AI-модуль

### 4.2 Виджеты

| Виджет | Описание |
|--------|----------|
| `clients_widget.py` | QTableWidget со списком клиентов, кнопки «Добавить» / «Открыть» / «Фильтр по статусу» |
| `client_detail_widget.py` | QDialog или вкладка: ФИО, специалисты, хронология всех опросов клиента |
| `employees_widget.py` | QTableWidget сотрудников, кнопки CRUD, статус цветом |
| `surveys_widget.py` | QTableWidget всех опросов, фильтры: тип / статус / дата / удовлетворённость |
| `survey_form_widget.py` | QDialog с QFormLayout — все блоки формы (жалобы, управление ситуацией) |

### 4.3 Технические решения

- `QTableWidget` для таблиц с сортировкой
- `QDialog` для форм создания/редактирования
- Цветовая индикация статусов через `QTableWidgetItem` foreground/background
- Сигналы Qt для обновления смежных виджетов после сохранения
- `QComboBox` с множественным выбором через `QListWidget` + `QCheckBox` для специалистов

### 4.4 Задачи фазы 4

1. Реализовать `main_window.py` с навигацией
2. Реализовать `clients_widget.py` + диалог добавления клиента
3. Реализовать `client_detail_widget.py`
4. Реализовать `employees_widget.py`
5. Реализовать `surveys_widget.py` с фильтрами
6. Реализовать `survey_form_widget.py` — полная форма со всеми блоками

---

## Фаза 5. Аналитика

### 5.1 `ui/analytics_widget.py`

- KPI-карточки (QLabel): % довольных, конфликты в процессе, всего клиентов
- График удовлетворённости по месяцам (PyQtChart `QLineSeries` или matplotlib `FigureCanvasQTAgg`)
- Столбчатая диаграмма: жалобы по сотрудникам
- Круговая: распределение статусов ситуаций
- Таблица: топ причин недовольства (QTableWidget)
- Фильтр по периоду: QComboBox (месяц / квартал / год) или QDateEdit

### 5.2 Задачи фазы 5

1. Реализовать сервис расчёта аналитики (`services/analytics.py`)
2. Создать виджет аналитики с KPI-карточками
3. Добавить графики (PyQtChart или matplotlib в QWidget)
4. Добавить фильтрацию по периоду

---

## Фаза 6. Экспорт и AI-модуль

### 6.1 Экспорт в Markdown (`services/export.py`)

Формат выгрузки:

```markdown
# Неудовлетворённые обратные связи
## Клиент: Иванов Иван
### Опрос: Плановый 2 | 15.01.2026
**Удовлетворённость**: Не доволен
**Недопонимание**: Да
**Жалоба на сотрудника**: Петрова А.А. — ...
**Жалоба на условия**: ...
**Статус**: В процессе
**Комментарий**: ...
---
```

Кнопка «Экспорт» → `QFileDialog.getSaveFileName()` → сохраняет .md файл на диск.

### 6.2 AI-модуль (`ui/ai_module_widget.py`)

**Компоненты виджета:**
- `QLineEdit` — поле ввода API-ключа (сохраняется в конфиг-файл `config.json`)
- `QComboBox` — список моделей OpenRouter (загружается из API)
- `QTextEdit` — редактируемый системный промпт (по умолчанию из `system_prompt.txt`)
- `QTextEdit` (read-only) — история диалога
- `QLineEdit` + кнопка «Отправить» — ввод сообщения
- Кнопка «Загрузить контекст» — подгрузить неудовлетворённые ОС в диалог

**Схема запроса к OpenRouter:**
```python
{
    "model": "выбранная_модель",
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "контекст_ОС + вопрос_пользователя"}
    ]
}
```

**`services/ai_service.py`** — `AIChatWorker(QThread)`:
- Сигнал `response_ready(str)` — ответ от AI
- Сигнал `error_occurred(str)` — ошибка
- Синхронный `httpx.Client` внутри `run()` — не блокирует UI

### 6.3 Задачи фазы 6

1. Реализовать `services/export.py` + кнопку экспорта в analytics_widget
2. Реализовать `AIChatWorker` в `services/ai_service.py`
3. Реализовать `ui/ai_module_widget.py` — чат, выбор модели, редактор промпта
4. Реализовать подгрузку контекста неудовлетворённых ОС в диалог
5. Сохранение API-ключа в `config.json` (рядом с `main.py`)

---

## Фаза 7. Финализация

### 7.1 Задачи

1. Сквозное тестирование всех функций
2. Обработка ошибок: QMessageBox для пользователя, logging для отладки
3. QSS-стили — единая тема оформления
4. README с инструкцией по запуску (`pip install -r requirements.txt` → `python main.py`)
5. `requirements.txt`: PyQt6, SQLAlchemy, httpx, openpyxl

---

## Сводка по фазам

| Фаза | Описание | Сложность |
|------|----------|-----------|
| 1 | Инициализация, модели, главное окно-заглушка | Базовая |
| 2 | Миграция из Excel | Средняя (парсинг текстов) |
| 3 | Сервисный слой + бизнес-логика | Средняя |
| 4 | UI — основные виджеты | Объёмная |
| 5 | Аналитика + графики | Средняя |
| 6 | Экспорт + AI-модуль | Средняя |
| 7 | Финализация, тесты, стили | Базовая |

---

## Важные технические решения

1. **SQLite** — достаточно для масштаба (один пользователь, сотни записей)
2. **PyQt6** — нативный GUI, не требует браузера или сервера
3. **Один Session на всё приложение** — создаётся в `main.py`, передаётся в виджеты через конструктор
4. **QThread для AI** — OpenRouter-запросы асинхронны через `AIChatWorker`, UI не блокируется
5. **Сервисный слой без PyQt6** — `services/` тестируется отдельно, не зависит от UI
6. **OpenRouter как AI-прокси** — единый API для GPT-4, Claude, Llama и других моделей
7. **Системный промпт в файле** — `system_prompt.txt` редактируется без пересборки

## Файлы для миграции

- `Опросы.xlsx` — основной источник данных (67 клиентов, ~93 записи опросов)
- `System-Prompt.txt` — системный промпт для AI-модуля
