"""Terminal: formatted output and approval prompts."""
from __future__ import annotations

import sys
import threading
from contextlib import AbstractContextManager

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, InvalidResponse
from rich.syntax import Syntax
from rich.table import Table

from .i18n import t
from .tools import Tool

YES_ANSWERS = {"y", "yes", "s", "sim"}
NO_ANSWERS = {"n", "no", "nao", "não"}

# Parallel workers take turns at the terminal: one approval prompt at a time.
_APPROVAL_LOCK = threading.Lock()


def _make_console() -> Console:
    # Avoids encoding crashes on Windows when the output is redirected (e.g. to a file).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    return Console()


console = _make_console()


class YesNoConfirm(Confirm):
    """Yes/no prompt in the current language that accepts English and Portuguese answers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.choices = [t("ui.yes"), t("ui.no")]
        self.validate_error_message = t("ui.invalid_yes_no", yes=t("ui.yes"), no=t("ui.no"))

    def process_response(self, value: str) -> bool:
        answer = value.strip().lower()
        if answer in YES_ANSWERS:
            return True
        if answer in NO_ANSWERS:
            return False
        raise InvalidResponse(self.validate_error_message)


def confirm(question: str) -> bool:
    """Yes/no question. Enter, Ctrl+C or no terminal means no."""
    try:
        return YesNoConfirm.ask(question, default=False, console=console)
    except (EOFError, KeyboardInterrupt):
        return False


def ask_approval(tool: Tool, args: dict) -> bool:
    """Asks the operator whether the action may run."""
    with _APPROVAL_LOCK:
        _show_approval_request(tool, args)
        return confirm(t("ui.allow"))


def _show_approval_request(tool: Tool, args: dict) -> None:
    container = escape(str(args.get("container", "?")))
    message = t("ui.approval_request", tool=tool.name, container=container)
    console.print(Panel(message, title=t("ui.approval_title"), border_style="yellow"))


def show_answer(answer: str, label: str | None = None) -> None:
    title = t("ui.answer_title") + (f" · {escape(label)}" if label else "")
    text = _hard_line_breaks(answer or t("ui.no_answer"))
    console.print(Panel(Markdown(text), title=title, border_style="blue"))


def _hard_line_breaks(text: str) -> str:
    """In Markdown a single line break becomes a space; '  \\n' keeps the break the model meant."""
    return text.replace("\n", "  \n")


def show_diff(title: str, diff: str) -> None:
    if not diff.strip():
        show_dim(t("ui.empty_diff"))
        return
    console.print(Panel(Syntax(diff, "diff", theme="ansi_dark", word_wrap=True), title=escape(title), border_style="cyan"))


def show_table(title: str, columns: list[str], rows: list[tuple]) -> None:
    table = Table(title=title, title_justify="left")
    for column in columns:
        table.add_column(column)
    for row in rows:
        table.add_row(*(escape(str(cell)) for cell in row))
    console.print(table)


def spinner(message: str) -> AbstractContextManager:
    """Progress indicator for single-agent commands (chat, ask)."""
    return console.status(f"[dim]{escape(message)}[/]", spinner="dots")


def show_ok(message: str) -> None:
    console.print(f"[green]✓[/] {message}")


def show_error(message: str, detail: str = "", hint: str = "") -> None:
    line = f"[red]{message}[/]" + (f" {escape(detail)}" if detail else "")
    console.print(line + (f"\n  {hint}" if hint else ""))


def show_dim(message: str) -> None:
    console.print(f"[dim]{escape(message)}[/]")
