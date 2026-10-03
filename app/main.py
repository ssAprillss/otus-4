import logging
import os
from collections.abc import Callable

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from langchain_core.language_models import BaseChatModel

from app.assistant import ask, build_assistants, build_chat_model
from app.repository import ProductRepository
from app.schemas import ChatRequest, ChatResponse, Product, ProductIn

DEFAULT_DB_PATH = "fruits.db"
DEFAULT_API_URL = "http://127.0.0.1:8000"


def api_client(app: FastAPI) -> httpx.Client:
    """HTTP client the agent's tools use to call this API; FRUIT_SHOP_API_URL must point to it."""
    return httpx.Client(base_url=os.getenv("FRUIT_SHOP_API_URL", DEFAULT_API_URL), timeout=30)


def create_app(
    db_path: str | None = None,
    chat_model: BaseChatModel | None = None,
    api_client_factory: Callable[[FastAPI], httpx.Client] = api_client,
) -> FastAPI:
    load_dotenv()
    # Tool calls and their results are logged by app.tools.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = FastAPI(title="Fruit Shop API", version="1.0.0")
    repository = ProductRepository(db_path or os.getenv("FRUIT_SHOP_DB", DEFAULT_DB_PATH))
    http = api_client_factory(app)
    assistants = build_assistants(http, chat_model or build_chat_model())

    @app.post("/products", response_model=Product, status_code=status.HTTP_201_CREATED, summary="Add a product")
    def add_product(data: ProductIn) -> Product:
        return repository.add(data)

    @app.get("/products", response_model=list[Product], summary="List all products")
    def list_products() -> list[Product]:
        return repository.list()

    @app.get("/products/{product_id}", response_model=Product, summary="Get a product card")
    def get_product(product_id: int) -> Product:
        product = repository.get(product_id)
        if product is None:
            raise _not_found(product_id)
        return product

    @app.put("/products/{product_id}", response_model=Product, summary="Update a product card")
    def update_product(product_id: int, data: ProductIn) -> Product:
        product = repository.update(product_id, data)
        if product is None:
            raise _not_found(product_id)
        return product

    @app.post(
        "/assistant/chat",
        response_model=ChatResponse,
        responses={502: {"model": ChatResponse}, 503: {"model": ChatResponse}},
        summary="Ask the shop assistant",
    )
    def chat(request: ChatRequest):
        response, status_code = ask(assistants[request.role], http, request.message)
        return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))

    return app


def _not_found(product_id: int) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Product {product_id} not found")
