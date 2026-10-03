"""CLI for the fruit shop API operator agent.

Usage: python main.py "Какие яблоки есть?" [--role admin]
The Fruit Shop API must be running: uvicorn app.main:create_app --factory
"""

import argparse
import logging
import os
import sys

import httpx
from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel

from app.assistant import ask, build_assistants, build_chat_model, format_contract
from app.main import DEFAULT_API_URL


def run(request: str, role: str, http: httpx.Client, model: BaseChatModel) -> tuple[str, int]:
    """Answer one request; returns the contract text and the process exit code."""
    assistant = build_assistants(http, model)[role]
    response, _ = ask(assistant, http, request)
    return format_contract(response), 0 if response.status == "success" else 1


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Fruit shop API operator agent")
    parser.add_argument("request", help='request in plain language, e.g. "Какие яблоки есть?"')
    parser.add_argument("--role", choices=["user", "admin"], default="user", help="admin may add and edit products")
    args = parser.parse_args(argv)

    load_dotenv()
    # Tool calls and their results are logged to stderr; the answer goes to stdout.
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    with httpx.Client(base_url=os.getenv("FRUIT_SHOP_API_URL", DEFAULT_API_URL), timeout=30) as http:
        text, exit_code = run(args.request, args.role, http, build_chat_model())
    print(text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
