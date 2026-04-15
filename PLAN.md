# snowball-mcp — итоговый план

MCP-сервер для systematic literature review: поиск по arXiv / Semantic Scholar / OpenAlex, snowball-расширение через цитирования, ревью статей **через чат с Claude** (без отдельного UI), генерация LaTeX и компиляция PDF через tectonic.

## Ключевые архитектурные решения

1. **Ревью через чат, не через web UI.** Claude батчами читает абстракты, сам пре-фильтрует "очевидно релевантно / очевидно мимо / borderline", показывает borderline-статьи юзеру с обоснованием. Решения летят в SQLite через MCP-tools. Никакого Starlette, браузера, второго терминала.
2. **SQLite — единственный стор.** Дедуп по DOI, fallback на нормализованный title.
3. **Tectonic вместо системного TeXLive.** Сам качает пакеты, сам разбирается с bibtex.
4. **Минимум зависимостей:** `mcp[cli]`, `httpx`, `aiosqlite`, `arxiv`, `pydantic-settings`. Никаких web-фреймворков.
5. **Состояние решений с обоснованием** (`reason` поле) — готовый аудит-trail для PRISMA-диаграммы.

## Схема БД

```sql
papers (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,            -- 'arxiv' | 'semantic_scholar' | 'openalex'
  source_id TEXT NOT NULL,
  doi TEXT,
  title TEXT NOT NULL,
  title_normalized TEXT NOT NULL,  -- для fallback-дедупа
  authors_json TEXT NOT NULL,
  year INTEGER,
  venue TEXT,
  abstract TEXT,
  pdf_url TEXT,
  bibtex TEXT,
  metadata_json TEXT,              -- сырые поля от API
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(source, source_id),
  UNIQUE(doi) WHERE doi IS NOT NULL
)
CREATE INDEX idx_papers_title_norm ON papers(title_normalized);

reviews (
  paper_id INTEGER PRIMARY KEY REFERENCES papers(id),
  status TEXT NOT NULL,            -- 'approved' | 'maybe' | 'rejected' | 'unreviewed'
  reason TEXT,                     -- обоснование (от Claude или юзера)
  note TEXT,
  reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  reviewed_by TEXT                 -- 'auto' | 'user'
)

review_criteria (
  id INTEGER PRIMARY KEY,
  criteria_text TEXT NOT NULL,     -- inclusion/exclusion критерии в свободной форме
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)

citations (
  source_paper_id INTEGER REFERENCES papers(id),
  cited_paper_id INTEGER REFERENCES papers(id),
  direction TEXT NOT NULL,         -- 'references' | 'citations'
  PRIMARY KEY (source_paper_id, cited_paper_id, direction)
)
```

## MCP tools

### Поиск и сохранение
- `search_papers(query, sources=["arxiv","semantic_scholar","openalex"], limit=20, year_from=None, year_to=None)` — поиск, дедуп между источниками, возврат списка (без сохранения)
- `save_papers(papers)` — INSERT OR IGNORE, возвращает `{saved, duplicates}`
- `get_saved_papers(status=None, source=None, year_from=None, year_to=None, search=None, limit=100, offset=0)`
- `get_paper_details(paper_id)`
- `expand_citations(paper_id, direction, limit=20)` — references или citations; arXiv → fallback на Semantic Scholar по DOI

### Ревью (chat-native)
- `set_review_criteria(criteria_text)` — фиксирует inclusion/exclusion критерии
- `get_review_criteria()` — Claude перечитывает перед каждым батчем (защита от дрифта)
- `get_unreviewed_papers(limit=20, filters=None)` — батч для пре-фильтра
- `set_review_status(paper_ids, status, reason, note=None, reviewed_by="auto")` — **batch**, принимает список id
- `get_review_progress()` — `{total, approved, maybe, rejected, unreviewed}`

### LaTeX / PDF
- `write_latex(sections, title, author, bibliography_style="plain", output_dir="data")` — секции готовые (Claude написал текст), сервер собирает .tex + .bib из approved
- `compile_pdf(tex_path)` — `subprocess.run(["tectonic", tex_path])`, возврат `{pdf_path, success, log}`

## Workflow ревью (для будущих сессий — описано в CLAUDE.md)

1. Юзер: "вот тема X, найди статьи"
2. Claude: `set_review_criteria("...")`, `search_papers(...)`, `save_papers(...)`
3. Claude: `get_unreviewed_papers(limit=20)` → читает абстракты → сам решает очевидные → `set_review_status([ids], "approved"|"rejected", reason="auto: ...", reviewed_by="auto")`
4. Borderline-статьи показывает юзеру **по одной** с рассуждением, ждёт `i`/`e`/`m`
5. После решения юзера: `set_review_status([id], status, reason="manual: ...", reviewed_by="user")`
6. Повторяет батчи до `get_review_progress()` без unreviewed
7. Snowball: на approved зовёт `expand_citations`, save_papers, новые попадают в unreviewed
8. После ревью: `write_latex(sections, ...)` → `compile_pdf(...)`

## API-клиенты

- **arXiv** (`arxiv` PyPI): rate limit 1 req / 3 sec; не поддерживает цитирования
- **Semantic Scholar** (`https://api.semanticscholar.org/graph/v1/`): 100 req/5min без ключа, 100 req/sec с ключом; references + citations
- **OpenAlex** (`https://api.openalex.org/works`): polite pool через email; abstracts как inverted index — конвертить в plaintext

## Конфиг (pydantic-settings)

```python
class Settings(BaseSettings):
    semantic_scholar_api_key: str | None = None
    openalex_email: str | None = None
    arxiv_delay: float = 3.0
    db_path: str = "data/papers.db"
    model_config = SettingsConfigDict(env_prefix="SNOWBALL_", env_file=".env")
```

## Структура проекта

```
snowball-mcp/
├── pyproject.toml
├── CLAUDE.md
├── PLAN.md
├── server.py                  # MCP entrypoint, регистрация tools
├── snowball/
│   ├── __init__.py
│   ├── settings.py            # Pydantic settings
│   ├── db.py                  # aiosqlite, миграции, dedup helpers
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── arxiv_client.py
│   │   ├── semantic_scholar.py
│   │   └── openalex.py
│   ├── tools/
│   │   ├── search.py          # search_papers, save_papers, get_*, expand_citations
│   │   ├── review.py          # criteria + status tools
│   │   └── latex.py           # write_latex, compile_pdf
│   ├── bibtex.py              # генерация bibtex из метаданных
│   └── dedup.py               # title normalization
└── data/                      # gitignored
    └── papers.db
```

## Фазы реализации

Каждая фаза = один коммит, проверяемая работа.

### Фаза 1 — Скелет
- `uv add "mcp[cli]" httpx aiosqlite arxiv pydantic-settings`
- `settings.py`, `db.py` (init schema, миграции)
- `server.py` с зарегистрированными tool-заглушками (raise NotImplementedError)
- Запуск через `uv run python server.py`

### Фаза 2 — Поиск
- Три клиента в `sources/`
- Дедуп: DOI primary, normalized title fallback (≥0.9 similarity)
- `search_papers`, `save_papers`
- Smoke-тест с реальными API на узкий запрос

### Фаза 3 — Чтение
- `get_saved_papers` (с фильтрами), `get_paper_details`

### Фаза 4 — Snowball
- `expand_citations` (Semantic Scholar / OpenAlex)
- arXiv fallback через DOI lookup в Semantic Scholar
- Запись в `citations` таблицу

### Фаза 5 — Ревью
- `set_review_criteria` / `get_review_criteria`
- `get_unreviewed_papers` (батчи, фильтры)
- `set_review_status` (батч-операция)
- `get_review_progress`
- В CLAUDE.md — детальный workflow ревью для Claude

### Фаза 6 — LaTeX/PDF
- Jinja2-шаблон для .tex (article class, biblatex)
- `bibtex.py`: генерация из метаданных если не пришёл от API
- `write_latex`, `compile_pdf`
- Проверка наличия tectonic при старте сервера → понятная ошибка с инструкцией установки

## Что НЕ делаем

- Web UI / Starlette / htmx / jinja для UI
- Markdown export/import для ревью
- Multi-reviewer / blinding (одиночный researcher)
- Zotero интеграция
- Свой PDF-парсинг (используем то что приходит от API)
- MCP elicitation — обычный чат + tool calls достаточно

## Ограничения, о которых надо помнить

- **Дрифт критериев в long-running ревью** — `get_review_criteria` перед каждым батчем
- **Контекст-окно** — батчи по 10–20, не загружать 100 абстрактов сразу
- **Bias от Claude при borderline** — показывать рассуждение нейтрально, без явной рекомендации
- **OpenAlex API key** — с февраля 2026 политика поменялась, проверить на момент запуска
- **Tectonic** — отдельная установка (`brew install tectonic`)
