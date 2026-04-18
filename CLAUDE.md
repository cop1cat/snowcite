# CLAUDE.md

Гайд для Claude Code-сессий в этом репо. Подробный план — см. `PLAN.md`.

## Что это

`snowball-mcp` — MCP-сервер для systematic literature review. Поиск по arXiv / Semantic Scholar / OpenAlex, snowball через цитирования, ревью статей через чат, генерация LaTeX и PDF через tectonic.

## Главное архитектурное правило

**Ревью статей идёт через чат, не через UI.** Никаких веб-интерфейсов, браузеров, второго терминала. Claude батчами читает абстракты, сам пре-фильтрует, borderline-кейсы показывает юзеру в чате. Не предлагай добавить Starlette/Flask/htmx — это сознательное архитектурное решение.

## Как вести ревью (это твой основной workflow)

1. **Перед каждым батчем** зови `get_review_criteria()` — критерии могли быть заданы давно, защита от дрифта.
2. **Прочитай summary**: `get_review_summary()` — текущая картина: кластеры, ключевые papers, stale-предупреждения. Если summary stale или counts расходятся — скажи об этом юзеру. Если summary ещё нет (первый батч) — пропусти.
3. `get_unreviewed_papers(limit=20)` — бери батчами по 10–20, не пытайся загрузить всё.
4. Для каждой статьи в батче реши **сам**:
   - **Очевидно релевантно** (matches criteria) → батч в `set_review_status([ids], "approved", reason="auto: matches criterion X", reviewed_by="auto")`
   - **Очевидно мимо** → батч в `set_review_status([ids], "rejected", reason="auto: off-topic — Y", reviewed_by="auto")`
   - **Borderline** → отложи, покажешь юзеру
5. Borderline — **по одной**, юзеру:
   ```
   Paper 7/87: "Title" (Year, Authors)
   Кратко: ...
   Почему borderline: ...
   i / e / m?
   ```
   **Не давай рекомендацию** — она создаёт bias. Только факты + почему сложно решить.
6. Юзер отвечает → `set_review_status([id], status, reason="manual: <user comment if any>", reviewed_by="user")`.
7. **После каждого батча** (не после каждой статьи!) — `save_review_summary(summary, clusters)`:
   - Summary ≤500 слов, rolling (включай всё предыдущее, не append)
   - Используй категории из `review_criteria`, не выдумывай свои кластеры
   - Clusters: `[{"topic": "...", "paper_ids": [...], "count": N}]`
   - Это singleton — перезаписывается при каждом вызове
8. `get_review_progress()` периодически, чтобы юзер видел прогресс.

### Правила работы с summary

- **Не доверяй summary слепо.** Это твоя же генерация, которая может содержать неточности. `get_review_summary()` возвращает live counts — всегда сверяй их с тем что написано в summary text.
- **Stale = регенерируй.** Если `stale=true` (после snowball или ручных правок) — прочти approved/maybe papers и перегенерируй summary.
- **Summary для outline, papers для текста.** При написании LaTeX — summary помогает со структурой, но абстракты бери через `get_papers_for_writing(cluster=...)`.
- **Кластеры = категории юзера.** Если юзер задал категории в criteria — используй их. Не переизобретай.

## Snowball-цикл

После первого прохода ревью:
1. `get_saved_papers(status="approved")`
2. Для каждой → `expand_citations(id, "references")` и/или `"citations"`
3. `save_papers(...)` — новые попадают в unreviewed (дедуп по DOI работает автоматически). **Это ставит `stale=TRUE` на summary.**
4. `get_review_summary()` → увидишь stale warning → регенерируй summary с учётом новых papers
5. Повтори ревью-цикл на новых

## Команды

```bash
# установка
uv sync

# запуск сервера (для отладки)
uv run python server.py

# подключение к Claude Code
claude mcp add snowball -- uv run python server.py

# tectonic (нужен для compile_pdf)
brew install tectonic
```

## Структура

```
server.py                  # MCP entrypoint
snowball/
├── settings.py            # pydantic-settings, env SNOWBALL_*
├── db.py                  # aiosqlite, миграции
├── sources/               # arxiv / semantic_scholar / openalex клиенты
├── tools/                 # search.py / review.py / latex.py
├── bibtex.py              # генерация bibtex
└── dedup.py               # title normalization
data/papers.db             # gitignored
```

## Конвенции

- **Дедуп**: DOI — primary key. Нет DOI → normalized title (lowercase, strip пунктуация, ≥0.9 similarity).
- **Источники в БД**: `'arxiv' | 'semantic_scholar' | 'openalex'`.
- **Статусы ревью**: `'approved' | 'maybe' | 'rejected' | 'unreviewed'`.
- **`reviewed_by`**: `'auto'` (Claude решил сам) или `'user'` (юзер подтвердил). Это критично для аудита.
- **`reason` обязательно** при `set_review_status` — даже короткое "matches criterion X". Это PRISMA-trail.
- **Все async** — aiosqlite, httpx.AsyncClient.

## Чего НЕ делаем

- Не добавляй web UI (Starlette/Flask/jinja для UI/htmx)
- Не интегрируй Zotero (юзер им не пользуется)
- Не делай MCP elicitation — обычные tool calls + чат достаточно
- Не парси PDF сам — используй абстракты от API
- Не используй системный TeXLive — только tectonic
- Не предлагай рекомендацию в borderline-кейсах — только факты
- Не добавляй markdown export/import для ревью — было обсуждено и отклонено

## API-источники: важные детали

- **arXiv** (lib `arxiv`): rate limit 1 req / 3 sec. Не поддерживает цитирования — для `expand_citations` fallback на Semantic Scholar по DOI.
- **Semantic Scholar**: 100 req/5min без ключа, 100 req/sec с ключом (`SNOWBALL_SEMANTIC_SCHOLAR_API_KEY`). Поддерживает references и citations.
- **OpenAlex**: polite pool через email (`SNOWBALL_OPENALEX_EMAIL`). Abstracts приходят как inverted index — конвертить в plaintext перед сохранением.

## Текущая фаза

См. PLAN.md → раздел "Фазы реализации". Каждая фаза = один коммит.
