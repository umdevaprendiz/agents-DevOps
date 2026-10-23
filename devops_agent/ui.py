"""Terminal: saída formatada e pedido de aprovação."""
from __future__ import annotations

import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, InvalidResponse

from .tools import Tool

YES_ANSWERS = {"s", "sim", "y", "yes"}
NO_ANSWERS = {"n", "nao", "não", "no"}


def _make_console() -> Console:
    # Evita erro de encoding no Windows quando a saída é redirecionada (ex.: para um arquivo).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    return Console()


console = _make_console()


class YesNoConfirm(Confirm):
    """Confirmação s/n que aceita respostas em português e inglês."""

    choices = ["s", "n"]
    validate_error_message = "[prompt.invalid]Digite s ou n"

    def process_response(self, value: str) -> bool:
        answer = value.strip().lower()
        if answer in YES_ANSWERS:
            return True
        if answer in NO_ANSWERS:
            return False
        raise InvalidResponse(self.validate_error_message)


def ask_approval(tool: Tool, args: dict) -> bool:
    """Pergunta ao operador se a ação pode rodar. Na dúvida (Enter, Ctrl+C, sem terminal), nega."""
    _show_approval_request(tool, args)
    try:
        return YesNoConfirm.ask("Permitir?", default=False, console=console)
    except (EOFError, KeyboardInterrupt):
        return False


def _show_approval_request(tool: Tool, args: dict) -> None:
    target = escape(str(args.get("container", "?")))
    console.print(
        Panel(
            f"O agente quer executar [bold]{tool.name}[/] no container [bold]{target}[/].",
            title="Aprovação necessária",
            border_style="yellow",
        )
    )


def show_answer(answer: str) -> None:
    text = _hard_line_breaks(answer or "_(o modelo não respondeu)_")
    console.print(Panel(Markdown(text), title="Agente", border_style="blue"))


def _hard_line_breaks(text: str) -> str:
    """Em Markdown uma quebra simples vira espaço; '  \\n' mantém a quebra que o modelo quis."""
    return text.replace("\n", "  \n")


def show_ok(message: str) -> None:
    console.print(f"[green]✓[/] {message}")


def show_error(message: str, detail: str = "", hint: str = "") -> None:
    line = f"[red]{message}[/]" + (f" {escape(detail)}" if detail else "")
    console.print(line + (f"\n  {hint}" if hint else ""))


def show_dim(message: str) -> None:
    console.print(f"[dim]{message}[/]")
