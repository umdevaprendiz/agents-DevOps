"""Brazilian Portuguese texts. Keys and {placeholders} must match en.py (checked by tests/test_i18n.py)."""

MESSAGES = {
    # --- Texts sent to the model -------------------------------------------------------------
    "prompt.system": """Você é um agente de DevOps que cuida dos containers Docker deste host.

Regras:
1. Investigue antes de concluir. Use as ferramentas list_containers, inspect_container, get_container_logs e get_container_stats.
2. Baseie-se só no que as ferramentas retornaram. Não invente nomes de containers, variáveis, logs ou números.
3. Só proponha restart/start/stop quando isso puder resolver. Se a causa for configuração errada, variável de ambiente faltando, bug no código ou dependência fora do ar, reiniciar não resolve: explique o que o operador precisa corrigir.
4. Ações que alteram containers pedem aprovação humana. Se for negada, não repita; sugira alternativas.
5. Valores mostrados como [REDACTED] foram ocultados de propósito para proteger segredos. Nunca tente revelá-los.
6. Seja breve.

Referência de exit codes: 0 = terminou normalmente; 1 = erro da aplicação; 2 = erro de uso/configuração; 125-127 = erro do Docker ou comando não encontrado; 137 = morto com SIGKILL (geralmente falta de memória, confira oom_killed); 139 = segfault; 143 = parado com SIGTERM.

Quando terminar, responda em português neste formato:
**Diagnóstico:** o que está acontecendo
**Causa provável:** por quê, citando a evidência (linha de log, exit code...)
**Ação:** o que você fez ou o que recomenda fazer""",
    "prompt.step_limit": "Limite de passos atingido. Responda agora com o que já descobriu, no formato pedido.",
    "prompt.evidence": (
        "Você respondeu sem usar nenhuma ferramenta. Não invente dados: chame inspect_container "
        "e get_container_logs do container antes de concluir."
    ),
    "prompt.action_denied": "Ação NEGADA pelo operador. Não tente executá-la de novo; explique o que ele pode fazer.",
    "prompt.unknown_tool": "Erro: a ferramenta '{name}' não existe. Disponíveis: {available}.",
    # --- Agent ------------------------------------------------------------------------------------
    "agent.thinking": "pensando...",
    "agent.unknown_tool": "✗ ferramenta desconhecida: {name}",
    "agent.denied": "ação negada",
    "agent.evidence_rejected": "resposta sem evidências recusada; pedindo investigação",
    "agent.tool_error": "Erro: {error}",
    "text.truncated_start": "...(início cortado)",
    "text.truncated_end": "...(final cortado)",
    "tools.missing_params": "faltam parâmetros: {names}",
    # --- Docker -------------------------------------------------------------------------------------
    "docker.cli_missing": "Docker CLI não encontrado no PATH.",
    "docker.timeout": "'docker {command}' excedeu {seconds}s.",
    "docker.exit_code": "'docker {command}' saiu com código {code}",
    "docker.invalid_name": "nome de container inválido: {value}",
    "docker.invalid_since": "valor inválido para since: {value}",
    "docker.no_logs": "(sem logs)",
    "docker.restarted": "Container '{container}' reiniciado.",
    "docker.started": "Container '{container}' iniciado.",
    "docker.stopped": "Container '{container}' parado.",
    # --- Monitor ------------------------------------------------------------------------------------
    "monitor.oom": " (OOMKilled: morto por falta de memória)",
    "monitor.restarting": "em loop de reinício ({count} reinícios, último exit code {exit_code}){oom}",
    "monitor.dead": "está no estado 'dead'",
    "monitor.exited": "parou com exit code {exit_code}{oom}",
    "monitor.unhealthy": "healthcheck falhando ({streak} falhas seguidas)",
    "monitor.restarted": "reiniciou {count}x desde a última verificação{oom}",
    "monitor.probable_loop": "já reiniciou {count}x e subiu há poucos minutos (possível loop){oom}",
    "monitor.log_errors": "{count} linhas de erro nos logs nos últimos {window}s, ex.: {example}",
    "monitor.task": (
        "O monitor detectou um problema no container '{container}': {detail}. "
        "Investigue a causa (inspect, logs, stats) e, se uma ação puder resolver, proponha-a."
    ),
    # --- Terminal -----------------------------------------------------------------------------------
    "ui.yes": "s",
    "ui.no": "n",
    "ui.invalid_yes_no": "[prompt.invalid]Digite {yes} ou {no}",
    "ui.approval_request": "O agente quer executar [bold]{tool}[/] no container [bold]{container}[/].",
    "ui.approval_title": "Aprovação necessária",
    "ui.allow": "Permitir?",
    "ui.no_answer": "_(o modelo não respondeu)_",
    "ui.answer_title": "Agente",
    # --- Command line ---------------------------------------------------------------------------------
    "cli.docker_ok": "Docker {version}",
    "cli.docker_down": "✗ Docker indisponível:",
    "cli.docker_hint": "Inicie o Docker e tente de novo.",
    "cli.ollama_ok": "Ollama com o modelo {model}",
    "cli.model_missing": "✗ Modelo '{model}' não encontrado.",
    "cli.model_hint": "Rode: [bold]ollama pull {model}[/]",
    "cli.ollama_down": "✗ Ollama não respondeu:",
    "cli.ollama_hint": "Inicie o Ollama e tente de novo.",
    "cli.ollama_error": "Erro do Ollama:",
    "cli.ollama_unreachable": "Não consegui falar com o Ollama:",
    "cli.chat_intro": "Converse com o agente. [bold]/limpar[/] zera a conversa, [bold]/sair[/] encerra.\n",
    "cli.prompt": "você>",
    "cli.chat_reset": "conversa zerada",
    "cli.interrupted": "interrompido",
    "cli.no_problems": "Nenhum problema encontrado.",
    "cli.problems_found": "{count} container(s) com problema.",
    "cli.issue_header": "Problema em {container}",
    "cli.watching": "Monitorando a cada {interval}s com {workers} worker(s). [bold]Ctrl+C[/] para parar.\n",
    "cli.heartbeat": "{time} · {new} problema(s) novo(s) · {running} investigação(ões) em andamento",
    "cli.docker_query_error": "Erro ao consultar o Docker:",
    "cli.investigation_failed": "A investigação de {container} falhou:",
    "cli.stopped": "encerrado",
    "cli.help.description": "Agente autônomo de DevOps para Docker, com LLM local (Ollama).",
    "cli.help.model": "modelo do Ollama (padrão: AGENT_MODEL ou qwen3:4b)",
    "cli.help.lang": "idioma: en ou pt-BR (padrão: AGENT_LANGUAGE ou o idioma do sistema)",
    "cli.help.chat": "conversa interativa com o agente",
    "cli.help.ask": "faz uma pergunta e sai",
    "cli.help.check": "verifica uma vez e investiga cada problema encontrado",
    "cli.help.watch": "monitora continuamente",
    "cli.help.only": "só estes containers (separados por vírgula)",
    "cli.help.scan_logs": "também procura linhas de erro nos logs",
    "cli.help.interval": "segundos entre verificações (padrão 30)",
    "cli.help.cooldown": "segundos antes de alertar de novo o mesmo container (padrão 600)",
    "cli.help.workers": "investigações em paralelo (padrão: AGENT_WORKERS ou 2)",
}
