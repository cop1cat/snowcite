# Установка

snowcite распространяется как Python-пакет и запускается в виде MCP-сервера
внутри Claude Code. Для работы потребуются:

- [uv](https://docs.astral.sh/uv/) — предоставляет команду `uvx`, через
  которую запускается сервер;
- [Claude Code](https://claude.com/claude-code) — клиент;
- один из компиляторов: [Typst](https://typst.app/) (рекомендуется) или
  [tectonic](https://tectonic-typesetting.github.io/) для LaTeX.

## Подключение к Claude Code

```bash
claude mcp add snowcite -- uvx snowcite
```

С API-ключами (увеличивают лимиты запросов и ускоряют поиск):

```bash
claude mcp add snowcite \
  -e SNOWCITE_SEMANTIC_SCHOLAR_API_KEY=xxx \
  -e SNOWCITE_OPENALEX_EMAIL=you@example.com \
  -- uvx snowcite
```

## Установка компилятора

Typst предпочтительнее: поддерживает Unicode без дополнительных настроек,
распространяется одним статически слинкованным исполняемым файлом и
компилирует документы инкрементально.

=== "macOS"

    ```bash
    brew install typst
    # Дополнительно — LaTeX-бэкенд
    brew install tectonic
    # Для экспорта в .docx
    brew install pandoc
    ```

=== "Linux"

    ```bash
    # Typst: готовый бинарник
    curl -L https://github.com/typst/typst/releases/latest/download/typst-x86_64-unknown-linux-musl.tar.xz | tar -xJ
    sudo mv typst-*/typst /usr/local/bin/

    # tectonic доступен в большинстве дистрибутивов
    sudo apt install tectonic
    ```

=== "Windows"

    ```powershell
    winget install --id Typst.Typst
    winget install --id tectonic.tectonic
    ```

## Проверка окружения

После подключения сервера попросите Claude выполнить диагностику:

```
Запусти check_environment.
```

Инструмент вернёт структурированный отчёт о доступных компиляторах, API и
переменных окружения. Записи с уровнем `error` требуют исправления,
`warn` указывают на отсутствие опциональных возможностей (например,
без pandoc не работает экспорт в `.docx`).

## API-ключи

### Semantic Scholar

Без ключа доступно 100 запросов за 5 минут. С ключом
([заявка](https://www.semanticscholar.org/product/api)) лимит поднимается
до 100 запросов в секунду. Задаётся через переменную
`SNOWCITE_SEMANTIC_SCHOLAR_API_KEY`.

### OpenAlex

Так называемый polite pool OpenAlex гарантирует стабильные лимиты при
передаче email в параметре `mailto=`. Задаётся через переменную
`SNOWCITE_OPENALEX_EMAIL`.

### Crossref

Использует тот же email, что и OpenAlex. Отдельного ключа не требует.

### PubMed

Ключ не требуется. NCBI рекомендует не более трёх запросов в секунду,
встроенный семафор соблюдает этот лимит автоматически.
