import json
import os
from pathlib import Path
from typing import Literal

import httpx
import ollama
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field, ValidationError

from app.schemas import ChatResponse, Product, Role
from app.tools import build_admin_tools, build_tools

DEFAULT_OLLAMA_MODEL = "gpt-oss:latest"
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(role: Role) -> str:
    system = (PROMPTS_DIR / "system.md").read_text(encoding="utf-8")
    role_rules = (PROMPTS_DIR / f"role_{role}.md").read_text(encoding="utf-8")
    # replace() rather than format(): the prompt contains literal JSON braces.
    return system.replace("{role_rules}", role_rules.strip()).strip()


PROMPTS: dict[Role, str] = {"user": _load_prompt("user"), "admin": _load_prompt("admin")}


class AssistantOutput(BaseModel):
    """Final answer of the assistant."""

    status: Literal["success", "error"]
    action: str = Field(description="One short sentence saying what you did")
    product_ids: list[int] = Field(default_factory=list, description="Ids of the products that answer the request")
    text: str | None = Field(default=None, description="Answer to a coffee question")
    errors: list[str] = Field(default_factory=list, description="What prevents fulfilling the request")


def build_chat_model() -> BaseChatModel:
    """Local Ollama model; OLLAMA_MODEL picks the model, OLLAMA_HOST the server address."""
    return ChatOllama(model=os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL))


def build_assistants(http: httpx.Client, model: BaseChatModel) -> dict[Role, object]:
    """One agent per role; http is a client for the Fruit Shop API that the tools call."""
    # Permissions are enforced here, not in the prompt: the customer's agent has no editing tools at all.
    # No checkpointer: every request starts a new conversation.
    read_tools = build_tools(http)
    tools: dict[Role, list[BaseTool]] = {"user": read_tools, "admin": read_tools + build_admin_tools(http)}
    return {
        role: create_agent(
            model, tools=tools[role], system_prompt=PROMPTS[role], response_format=ToolStrategy(AssistantOutput)
        )
        for role in tools
    }


def ask(assistant, http: httpx.Client, message: str) -> tuple[ChatResponse, int]:
    """Run the agent and return the answer with the HTTP status that suits it."""
    try:
        return _ask(assistant, http, message), 200
    except ConnectionError:
        return _llm_error("Ollama is not running"), 503
    except ollama.ResponseError as e:
        return _llm_error(f"Ollama error: {e.error}"), 502


def _ask(assistant, http: httpx.Client, message: str) -> ChatResponse:
    result = assistant.invoke({"messages": [{"role": "user", "content": message}]})
    output: AssistantOutput | None = result.get("structured_response")
    if output is None:
        # Local models sometimes write the structured answer as plain JSON text instead of calling the tool.
        reply = result["messages"][-1].text
        try:
            output = AssistantOutput.model_validate_json(reply)
        except ValidationError:
            return ChatResponse(
                status="error",
                action="The assistant answered without the required structure",
                data=reply or None,
                errors=["The assistant did not return a structured answer."],
            )

    # Product cards always come from the API, never from the model, so prices and stock can't be made up.
    products = []
    errors = list(output.errors)
    for product_id in output.product_ids:
        try:
            response = http.get(f"/products/{product_id}")
        except httpx.HTTPError:
            errors.append(f"Product {product_id}: the shop API is unavailable.")
            continue
        if response.is_success:
            products.append(Product.model_validate(response.json()))
        else:
            errors.append(f"Product {product_id} not found.")

    return ChatResponse(
        status="error" if errors or output.status == "error" else "success",
        action=output.action,
        data=products or output.text or None,
        errors=errors,
    )


def _llm_error(error: str) -> ChatResponse:
    return ChatResponse(status="error", action="Ask the language model", data=None, errors=[error])


def format_contract(response: ChatResponse) -> str:
    """Render the answer in the text contract: Status / Action / Data / Errors."""
    if isinstance(response.data, list):
        data = json.dumps([p.model_dump(mode="json") for p in response.data], ensure_ascii=False, indent=2)
    else:
        data = response.data or "-"
    errors = "; ".join(response.errors) or "-"
    return f"Status: {response.status}\nAction: {response.action}\nData: {data}\nErrors: {errors}"
