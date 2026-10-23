"""Dockerfile checks: unpinned images, root user, curl | sh, secrets in ENV/ARG and more."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from ..redaction import is_sensitive_key, redact
from ..workspace import Workspace, WorkspaceError
from .heuristics import plausible_secret
from .model import Finding, Rule

UNPINNED_IMAGE = Rule("DF001", "medium", "sec.df001.title", "sec.df001.fix")
RUNS_AS_ROOT = Rule("DF002", "high", "sec.df002.title", "sec.df002.fix")
PIPE_TO_SHELL = Rule("DF003", "high", "sec.df003.title", "sec.df003.fix")
SECRET_IN_IMAGE = Rule("DF004", "high", "sec.df004.title", "sec.df004.fix")
WHOLE_CONTEXT = Rule("DF005", "medium", "sec.df005.title", "sec.df005.fix")
NO_HEALTHCHECK = Rule("DF006", "low", "sec.df006.title", "sec.df006.fix")
APT_RECOMMENDS = Rule("DF007", "low", "sec.df007.title", "sec.df007.fix")
WORLD_WRITABLE = Rule("DF008", "medium", "sec.df008.title", "sec.df008.fix")

PATTERNS = ("Dockerfile", "Dockerfile.*", "*.dockerfile")
ROOT_USERS = {"root", "0", "0:0", "root:root"}
_PIPE_RE = re.compile(r"(?i)\b(?:curl|wget)\b[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b")
_CHMOD_RE = re.compile(r"\bchmod\s+(?:-R\s+)?0?777\b")
DETAIL_CHARS = 160


@dataclass(frozen=True)
class Instruction:
    line: int
    keyword: str
    args: str


# --- Parsing -------------------------------------------------------------------------------------

def parse(text: str) -> list[Instruction]:
    """Instructions with their first line number; joins `\\` continuations and skips comments."""
    instructions, buffer, start = [], [], 0
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not buffer:
            start = number
        buffer.append(stripped.rstrip("\\").strip())
        if not stripped.endswith("\\"):
            instructions.append(_instruction(start, " ".join(buffer)))
            buffer = []
    if buffer:
        instructions.append(_instruction(start, " ".join(buffer)))
    return instructions


def _instruction(line: int, text: str) -> Instruction:
    keyword, _, args = text.partition(" ")
    return Instruction(line, keyword.upper(), args.strip())


def stages(instructions: list[Instruction]) -> list[list[Instruction]]:
    result: list[list[Instruction]] = []
    for instruction in instructions:
        if instruction.keyword == "FROM" or not result:
            result.append([])
        result[-1].append(instruction)
    return result


def base_image(args: str) -> tuple[str, str | None]:
    """FROM [--platform=x] image [AS name] -> (image, name)."""
    parts = [part for part in args.split() if not part.startswith("--")]
    image = parts[0] if parts else ""
    alias = parts[2] if len(parts) >= 3 and parts[1].lower() == "as" else None
    return image, alias


def is_unpinned(image: str, aliases: set[str] = frozenset()) -> bool:
    """`node` or `node:latest` float; `node:20`, a digest, scratch, a build stage or ${VAR} do not."""
    if not image or "$" in image or "@" in image or image.lower() == "scratch" or image in aliases:
        return False
    name = image.rsplit("/", 1)[-1]
    return ":" not in name or name.endswith(":latest")


# --- Checks ----------------------------------------------------------------------------------------

def check(workspace: Workspace, path: str) -> list[Finding]:
    try:
        instructions = parse(workspace.text(path))
    except WorkspaceError:
        return []
    groups = stages(instructions)
    findings = _image_findings(path, groups) + _instruction_findings(path, instructions)
    if groups:
        findings += _final_stage_findings(path, groups[-1])
    return findings + _context_findings(workspace, path, instructions)


def _image_findings(path: str, groups: list[list[Instruction]]) -> list[Finding]:
    findings, aliases = [], set()
    for stage in groups:
        image, alias = base_image(stage[0].args)
        if is_unpinned(image, aliases):
            findings.append(UNPINNED_IMAGE.finding(f"{path}:{stage[0].line}", f"FROM {image}"))
        if alias:
            aliases.add(alias)
    return findings


def _instruction_findings(path: str, instructions: list[Instruction]) -> list[Finding]:
    findings = []
    for instruction in instructions:
        where = f"{path}:{instruction.line}"
        findings += [rule.finding(where, _evidence(instruction)) for rule in _rules_for(instruction)]
    return findings


def _rules_for(instruction: Instruction) -> list[Rule]:
    if instruction.keyword in ("ENV", "ARG"):
        return [SECRET_IN_IMAGE] if _has_secret(instruction.args) else []
    if instruction.keyword != "RUN":
        return []
    checks = (
        (PIPE_TO_SHELL, bool(_PIPE_RE.search(instruction.args))),
        (WORLD_WRITABLE, bool(_CHMOD_RE.search(instruction.args))),
        (APT_RECOMMENDS, "apt-get install" in instruction.args and "--no-install-recommends" not in instruction.args),
    )
    return [rule for rule, matched in checks if matched]


def _has_secret(args: str) -> bool:
    return any(is_sensitive_key(key) and plausible_secret(value) for key, value in _assignments(args))


def _assignments(args: str) -> list[tuple[str, str]]:
    """`KEY=value KEY2=value2` or the legacy `KEY value` form."""
    if "=" not in args.split(" ", 1)[0]:
        key, _, value = args.partition(" ")
        return [(key, value.strip())]
    pairs = [token.partition("=") for token in args.split()]
    return [(key, value.strip("\"'")) for key, _, value in pairs]


def _final_stage_findings(path: str, stage: list[Instruction]) -> list[Finding]:
    where = f"{path}:{stage[0].line}"
    users = [i.args.split()[0] for i in stage if i.keyword == "USER" and i.args]
    findings = []
    if not users or users[-1].lower() in ROOT_USERS:
        findings.append(RUNS_AS_ROOT.finding(where, f"USER {users[-1]}" if users else ""))
    if not any(i.keyword == "HEALTHCHECK" and not i.args.upper().startswith("NONE") for i in stage):
        findings.append(NO_HEALTHCHECK.finding(where))
    return findings


def _context_findings(workspace: Workspace, path: str, instructions: list[Instruction]) -> list[Finding]:
    """COPY . without a .dockerignore can put .env, .git and keys inside the image."""
    folder = PurePosixPath(path).parent
    if (workspace.root / folder / ".dockerignore").exists():
        return []
    for instruction in instructions:
        if instruction.keyword in ("COPY", "ADD") and _copies_everything(instruction.args):
            return [WHOLE_CONTEXT.finding(f"{path}:{instruction.line}", _evidence(instruction))]
    return []


def _copies_everything(args: str) -> bool:
    sources = [part for part in args.split() if not part.startswith("--")][:-1]
    return any(source in (".", "./") for source in sources)


def _evidence(instruction: Instruction) -> str:
    return redact(f"{instruction.keyword} {instruction.args}")[:DETAIL_CHARS]
