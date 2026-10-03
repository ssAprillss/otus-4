from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.main import create_app
from main import run
from tests.test_assistant import APPLE, final, scripted, tool_call


def test_cli_prints_answer_in_contract_format(tmp_path):
    api = TestClient(create_app(str(tmp_path / "cli.db"), chat_model=scripted()))
    api.post("/products", json=APPLE)
    model = scripted(tool_call("list_products"), final(status="success", action="Поиск яблок", product_ids=[1]))

    text, exit_code = run("Какие яблоки есть?", "user", api, model)

    assert exit_code == 0
    lines = text.splitlines()
    assert lines[0] == "Status: success"
    assert lines[1] == "Action: Поиск яблок"
    assert lines[2] == "Data: ["
    assert lines[-1] == "Errors: -"


def test_cli_admin_role_edits_product(tmp_path):
    api = TestClient(create_app(str(tmp_path / "cli.db"), chat_model=scripted()))
    api.post("/products", json=APPLE)
    model = scripted(
        tool_call("update_product", product_id=1, quantity=5),
        final(status="success", action="Остаток изменён", product_ids=[1]),
    )

    _, exit_code = run("Поставь яблокам остаток 5", "admin", api, model)

    assert exit_code == 0
    assert api.get("/products/1").json()["quantity"] == 5


def test_cli_exit_code_is_1_on_error(tmp_path):
    api = TestClient(create_app(str(tmp_path / "cli.db"), chat_model=scripted()))

    text, exit_code = run("Привет", "user", api, scripted(AIMessage(content="не JSON")))

    assert exit_code == 1
    assert text.startswith("Status: error")
