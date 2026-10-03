# Отчёт: агент — API-оператор фруктового магазина

Агент на LangChain принимает запрос на естественном языке, сам выбирает нужную операцию
HTTP API магазина, вызывает её через LangChain tool и возвращает ответ в фиксированном формате
`Status / Action / Data / Errors`.

## Структура проекта

| Путь | Что внутри |
|---|---|
| [main.py](main.py) | CLI: `python main.py "запрос" [--role admin]` |
| [app/main.py](app/main.py) | HTTP API магазина (FastAPI) и эндпоинт `POST /assistant/chat` |
| [app/repository.py](app/repository.py) | хранение товаров в SQLite |
| [app/tools.py](app/tools.py) | LangChain tools, вызывающие API по HTTP |
| [app/assistant.py](app/assistant.py) | модель, сборка агента, разбор ответа, вывод контракта |
| [prompts/](prompts/) | системный промпт и правила ролей в Markdown |
| [tests/](tests/) | тесты pytest (55 шт.) |
| [docs/test-run.log](docs/test-run.log) | полный лог проверочных запросов |
| [.env.example](.env.example) | пример настроек |

## LLM и её настройка

Используется **локальная модель через [Ollama](https://ollama.com)**: по умолчанию
`gpt-oss:latest` (20B, поддерживает вызов инструментов). Подключение — `ChatOllama` из
`langchain-ollama` ([app/assistant.py:L42–L44](app/assistant.py#L42-L44)). Ключи API не
нужны, секретов в репозитории нет.

1. Установите Ollama: https://ollama.com/download.
2. Скачайте модель:
   ```bash
   ollama pull gpt-oss
   ```
3. Скопируйте `.env.example` в `.env` и при необходимости поправьте значения. Файл `.env`
   внесён в `.gitignore`.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `OLLAMA_MODEL` | `gpt-oss:latest` | модель Ollama (должна поддерживать tools) |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | адрес сервера Ollama |
| `FRUIT_SHOP_API_URL` | `http://127.0.0.1:8000` | адрес API, который вызывают tools |
| `FRUIT_SHOP_DB` | `fruits.db` | файл базы SQLite |

## Выбранное API и операции

Минимальное API реализовано прямо в репозитории (FastAPI + SQLite,
[app/main.py](app/main.py)). Агент вызывает его по HTTP через `httpx`.

| Операция | HTTP | LangChain tool | Кому доступен |
|---|---|---|---|
| Список товаров | `GET /products` | `list_products` | всем |
| Карточка товара | `GET /products/{id}` | `get_product` | всем |
| Создать товар | `POST /products` | `add_product` | только `--role admin` |
| Обновить товар | `GET` + `PUT /products/{id}` | `update_product` (меняет только названные поля) | только `--role admin` |

Права ограничены в коде: агент для обычного пользователя не получает инструментов записи
([app/assistant.py:L47–L58](app/assistant.py#L47-L58)).

> Роль задаётся параметром `--role` без проверки — учебное упрощение. В реальном сервисе роль
> нужно определять по аутентификации.

## Запуск

Команды для Windows, работают и в cmd, и в PowerShell. Выполняйте их из папки проекта.
Ollama должна быть запущена (см. раздел выше).

**1. Подготовка (один раз):**

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

**2. Терминал 1 — API магазина:**

```powershell
.venv\Scripts\activate
uvicorn app.main:create_app --factory
```

**3. Терминал 2 — агент** (API из терминала 1 должно работать):

```powershell
.venv\Scripts\activate
python main.py "Какие яблоки у вас есть?"
python main.py "Добавь грушу Конференция, цена 199 рублей, в наличии 30" --role admin
```

> **Важно:** `.venv\Scripts\activate` нужно выполнять в **каждом** новом окне терминала; после
> активации в начале строки появляется `(.venv)`. Без неё Windows может запустить вместо Python
> заглушку Microsoft Store: команда печатает только `Python` и ничего не делает. Можно и без
> активации, указав Python окружения явно: `.venv\Scripts\python main.py "…"`.
>
> Если PowerShell отвечает, что выполнение сценариев отключено, разрешите его для текущего окна:
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, затем повторите активацию.

В репозитории лежит база [fruits.db](fruits.db) с примерами товаров, так что каталог сразу
не пуст. Учтите, что админские запросы меняют эту базу.

Ответ печатается в stdout, отладочный вывод вызовов tools — в stderr. Код выхода: `0` при
`Status: success`, `1` при `Status: error`.

Тесты: `pip install -r requirements-dev.txt`, затем `pytest`.

## Подтверждение критериев

| Критерий | Где смотреть |
|---|---|
| Объявление tools | [app/tools.py:L13–L26](app/tools.py#L13-L26) (`list_products`, `get_product`), [app/tools.py:L29–L57](app/tools.py#L29-L57) (`add_product`, `update_product`) |
| Реальный HTTP-вызов API | [app/tools.py:L60–L77](app/tools.py#L60-L77), сам запрос — [app/tools.py:L63](app/tools.py#L63) (`http.request(method, path, json=body)`) |
| Структурированный результат tool | [app/tools.py:L64–L75](app/tools.py#L64-L75): JSON `{"ok", "status_code", "data" / "error"}` |
| Вывод результата tool в консоль | логгер — [app/tools.py:L76](app/tools.py#L76); настройка вывода в CLI — [main.py:L37](main.py#L37) |
| Сборка агента | [app/assistant.py:L47–L58](app/assistant.py#L47-L58) (`create_agent`, tools, системный промпт, структурированный ответ) |
| Запуск из CLI | [main.py:L27–L43](main.py#L27-L43) |
| Контракт ответа | правила для модели — [prompts/system.md:L26–L38](prompts/system.md#L26-L38); схема ответа — [app/schemas.py:L37–L45](app/schemas.py#L37-L45); вывод в виде `Status / Action / Data / Errors` — [app/assistant.py:L113–L120](app/assistant.py#L113-L120); описание — раздел «Контракт ответа» ниже |
| Промпты | [prompts/](prompts/) и раздел «Использованные промпты» ниже |
| Секреты не закоммичены | секретов нет (локальная модель); `.env` в [.gitignore](.gitignore); пример — [.env.example](.env.example) |

### Пример: запрос → API-метод

Запрос «Поставь малине цену 399 рублей» от администратора должен привести к поиску товара
(`list_products` → `GET /products`) и обновлению карточки (`update_product` →
`GET` + `PUT /products/4`). Фактический лог вызовов (список товаров сокращён):

```text
$ python main.py "Поставь малине цену 399 рублей" --role admin
[app.tools] tool list_products: GET /products -> {"ok": true, "status_code": 200, "data": [ … ]}
[app.tools] tool update_product: GET /products/4 -> {"ok": true, "status_code": 200, "data": {"name": "Малина", "description": "Свежая, лоток 250 г", "price": "349.00", "quantity": 15, "id": 4}}
[app.tools] tool update_product: PUT /products/4 -> {"ok": true, "status_code": 200, "data": {"name": "Малина", "description": "Свежая, лоток 250 г", "price": "399", "quantity": 15, "id": 4}}
Status: success
Action: Обновил цену малин
```

Агент сам нашёл id малины в каталоге и изменил только цену: описание и остаток остались прежними.

## Контракт ответа

```text
Status: success | error
Action: <что сделал агент>
Data: <результат API: карточки товаров в JSON | текст ответа на вопрос о кофе | ->
Errors: <ошибки через "; " | ->
```

- `Status` — `error`, если список ошибок не пуст. Это проверяет код, а не модель.
- `Data` — карточки товаров, которые сервер получает из API по id, выбранным моделью.
  Модель не переписывает цены и остатки, поэтому не может их исказить.
- Тот же контракт возвращает HTTP-эндпоинт `POST /assistant/chat` в виде JSON с полями
  `status`, `action`, `data`, `errors`.

## Проверочные запросы

7 запросов, выполненных через CLI на модели `gpt-oss:latest`. Четыре из них (№ 1–4) привели
к вызову API-tools, всего 6 HTTP-запросов к API.
Запросы выполнялись на копии рабочей базы. Полный вывод с логами — [docs/test-run.log](docs/test-run.log).

| № | Запрос | Роль | Вызванные tools → HTTP | Status | Результат |
|---|---|---|---|---|---|
| 1 | Какие яблоки у вас есть? | user | `list_products` → `GET /products` | success | 4 карточки яблок |
| 2 | Покажи карточку товара с id 4 | user | `get_product` → `GET /products/4` | success | карточка малины |
| 3 | Добавь грушу Конференция, сладкая, цена 199 рублей за кг, в наличии 30 | admin | `add_product` → `POST /products` | success | создан товар #9 |
| 4 | Поставь малине цену 399 рублей | admin | `list_products` → `GET /products`; `update_product` → `GET` + `PUT /products/4` | success | цена 349 → 399 |
| 5 | Поставь малине цену 1 рубль | user | — (инструментов записи у user нет) | error | «Изменять каталог может только администратор» |
| 6 | Как готовить кофе в турке? | user | — (tools не нужны) | success | текстовый рецепт |
| 7 | Какая завтра погода? | user | — | error | «Запрос не относится к каталогу или к кофе» |

Ответы агента (логи tools с полным списком товаров сокращены):

```text
$ python main.py "Какие яблоки у вас есть?"
[app.tools] tool list_products: GET /products -> {"ok": true, "status_code": 200, "data": [ … ]}
Status: success
Action: Поиск яблок в каталоге
Data: [
  {"name": "Яблоко", "description": "Гренни Смит, зелёное, цена за кг", "price": "129.90", "quantity": 100, "id": 3},
  {"name": "Яблоко Голден Делишес", "description": "Жёлтое, сладкое, медовое, цена за кг", "price": "139.90", "quantity": 80, "id": 5},
  {"name": "Яблоко Фуджи", "description": "Хрустящее, очень сладкое, цена за кг", "price": "189.90", "quantity": 60, "id": 6},
  {"name": "Яблоко Гала", "description": "Красно-жёлтое, сладкое с лёгкой кислинкой, цена за кг", "price": "159.90", "quantity": 70, "id": 7}
]
Errors: -

$ python main.py "Покажи карточку товара с id 4"
[app.tools] tool get_product: GET /products/4 -> {"ok": true, "status_code": 200, "data": {"name": "Малина", "description": "Свежая, лоток 250 г", "price": "349.00", "quantity": 15, "id": 4}}
Status: success
Action: Найдена карточка товара
Data: [
  {"name": "Малина", "description": "Свежая, лоток 250 г", "price": "349.00", "quantity": 15, "id": 4}
]
Errors: -

$ python main.py "Добавь грушу Конференция, сладкая, цена 199 рублей за кг, в наличии 30" --role admin
[app.tools] tool add_product: POST /products -> {"ok": true, "status_code": 201, "data": {"name": "груша Конференция", "description": "сладкая", "price": "199", "quantity": 30, "id": 9}}
Status: success
Action: Добавил грушу Конференция
Data: [
  {"name": "груша Конференция", "description": "сладкая", "price": "199", "quantity": 30, "id": 9}
]
Errors: -

$ python main.py "Поставь малине цену 1 рубль"
Status: error
Action: Невозможно изменить цену
Data: -
Errors: Изменять каталог может только администратор

$ python main.py "Как готовить кофе в турке?"
Status: success
Action: Ответ на вопрос о кофе
Data: Для приготовления кофе в турке вам понадобится:
1. **Подготовка** – используйте мелко молотый кофе … (полный текст — в docs/test-run.log)
Errors: -

$ python main.py "Какая завтра погода?"
Status: error
Action: Запрос не относится к каталогу
Data: -
Errors: Запрос не относится к каталогу или к кофе
```

Ответ на запрос 4 приведён выше, в разделе «Пример: запрос → API-метод». Для удобства чтения
JSON в `Data` здесь записан в одну строку на карточку; в консоли он выводится с отступами.

## Использованные промпты

Промпты хранятся в Markdown и загружаются кодом из файлов
([app/assistant.py:L22–L29](app/assistant.py#L22-L29)): итоговый системный промпт — это
[prompts/system.md](prompts/system.md), куда вместо `{role_rules}` подставляются правила роли.

### Системный промпт — [prompts/system.md](prompts/system.md)

```markdown
You are an API operator agent for an online fruit shop. You fulfil requests by calling the shop's HTTP API
through tools. Each request is independent: there is no conversation history.

## What you help with

1. The shop's products. Use the catalogue tools; never invent products, prices or stock levels.
   Ordering is not available. The catalogue is the only information about the shop you have, so anything
   else would be made up: never mention contacting the shop, phone, email, website, address, opening hours,
   delivery, payment, notifications or reservations, and never suggest any other way to buy.
2. Coffee: kinds of coffee and how to brew it. Answer from general knowledge with only well-established
   brewing advice. The shop does not sell coffee.

## Permissions

{role_rules}

## Rules for calling tools

- Product ids are not known in advance: call list_products to find products by name, and get_product
  to read one card by id.
- Never guess ids, prices or other values: take them from tool results or from the request.
- Every tool returns JSON: {"ok": true, "data": ...} on success, {"ok": false, "error": ...} on failure.
  If a tool fails, do not retry with made-up values; report the failure in errors.
- Coffee questions need no tools.

## Response contract

Always finish by calling AssistantOutput. Write action, text and errors in the requester's language.

- action: one short sentence saying what you did, for example "Поиск яблок в каталоге".
- product_ids: ids of the catalogue products that answer the request. The server attaches their cards,
  so do not copy product details anywhere. Leave empty if no product fits.
- text: the answer to a coffee question; leave empty for product questions.
- errors: what prevents fulfilling the request: the product is not in the catalogue, it is out of stock
  (quantity 0), a tool returned an error, or the topic is neither products nor coffee. If the requester wants
  to buy or order anything, always add the error "Оформление заказов недоступно" (in the requester's language),
  while still listing the requested products in product_ids.
- status: "error" if errors is not empty, otherwise "success".
```

### Правила роли `user` — [prompts/role_user.md](prompts/role_user.md)

```markdown
The requester is a customer: you can only look products up. If asked to add or change products, add the error
"Изменять каталог может только администратор" (in the requester's language) and change nothing.
```

### Правила роли `admin` — [prompts/role_admin.md](prompts/role_admin.md)

```markdown
The requester is a shop administrator: besides looking products up, you can add products with add_product
and edit product cards with update_product. Change exactly what was asked and nothing else; if the request
does not say which product or which values to set, change nothing and report that in errors.
When calling update_product, pass only the fields to change.
After a change, put the id of every added or edited product in product_ids.
```

### Описания tools (тоже часть промпта)

LangChain передаёт модели описания инструментов из docstring
([app/tools.py](app/tools.py)):

| Tool | Описание для модели |
|---|---|
| `list_products` | List every product in the shop: id, name, description, price in rubles and quantity in stock. |
| `get_product(product_id)` | Get one product card by its id. |
| `add_product(name, price, quantity=0, description=None)` | Add a new product to the catalogue. Price is in rubles, quantity is the number of units in stock. |
| `update_product(product_id, name?, description?, price?, quantity?)` | Edit a product card. Pass only the fields to change; the others keep their current values. |
| `AssistantOutput` | Final answer of the assistant (поля `status`, `action`, `product_ids`, `text`, `errors`). |

### Пользовательские шаблоны

Запрос пользователя передаётся модели как есть, одним сообщением, без истории. Шаблоны
запросов, на которых проверялся агент:

| Шаблон | Ожидаемый tool | Роль |
|---|---|---|
| `Какие <товары> у вас есть?` | `list_products` | любая |
| `Покажи карточку товара с id <id>` | `get_product` | любая |
| `Есть ли <товар>?` / `Сколько стоит <товар>?` | `list_products` | любая |
| `Добавь <название>, <описание>, цена <цена> рублей, в наличии <количество>` | `add_product` | admin |
| `Поставь <товару> цену <цена> рублей` / `Поставь <товару> остаток <количество>` | `list_products` + `update_product` | admin |
| `Как готовить кофе <способ>?` | — | любая |
