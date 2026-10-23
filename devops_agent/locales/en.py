"""English texts. Keys and {placeholders} must match pt_br.py (checked by tests/test_i18n.py).
Literal braces are doubled: {{ and }}."""

MESSAGES = {
    # --- Texts sent to the model -------------------------------------------------------------
    "prompt.system": """You are an autonomous DevOps agent. You help with anything DevOps: containers, infrastructure and configuration files, application code, logs, security alerts and preventing failures.

How you work:
1. Investigate before concluding. When you do not know where the problem is, start with collect_diagnostics. Docker tools: list_containers, inspect_container, get_container_logs, get_container_stats. Project tools: list_files, read_file, search_files, git_status, git_log, git_diff.
2. Rely only on what the tools returned. Never invent names, files, variables, logs or numbers.
3. To change files, call propose_change with the smallest edit that solves the problem. Change only what is necessary: no refactors, no style changes, never secrets (use references such as ${{VARIABLE}}). The proposal goes to its own git branch; the operator reviews it and decides.
4. Only propose restart/start/stop when it can actually fix the problem; those actions need human approval. If one is denied, do not repeat it; suggest alternatives.
5. Values shown as [REDACTED] were hidden on purpose to protect secrets. Never try to reveal them.
6. Be direct and brief. Before a long investigation, say in one sentence what you will check. Ask the operator a question only when you cannot continue without the answer.
7. Report results honestly, including what failed or what you could not verify.

Exit code reference: 0 = finished normally; 1 = application error; 2 = usage/configuration error; 125-127 = Docker error or command not found; 137 = killed with SIGKILL (usually out of memory, check oom_killed); 139 = segfault; 143 = stopped with SIGTERM.

When you report problems, answer in English with one block per problem:
**Problem:** what is broken (container, file or service)
**Error:** the exact error message or evidence (log line, exit code, configuration line)
**Cause:** why it happens
**How to fix:** concrete steps, commands or settings to use
**Proposed change:** the proposal id, if you created one with propose_change
For other requests, answer in English, naturally and concisely.""",
    "prompt.step_limit": "Step limit reached. Answer now with what you found so far, in the requested format.",
    "prompt.evidence": (
        "You answered without using any tool. Do not invent data: call inspect_container "
        "and get_container_logs for the container before concluding."
    ),
    "prompt.action_denied": "Action DENIED by the operator. Do not try it again; explain what they can do instead.",
    "prompt.unknown_tool": "Error: the tool '{name}' does not exist. Available: {available}.",
    "prompt.suggest": (
        "Review this project{focus} and propose only the changes that are really necessary: bugs, "
        "security risks, wrong configuration or things likely to fail. Investigate first (list_files, "
        "read_file, search_files and the Docker tools), then call propose_change once per independent fix, "
        "with the smallest possible edit. If nothing needs to change, say so and propose nothing."
    ),
    "prompt.suggest_focus": ", focusing on: {focus}",
    "prompt.debug": (
        "Debug {target}. Find what is failing and how to fix it. Start with collect_diagnostics, then "
        "investigate each problem in depth: container logs and inspect, and the related project files "
        "(Dockerfile, compose, configuration, code). Explain every problem in the requested format, with "
        "the exact commands or settings to use. When a file change fixes a problem, call propose_change "
        "with the smallest edit. Do not propose changes that are not needed."
    ),
    "prompt.debug_everything": "the whole environment (containers and project)",
    "prompt.explain": (
        "Explain this proposed change to the operator in plain language: what changes, why it is needed, "
        "the risks and how to test it. Be brief.\n\nTitle: {title}\nAuthor's explanation: {explanation}\n\n"
        "Diff:\n{diff}"
    ),
    # --- Agent ------------------------------------------------------------------------------------
    "agent.thinking": "thinking...",
    "agent.unknown_tool": "✗ unknown tool: {name}",
    "agent.denied": "action denied",
    "agent.evidence_rejected": "answer without evidence rejected; asking for an investigation",
    "agent.tool_error": "Error: {error}",
    "text.truncated_start": "...(start cut)",
    "text.truncated_end": "...(end cut)",
    "tools.missing_params": "missing parameters: {names}",
    # --- Docker -------------------------------------------------------------------------------------
    "docker.cli_missing": "Docker CLI not found in PATH.",
    "docker.timeout": "'docker {command}' took longer than {seconds}s.",
    "docker.exit_code": "'docker {command}' exited with code {code}",
    "docker.invalid_name": "invalid container name: {value}",
    "docker.invalid_since": "invalid value for since: {value}",
    "docker.no_logs": "(no logs)",
    "docker.restarted": "Container '{container}' restarted.",
    "docker.started": "Container '{container}' started.",
    "docker.stopped": "Container '{container}' stopped.",
    # --- Workspace and git ----------------------------------------------------------------------------
    "workspace.outside": "path outside the workspace: {path}",
    "workspace.secret": "access denied to a secret file: {path}",
    "workspace.not_found": "file not found: {path}",
    "workspace.too_big": "file too big to read (limit {size} KB): {path}",
    "workspace.binary": "binary file, not readable as text: {path}",
    "workspace.file_header": "{path} (lines {first}-{last} of {total})",
    "workspace.no_files": "(no files)",
    "workspace.more": "...and {count} more",
    "workspace.no_matches": "(no matches)",
    "workspace.no_changes": "(no uncommitted changes)",
    "diag.docker_unavailable": "Containers: Docker unavailable ({error}).",
    "diag.containers_ok": "Containers: no problems detected.",
    "diag.containers_title": "Containers with problems:",
    "diag.logs_title": "Project log files with errors:",
    "diag.logs_ok": "Project log files: no errors found.",
    "diag.log_file": "- {path} ({count} error lines, latest:)",
    "diag.infra_title": "Infrastructure files:",
    "diag.infra_none": "Infrastructure files: none found.",
    "git.cli_missing": "git not found in PATH.",
    "git.timeout": "'git {command}' took longer than {seconds}s.",
    "git.exit_code": "'git {command}' exited with code {code}",
    # --- Proposals ------------------------------------------------------------------------------------
    "proposal.not_repo": "the workspace is not a git repository (run 'git init' and make a first commit).",
    "proposal.bad_edits": "edits must be a list of {{path, old_text, new_text}} objects.",
    "proposal.no_edits": "the proposal has no edits.",
    "proposal.file_exists": "{path} already exists; to change it, put the exact text to replace in old_text.",
    "proposal.file_missing": "{path} does not exist in the last commit; to create it, use old_text=''.",
    "proposal.not_found": (
        "old_text was not found in {path}. Read the file again and copy the text exactly, "
        "without the line-number prefix."
    ),
    "proposal.ambiguous": "old_text appears {count} times in {path}; include more surrounding lines so it is unique.",
    "proposal.redacted_old": "old_text contains [REDACTED]: that line holds a secret and the agent cannot edit it ({path}).",
    "proposal.secret_new": "new_text looks like it contains a secret; use a reference such as ${{VARIABLE}} instead ({path}).",
    "proposal.created": (
        "Proposal {id} created on branch {branch}. The operator can review it with /diff {id} "
        "and decide with /apply {id} or /pr {id}."
    ),
    "proposal.none": "No pending proposals.",
    "proposal.unknown": "No pending proposal matches '{ref}'.",
    "proposal.nothing_to_undo": "No applied proposal to undo.",
    "proposal.already_undone": "The last applied proposal ({commit}) was already undone.",
    "proposal.no_remote": "This repository has no 'origin' remote to open a pull request.",
    "proposal.pushed_no_gh": (
        "Branch {branch} pushed. Install the GitHub CLI (gh) to open the PR automatically, "
        "or open it on GitHub from {branch} into {base}."
    ),
    # --- Chat commands --------------------------------------------------------------------------------
    "cmd.unknown": "Unknown command: {name}. Type /help to see the commands.",
    "cmd.failed": "Could not complete the command:",
    "cmd.help_title": "Commands",
    "cmd.col.command": "Command",
    "cmd.col.aliases": "Aliases",
    "cmd.col.description": "Description",
    "cmd.col.id": "ID",
    "cmd.col.title": "Title",
    "cmd.col.branch": "Branch",
    "cmd.help.help": "Shows this list",
    "cmd.help.debug": "Finds what is failing (containers, logs, project), explains each bug and proposes fixes",
    "cmd.help.suggest": "The agent reviews the project and proposes only necessary changes",
    "cmd.help.proposals": "Lists pending proposals",
    "cmd.help.diff": "Shows the changes of a proposal (default: the latest)",
    "cmd.help.explain": "Explains a proposal in plain language",
    "cmd.help.apply": "Merges a proposal into your current branch",
    "cmd.help.pr": "Pushes a proposal and opens a pull request",
    "cmd.help.discard": "Deletes a proposal",
    "cmd.help.undo": "Reverts the last applied proposal (with a new commit)",
    "cmd.help.status": "Model, language, workspace, branch and proposals",
    "cmd.help.clear": "Clears the conversation",
    "cmd.help.exit": "Quits",
    "cmd.proposals_title": "Pending proposals",
    "cmd.proposal_ready": "[bold cyan]Proposal {id}[/]: {title} → /diff {id} · /explain {id} · /apply {id} · /pr {id}",
    "cmd.no_new_proposals": "no change proposed",
    "cmd.confirm_apply": "Merge proposal {id} into branch {branch}?",
    "cmd.applied": "Proposal {id} merged into {branch}. Undo with /undo.",
    "cmd.confirm_discard": "Delete proposal {id}?",
    "cmd.discarded": "Proposal {id} deleted.",
    "cmd.confirm_undo": "Revert the last applied proposal with a new commit?",
    "cmd.undone": "Proposal reverted (merge {commit}).",
    "cmd.confirm_pr": "Push branch {branch} to origin and open a pull request?",
    "cmd.status_title": "Status",
    "cmd.status.model": "Model",
    "cmd.status.language": "Language",
    "cmd.status.workspace": "Workspace",
    "cmd.status.branch": "Branch",
    "cmd.status.proposals": "Pending proposals",
    "cmd.not_a_repo": "(not a git repository)",
    # --- Monitor ------------------------------------------------------------------------------------
    "monitor.oom": " (OOMKilled: killed for lack of memory)",
    "monitor.restarting": "restart loop ({count} restarts, last exit code {exit_code}){oom}",
    "monitor.dead": "is in the 'dead' state",
    "monitor.exited": "stopped with exit code {exit_code}{oom}",
    "monitor.unhealthy": "healthcheck failing ({streak} consecutive failures)",
    "monitor.restarted": "restarted {count}x since the last check{oom}",
    "monitor.probable_loop": "already restarted {count}x and came up a few minutes ago (probable loop){oom}",
    "monitor.log_errors": "{count} error lines in the logs in the last {window}s, e.g.: {example}",
    "monitor.task": (
        "The monitor detected a problem in container '{container}': {detail}. "
        "Investigate the cause (logs, inspect, stats and the related project files) and explain it in the "
        "requested format. If a file change fixes it, propose it with propose_change; if an action fixes it, "
        "propose that action."
    ),
    # --- Terminal -----------------------------------------------------------------------------------
    "ui.yes": "y",
    "ui.no": "n",
    "ui.invalid_yes_no": "[prompt.invalid]Type {yes} or {no}",
    "ui.approval_request": "The agent wants to run [bold]{tool}[/] on container [bold]{container}[/].",
    "ui.approval_title": "Approval required",
    "ui.allow": "Allow?",
    "ui.no_answer": "_(the model did not answer)_",
    "ui.answer_title": "Agent",
    "ui.empty_diff": "(empty diff)",
    # --- Command line ---------------------------------------------------------------------------------
    "cli.docker_ok": "Docker {version}",
    "cli.docker_down": "✗ Docker unavailable:",
    "cli.docker_hint": "Start Docker and try again.",
    "cli.ollama_ok": "Ollama with model {model}",
    "cli.model_missing": "✗ Model '{model}' not found.",
    "cli.model_hint": "Run: [bold]ollama pull {model}[/]",
    "cli.ollama_down": "✗ Ollama did not respond:",
    "cli.ollama_hint": "Start Ollama and try again.",
    "cli.ollama_error": "Ollama error:",
    "cli.ollama_unreachable": "Could not reach Ollama:",
    "cli.workspace_ok": "Workspace {path} (branch {branch})",
    "cli.workspace_no_git": "Workspace {path} (not a git repository: change proposals are disabled)",
    "cli.workspace_missing": "✗ Workspace not found:",
    "cli.workspace_hint": "Set AGENT_WORKSPACE to an existing folder.",
    "cli.chat_intro": "Chat with the agent. Type [bold]/help[/] for commands and [bold]/exit[/] to quit.\n",
    "cli.prompt": "you>",
    "cli.chat_reset": "conversation cleared",
    "cli.interrupted": "interrupted",
    "cli.no_problems": "No problems found.",
    "cli.problems_found": "{count} container(s) with problems.",
    "cli.issue_header": "Problem in {container}",
    "cli.watching": "Watching every {interval}s with {workers} worker(s). [bold]Ctrl+C[/] to stop.\n",
    "cli.heartbeat": "{time} · {new} new problem(s) · {running} investigation(s) in progress",
    "cli.docker_query_error": "Error querying Docker:",
    "cli.investigation_failed": "Investigation of {container} failed:",
    "cli.stopped": "stopped",
    "cli.help.description": "Autonomous DevOps agent powered by a local LLM (Ollama).",
    "cli.help.model": "Ollama model (default: AGENT_MODEL or qwen3:4b)",
    "cli.help.lang": "language: en or pt-BR (default: AGENT_LANGUAGE or the system language)",
    "cli.help.chat": "interactive chat with the agent (type /help inside)",
    "cli.help.ask": "ask one question and exit",
    "cli.help.debug": "find what is failing, explain each bug and propose fixes",
    "cli.help.focus": "optional focus: a container, a file or a symptom",
    "cli.review_in_chat": "Review and decide in the chat: devops-agent chat, then /diff, /explain, /apply or /pr.",
    "cli.help.check": "scan once and investigate every problem found",
    "cli.help.watch": "watch continuously",
    "cli.help.only": "only these containers (comma separated)",
    "cli.help.scan_logs": "also look for error lines in the logs",
    "cli.help.interval": "seconds between scans (default 30)",
    "cli.help.cooldown": "seconds before alerting about the same container again (default 600)",
    "cli.help.workers": "parallel investigations (default: AGENT_WORKERS or 2)",
}
