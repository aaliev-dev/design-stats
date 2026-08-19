# Design Stats

Дашборд аналитики по design-задачам AdGuard (2018–2026).
Streamlit + Plotly + SQLite. ~6600 задач, ~260k переходов статусов.

## Быстрый старт

```bash
pip install -r requirements.txt

# Если design_insights.db уже есть — запускай сразу
streamlit run dashboard.py

# Если нужно обновить данные из Jira
export AIGUARD_JIRA_TOKEN="your_pat_token"
python3 fetch_data.py

# Экспорт метрик в CSV
python3 export_csv.py
```

Откроется на http://localhost:8501

## Структура

```
├── dashboard.py         # Streamlit-дашборд (~2400 строк, 5 табов)
├── fetch_data.py        # Пайплайн: Jira API → SQLite
├── export_csv.py        # Экспорт 16 метрик в CSV
├── design_insights.db   # SQLite (78MB, генерируется, в .gitignore)
├── requirements.txt
├── .streamlit/
│   └── config.toml      # Streamlit config
└── .gitignore
```

## Что показывает

| Таб | Содержимое |
|-----|-----------|
| 📊 Overview | KPI, throughput, залогированные часы, время в работе |
| 🔄 Cycle Time & Flow | Percentiles, CFD, Sankey, cycle time, flow efficiency, on-time, predictability, rework, FTR, review reject rate, YoY |
| 👥 People | Топ исполнителей, heatmap, worklog coverage, cycle time/rework/stale/WIP по людям |
| 🔬 Deep Dives | Worklog coverage, время в бэклоге, time-to-assign, stale tasks, rework, estimation accuracy, churn, throughput по компонентам |
| 🔍 Data Explorer | Поиск и фильтрация задач, экспорт в CSV |

## База данных

| Таблица | Строки | Описание |
|---------|--------|----------|
| `issues` | ~6600 | Задачи: key, project, status, assignee, dates, estimates, labels, components |
| `changelog` | ~118k | Полная история изменений полей |
| `status_transitions` | ~26k | Переходы статусов |
| `worklogs` | ~2700 | Учёт затраченного времени |

## Фильтры

В sidebar: по дате создания, проекту, исполнителю, статусу.
Все метрики пересчитываются при изменении фильтров.
