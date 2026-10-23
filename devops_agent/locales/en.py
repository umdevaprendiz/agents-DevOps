"""English texts. Keys and {placeholders} must match pt_br.py (checked by tests/test_i18n.py)."""

MESSAGES = {
    # --- Texts sent to the model -------------------------------------------------------------
    "prompt.system": """You are a DevOps agent that takes care of the Docker containers on this host.

Rules:
1. Investigate before concluding. Use the tools list_containers, inspect_container, get_container_logs and get_container_stats.
2. Rely only on what the tools returned. Never invent container names, variables, logs or numbers.
3. Only propose restart/start/stop when it can actually fix the problem. If the cause is a wrong configuration, a missing environment variable, a bug in the code or a dependency that is down, restarting will not help: explain what the operator needs to fix.
4. Actions that change containers need human approval. If one is denied, do not repeat it; suggest alternatives.
5. Values shown as [REDACTED] were hidden on purpose to protect secrets. Never try to reveal them.
6. Be brief.

Exit code reference: 0 = finished normally; 1 = application error; 2 = usage/configuration error; 125-127 = Docker error or command not found; 137 = killed with SIGKILL (usually out of memory, check oom_killed); 139 = segfault; 143 = stopped with SIGTERM.

When you are done, answer in English using this format:
**Diagnosis:** what is happening
**Probable cause:** why, quoting the evidence (log line, exit code...)
**Action:** what you did or what you recommend""",
    "prompt.step_limit": "Step limit reached. Answer now with what you found so far, in the requested format.",
    "prompt.evidence": (
        "You answered without using any tool. Do not invent data: call inspect_container "
        "and get_container_logs for the container before concluding."
    ),
    "prompt.action_denied": "Action DENIED by the operator. Do not try it again; explain what they can do instead.",
    "prompt.unknown_tool": "Error: the tool '{name}' does not exist. Available: {available}.",
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
        "Investigate the cause (inspect, logs, stats) and, if an action can fix it, propose it."
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
    "cli.chat_intro": "Chat with the agent. [bold]/clear[/] resets the conversation, [bold]/exit[/] quits.\n",
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
    "cli.help.description": "Autonomous DevOps agent for Docker, powered by a local LLM (Ollama).",
    "cli.help.model": "Ollama model (default: AGENT_MODEL or qwen3:4b)",
    "cli.help.lang": "language: en or pt-BR (default: AGENT_LANGUAGE or the system language)",
    "cli.help.chat": "interactive chat with the agent",
    "cli.help.ask": "ask one question and exit",
    "cli.help.check": "scan once and investigate every problem found",
    "cli.help.watch": "watch continuously",
    "cli.help.only": "only these containers (comma separated)",
    "cli.help.scan_logs": "also look for error lines in the logs",
    "cli.help.interval": "seconds between scans (default 30)",
    "cli.help.cooldown": "seconds before alerting about the same container again (default 600)",
    "cli.help.workers": "parallel investigations (default: AGENT_WORKERS or 2)",
}
