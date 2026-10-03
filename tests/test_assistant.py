import json
import logging
from decimal import Decimal
from itertools import count

import httpx
import ollama
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from pydantic import Field

from app.assistant import DEFAULT_OLLAMA_MODEL, PROMPTS, build_chat_model, format_contract
from app.main import create_app
from app.schemas import ChatResponse, Product
from app.tools import build_admin_tools, build_tools

APPLE = {"name": "Яблоко", "description": "Гренни Смит", "price": "129.90", "quantity": 50}

_call_ids = count()


class ScriptedChatModel(GenericFakeChatModel):
    """Replays scripted replies and records what the agent sent to the model."""

    received: list = Field(default_factory=list)
    bound_tools: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.bound_tools.append(sorted(t.name for t in tools))
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.received.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class FailingChatModel(ScriptedChatModel):
    error: Exception

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise self.error


def scripted(*replies):
    return ScriptedChatModel(messages=iter(replies))


def tool_call(tool_name, /, **args):
    return AIMessage(content="", tool_calls=[{"name": tool_name, "args": args, "id": f"call_{next(_call_ids)}"}])


def final(**args):
    """The model's structured answer."""
    return tool_call("AssistantOutput", **args)


def dialogue(messages):
    return [m.content for m in messages if not isinstance(m, SystemMessage)]


def make_client(tmp_path, model):
    # The agent's tools call the API in-process through TestClient, which is an httpx client.
    app = create_app(str(tmp_path / "test.db"), chat_model=model, api_client_factory=TestClient)
    client = TestClient(app)
    client.post("/products", json=APPLE)
    return client


def test_chat_returns_product_cards_from_catalogue(tmp_path):
    model = scripted(
        tool_call("list_products"),
        final(status="success", action="Поиск яблок в каталоге", product_ids=[1]),
    )

    response = make_client(tmp_path, model).post("/assistant/chat", json={"message": "Какие яблоки есть?"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "action": "Поиск яблок в каталоге",
        "data": [{**APPLE, "id": 1}],
        "errors": [],
    }
    assert model.received[0][0].content == PROMPTS["user"]
    tool_result = model.received[1][-1]
    assert isinstance(tool_result, ToolMessage)
    assert json.loads(tool_result.content)["data"][0]["name"] == "Яблоко"


def test_chat_reports_unknown_product_id(tmp_path):
    model = scripted(final(status="success", action="Поиск груш в каталоге", product_ids=[1, 42]))

    body = make_client(tmp_path, model).post("/assistant/chat", json={"message": "Есть груши?"}).json()

    assert body["status"] == "error"
    assert [p["id"] for p in body["data"]] == [1]
    assert body["errors"] == ["Product 42 not found."]


def test_chat_returns_text_answer_for_coffee(tmp_path):
    model = scripted(final(status="success", action="Рассказ о приготовлении кофе", text="Залейте кофе водой 93 °C."))

    body = make_client(tmp_path, model).post("/assistant/chat", json={"message": "Как готовить кофе?"}).json()

    assert body == {
        "status": "success",
        "action": "Рассказ о приготовлении кофе",
        "data": "Залейте кофе водой 93 °C.",
        "errors": [],
    }


def test_chat_status_is_error_when_errors_reported(tmp_path):
    model = scripted(final(status="success", action="Проверка темы запроса", errors=["Могу помочь только с фруктами"]))

    body = make_client(tmp_path, model).post("/assistant/chat", json={"message": "Какая погода?"}).json()

    assert body == {
        "status": "error",
        "action": "Проверка темы запроса",
        "data": None,
        "errors": ["Могу помочь только с фруктами"],
    }


def test_chat_keeps_no_history(tmp_path):
    model = scripted(
        final(status="success", action="Первый", product_ids=[1]),
        final(status="success", action="Второй", product_ids=[1]),
    )
    client = make_client(tmp_path, model)

    client.post("/assistant/chat", json={"message": "Есть яблоки?"})
    client.post("/assistant/chat", json={"message": "А сколько стоят?"})

    assert dialogue(model.received[1]) == ["А сколько стоят?"]


def test_chat_accepts_structured_answer_written_as_text(tmp_path):
    reply = json.dumps({"status": "success", "action": "Поиск яблок", "product_ids": [1], "text": "", "errors": []})
    model = scripted(AIMessage(content=reply))

    body = make_client(tmp_path, model).post("/assistant/chat", json={"message": "Есть яблоки?"}).json()

    assert body == {"status": "success", "action": "Поиск яблок", "data": [{**APPLE, "id": 1}], "errors": []}


def test_chat_reports_unstructured_answer(tmp_path):
    model = scripted(AIMessage(content="Просто текст"))

    response = make_client(tmp_path, model).post("/assistant/chat", json={"message": "Привет"})

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert response.json()["data"] == "Просто текст"
    assert response.json()["errors"] == ["The assistant did not return a structured answer."]


@pytest.mark.parametrize(
    ("role", "expected_tools"),
    [
        (None, ["AssistantOutput", "get_product", "list_products"]),
        ("user", ["AssistantOutput", "get_product", "list_products"]),
        ("admin", ["AssistantOutput", "add_product", "get_product", "list_products", "update_product"]),
    ],
)
def test_chat_gives_editing_tools_only_to_admin(tmp_path, role, expected_tools):
    model = scripted(final(status="success", action="Готово"))
    payload = {"message": "Привет"} | ({"role": role} if role else {})

    make_client(tmp_path, model).post("/assistant/chat", json=payload)

    assert model.bound_tools[-1] == expected_tools
    assert model.received[0][0].content == PROMPTS[role or "user"]


def test_admin_edits_product_through_chat(tmp_path):
    model = scripted(
        tool_call("update_product", product_id=1, price="99.90"),
        final(status="success", action="Цена яблока изменена на 99,90 ₽", product_ids=[1]),
    )
    client = make_client(tmp_path, model)

    body = client.post("/assistant/chat", json={"message": "Поставь яблоку цену 99.90", "role": "admin"}).json()

    assert body["status"] == "success"
    assert body["data"] == [{**APPLE, "price": "99.90", "id": 1}]
    assert client.get("/products/1").json()["price"] == "99.90"


def test_admin_adds_product_through_chat(tmp_path):
    model = scripted(
        tool_call("add_product", name="Груша", price=150, quantity=10),
        final(status="success", action="Добавлена груша", product_ids=[2]),
    )
    client = make_client(tmp_path, model)

    body = client.post("/assistant/chat", json={"message": "Добавь грушу", "role": "admin"}).json()

    [product] = body["data"]
    assert (product["id"], product["name"], Decimal(product["price"]), product["quantity"]) == (2, "Груша", 150, 10)
    assert len(client.get("/products").json()) == 2


def test_user_cannot_edit_even_if_model_tries(tmp_path):
    model = scripted(
        tool_call("update_product", product_id=1, price="1"),
        final(status="error", action="Попытка изменить цену", errors=["Нет прав"]),
    )
    client = make_client(tmp_path, model)

    client.post("/assistant/chat", json={"message": "Поставь яблоку цену 1 рубль"})

    assert client.get("/products/1").json()["price"] == "129.90"
    tool_result = model.received[1][-1]
    assert isinstance(tool_result, ToolMessage)
    assert tool_result.status == "error"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": ""},
        {"message": "   "},
        {"message": "a" * 2001},
        {"message": "hi", "conversation_id": "x"},
        {"message": "hi", "role": "root"},
    ],
)
def test_chat_rejects_invalid_request(tmp_path, payload):
    assert make_client(tmp_path, scripted()).post("/assistant/chat", json=payload).status_code == 422


def test_chat_reports_ollama_not_running(tmp_path):
    model = FailingChatModel(messages=iter([]), error=ConnectionError("Failed to connect to Ollama"))

    response = make_client(tmp_path, model).post("/assistant/chat", json={"message": "Привет"})

    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["errors"] == ["Ollama is not running"]


def test_chat_reports_ollama_error(tmp_path):
    model = FailingChatModel(messages=iter([]), error=ollama.ResponseError("model 'x' not found", 404))

    response = make_client(tmp_path, model).post("/assistant/chat", json={"message": "Привет"})

    assert response.status_code == 502
    assert response.json()["status"] == "error"
    assert response.json()["errors"] == ["Ollama error: model 'x' not found"]


@pytest.fixture
def api(tmp_path):
    """HTTP client of a real app instance with one product."""
    client = TestClient(create_app(str(tmp_path / "tools.db"), chat_model=scripted()))
    client.post("/products", json=APPLE)
    return client


@pytest.fixture
def tools(api):
    return {t.name: t for t in build_tools(api) + build_admin_tools(api)}


def test_list_products_tool(tools):
    result = json.loads(tools["list_products"].invoke({}))

    assert result == {"ok": True, "status_code": 200, "data": [{**APPLE, "id": 1}]}


def test_get_product_tool(tools):
    assert json.loads(tools["get_product"].invoke({"product_id": 1}))["data"]["price"] == "129.90"
    assert json.loads(tools["get_product"].invoke({"product_id": 42})) == {
        "ok": False,
        "status_code": 404,
        "error": "Product 42 not found",
    }


def test_add_product_tool(api, tools):
    result = json.loads(tools["add_product"].invoke({"name": "Киви", "price": "79.50"}))

    assert result["status_code"] == 201
    assert result["data"] == {"id": 2, "name": "Киви", "description": None, "price": "79.50", "quantity": 0}
    assert api.get("/products/2").json()["name"] == "Киви"


@pytest.mark.parametrize("args", [{"name": "", "price": "10"}, {"name": "Киви", "price": "-1"}])
def test_add_product_tool_reports_invalid_data(api, tools, args):
    result = json.loads(tools["add_product"].invoke(args))

    assert (result["ok"], result["status_code"]) == (False, 422)
    assert len(api.get("/products").json()) == 1


def test_update_product_tool_changes_only_given_fields(api, tools):
    result = json.loads(tools["update_product"].invoke({"product_id": 1, "quantity": 7}))

    assert result["data"] == {**APPLE, "quantity": 7, "id": 1}
    assert api.get("/products/1").json() == {**APPLE, "quantity": 7, "id": 1}


def test_update_product_tool_reports_missing_product(tools):
    result = json.loads(tools["update_product"].invoke({"product_id": 42, "price": "10"}))

    assert (result["ok"], result["status_code"]) == (False, 404)


def test_update_product_tool_reports_invalid_data(api, tools):
    result = json.loads(tools["update_product"].invoke({"product_id": 1, "price": "0"}))

    assert (result["ok"], result["status_code"]) == (False, 422)
    assert api.get("/products/1").json()["price"] == "129.90"


def test_tools_report_unavailable_api():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    http = httpx.Client(base_url="http://shop", transport=httpx.MockTransport(refuse))
    list_products = build_tools(http)[0]

    assert json.loads(list_products.invoke({})) == {"ok": False, "error": "The shop API is unavailable (ConnectError)"}


def test_tools_log_their_results(tools, caplog):
    with caplog.at_level(logging.INFO, logger="app.tools"):
        tools["get_product"].invoke({"product_id": 1})

    assert "tool get_product: GET /products/1 -> " in caplog.text
    assert '"name": "Яблоко"' in caplog.text


def test_format_contract_with_products():
    response = ChatResponse(status="success", action="Поиск яблок", data=[Product(**APPLE, id=1)], errors=[])

    text = format_contract(response)

    assert text.startswith("Status: success\nAction: Поиск яблок\nData: [")
    assert '"name": "Яблоко"' in text
    assert text.endswith("\nErrors: -")


def test_format_contract_with_errors():
    response = ChatResponse(status="error", action="Проверка", data=None, errors=["Нет товара", "Нет прав"])

    assert format_contract(response) == "Status: error\nAction: Проверка\nData: -\nErrors: Нет товара; Нет прав"


def test_chat_model_is_configurable(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    assert build_chat_model().model == DEFAULT_OLLAMA_MODEL

    monkeypatch.setenv("OLLAMA_MODEL", "deepseek-r1:14b")
    assert build_chat_model().model == "deepseek-r1:14b"
