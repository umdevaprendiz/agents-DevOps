"""Brazilian Portuguese texts. Keys and {placeholders} must match en.py (checked by tests/test_i18n.py).
Literal braces are doubled: {{ and }}."""

MESSAGES = {
    # --- Texts sent to the model -------------------------------------------------------------
    "prompt.system": """Você é um agente autônomo de DevOps. Você ajuda com qualquer coisa de DevOps: containers, arquivos de infraestrutura e configuração, código da aplicação, logs, alertas de segurança e prevenção de falhas.

Como você trabalha:
1. Investigue antes de concluir. Quando não souber onde está o problema, comece por collect_diagnostics. Ferramentas de Docker: list_containers, inspect_container, get_container_logs, get_container_stats. Ferramentas do projeto: list_files, read_file, search_files, git_status, git_log, git_diff.
2. Baseie-se só no que as ferramentas retornaram. Não invente nomes, arquivos, variáveis, logs ou números.
3. Para alterar arquivos, chame propose_change com a menor edição que resolve o problema. Mude só o necessário: nada de refatorações ou mudanças de estilo, e nunca segredos (use referências como ${{VARIAVEL}}). A proposta vai para uma branch própria no git; o operador revisa e decide.
4. Só proponha restart/start/stop quando isso puder resolver; essas ações pedem aprovação humana. Se uma for negada, não repita; sugira alternativas.
5. Valores mostrados como [REDACTED] foram ocultados de propósito para proteger segredos. Nunca tente revelá-los.
6. Seja direto e breve. Antes de uma investigação longa, diga em uma frase o que vai verificar. Só faça perguntas ao operador quando não puder continuar sem a resposta.
7. Relate os resultados com honestidade, inclusive o que falhou ou o que você não conseguiu verificar.

Referência de exit codes: 0 = terminou normalmente; 1 = erro da aplicação; 2 = erro de uso/configuração; 125-127 = erro do Docker ou comando não encontrado; 137 = morto com SIGKILL (geralmente falta de memória, confira oom_killed); 139 = segfault; 143 = parado com SIGTERM.

Ao relatar problemas, responda em português, com um bloco por problema:
**Problema:** o que está quebrado (container, arquivo ou serviço)
**Erro:** a mensagem de erro exata ou a evidência (linha de log, exit code, linha de configuração)
**Causa:** por que acontece
**Como resolver:** passos concretos, comandos ou configurações a usar
**Mudança proposta:** o id da proposta, se você criou uma com propose_change
Para outros pedidos, responda em português, de forma natural e concisa.""",
    "prompt.step_limit": "Limite de passos atingido. Responda agora com o que já descobriu, no formato pedido.",
    "prompt.evidence": (
        "Você respondeu sem usar nenhuma ferramenta. Não invente dados: chame inspect_container "
        "e get_container_logs do container antes de concluir."
    ),
    "prompt.action_denied": "Ação NEGADA pelo operador. Não tente executá-la de novo; explique o que ele pode fazer.",
    "prompt.unknown_tool": "Erro: a ferramenta '{name}' não existe. Disponíveis: {available}.",
    "prompt.suggest": (
        "Revise este projeto{focus} e proponha só as mudanças realmente necessárias: bugs, riscos de "
        "segurança, configuração errada ou coisas com chance de falhar. Investigue primeiro (list_files, "
        "read_file, search_files e as ferramentas de Docker) e depois chame propose_change uma vez para cada "
        "correção independente, com a menor edição possível. Se nada precisar mudar, diga isso e não proponha nada."
    ),
    "prompt.suggest_focus": ", com foco em: {focus}",
    "prompt.debug": (
        "Depure {target}. Descubra o que está falhando e como resolver. Comece por collect_diagnostics e "
        "depois investigue cada problema a fundo: logs e inspect dos containers e os arquivos do projeto "
        "relacionados (Dockerfile, compose, configuração, código). Explique cada problema no formato pedido, "
        "com os comandos ou configurações exatos a usar. Quando uma mudança em arquivo resolver um problema, "
        "chame propose_change com a menor edição. Não proponha mudanças desnecessárias."
    ),
    "prompt.debug_everything": "o ambiente inteiro (containers e projeto)",
    "prompt.explain": (
        "Explique esta mudança proposta ao operador em linguagem simples: o que muda, por que é necessária, "
        "os riscos e como testar. Seja breve.\n\nTítulo: {title}\nExplicação do autor: {explanation}\n\n"
        "Diff:\n{diff}"
    ),
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
    # --- Workspace and git ----------------------------------------------------------------------------
    "workspace.outside": "caminho fora do workspace: {path}",
    "workspace.secret": "acesso negado a um arquivo de segredos: {path}",
    "workspace.not_found": "arquivo não encontrado: {path}",
    "workspace.too_big": "arquivo grande demais para ler (limite de {size} KB): {path}",
    "workspace.binary": "arquivo binário, não pode ser lido como texto: {path}",
    "workspace.file_header": "{path} (linhas {first}-{last} de {total})",
    "workspace.no_files": "(nenhum arquivo)",
    "workspace.more": "...e mais {count}",
    "workspace.no_matches": "(nenhum resultado)",
    "workspace.no_changes": "(nenhuma alteração sem commit)",
    "diag.docker_unavailable": "Containers: Docker indisponível ({error}).",
    "diag.containers_ok": "Containers: nenhum problema detectado.",
    "diag.containers_title": "Containers com problema:",
    "diag.logs_title": "Arquivos de log do projeto com erros:",
    "diag.logs_ok": "Arquivos de log do projeto: nenhum erro encontrado.",
    "diag.log_file": "- {path} ({count} linhas de erro, as mais recentes:)",
    "diag.infra_title": "Arquivos de infraestrutura:",
    "diag.infra_none": "Arquivos de infraestrutura: nenhum encontrado.",
    "git.cli_missing": "git não encontrado no PATH.",
    "git.timeout": "'git {command}' excedeu {seconds}s.",
    "git.exit_code": "'git {command}' saiu com código {code}",
    # --- Proposals ------------------------------------------------------------------------------------
    "proposal.not_repo": "o workspace não é um repositório git (rode 'git init' e faça um primeiro commit).",
    "proposal.bad_edits": "edits deve ser uma lista de objetos {{path, old_text, new_text}}.",
    "proposal.no_edits": "a proposta não tem nenhuma edição.",
    "proposal.file_exists": "{path} já existe; para alterá-lo, coloque em old_text o texto exato a substituir.",
    "proposal.file_missing": "{path} não existe no último commit; para criá-lo, use old_text=''.",
    "proposal.not_found": (
        "old_text não foi encontrado em {path}. Leia o arquivo de novo e copie o texto exatamente, "
        "sem o prefixo com o número da linha."
    ),
    "proposal.ambiguous": "old_text aparece {count} vezes em {path}; inclua mais linhas ao redor para que seja único.",
    "proposal.redacted_old": "old_text contém [REDACTED]: essa linha guarda um segredo e o agente não pode editá-la ({path}).",
    "proposal.secret_new": "new_text parece conter um segredo; use uma referência como ${{VARIAVEL}} ({path}).",
    "proposal.created": (
        "Proposta {id} criada na branch {branch}. O operador pode revisá-la com /diff {id} "
        "e decidir com /apply {id} ou /pr {id}."
    ),
    "proposal.none": "Nenhuma proposta pendente.",
    "proposal.unknown": "Nenhuma proposta pendente corresponde a '{ref}'.",
    "proposal.nothing_to_undo": "Nenhuma proposta aplicada para desfazer.",
    "proposal.already_undone": "A última proposta aplicada ({commit}) já foi desfeita.",
    "proposal.no_remote": "Este repositório não tem o remoto 'origin' para abrir um pull request.",
    "proposal.pushed_no_gh": (
        "Branch {branch} enviada. Instale o GitHub CLI (gh) para abrir o PR automaticamente, "
        "ou abra no GitHub da {branch} para a {base}."
    ),
    # --- Chat commands --------------------------------------------------------------------------------
    "cmd.unknown": "Comando desconhecido: {name}. Digite /help para ver os comandos.",
    "cmd.failed": "Não foi possível concluir o comando:",
    "cmd.help_title": "Comandos",
    "cmd.col.command": "Comando",
    "cmd.col.aliases": "Apelidos",
    "cmd.col.description": "Descrição",
    "cmd.col.id": "ID",
    "cmd.col.title": "Título",
    "cmd.col.branch": "Branch",
    "cmd.help.help": "Mostra esta lista",
    "cmd.help.debug": "Descobre o que está falhando (containers, logs, projeto), explica cada bug e propõe correções",
    "cmd.help.suggest": "O agente revisa o projeto e propõe só as mudanças necessárias",
    "cmd.help.proposals": "Lista as propostas pendentes",
    "cmd.help.diff": "Mostra as alterações de uma proposta (padrão: a mais recente)",
    "cmd.help.explain": "Explica uma proposta em linguagem simples",
    "cmd.help.apply": "Junta uma proposta na sua branch atual",
    "cmd.help.pr": "Envia uma proposta e abre um pull request",
    "cmd.help.discard": "Apaga uma proposta",
    "cmd.help.undo": "Reverte a última proposta aplicada (com um novo commit)",
    "cmd.help.status": "Modelo, idioma, workspace, branch e propostas",
    "cmd.help.clear": "Limpa a conversa",
    "cmd.help.exit": "Sai",
    "cmd.proposals_title": "Propostas pendentes",
    "cmd.proposal_ready": "[bold cyan]Proposta {id}[/]: {title} → /diff {id} · /explain {id} · /apply {id} · /pr {id}",
    "cmd.no_new_proposals": "nenhuma mudança proposta",
    "cmd.confirm_apply": "Juntar a proposta {id} na branch {branch}?",
    "cmd.applied": "Proposta {id} aplicada em {branch}. Desfaça com /undo.",
    "cmd.confirm_discard": "Apagar a proposta {id}?",
    "cmd.discarded": "Proposta {id} apagada.",
    "cmd.confirm_undo": "Reverter a última proposta aplicada com um novo commit?",
    "cmd.undone": "Proposta revertida (merge {commit}).",
    "cmd.confirm_pr": "Enviar a branch {branch} para o origin e abrir um pull request?",
    "cmd.status_title": "Status",
    "cmd.status.model": "Modelo",
    "cmd.status.language": "Idioma",
    "cmd.status.workspace": "Workspace",
    "cmd.status.branch": "Branch",
    "cmd.status.proposals": "Propostas pendentes",
    "cmd.not_a_repo": "(não é um repositório git)",
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
        "Investigue a causa (logs, inspect, stats e os arquivos do projeto relacionados) e explique no "
        "formato pedido. Se uma mudança em arquivo resolver, proponha-a com propose_change; se uma ação "
        "resolver, proponha a ação."
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
    "ui.empty_diff": "(diff vazio)",
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
    "cli.workspace_ok": "Workspace {path} (branch {branch})",
    "cli.workspace_no_git": "Workspace {path} (não é um repositório git: propostas de mudança desativadas)",
    "cli.workspace_missing": "✗ Workspace não encontrado:",
    "cli.workspace_hint": "Defina AGENT_WORKSPACE com uma pasta existente.",
    "cli.chat_intro": "Converse com o agente. Digite [bold]/ajuda[/] para ver os comandos e [bold]/sair[/] para encerrar.\n",
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
    "cli.help.description": "Agente autônomo de DevOps com LLM local (Ollama).",
    "cli.help.model": "modelo do Ollama (padrão: AGENT_MODEL ou qwen3:4b)",
    "cli.help.lang": "idioma: en ou pt-BR (padrão: AGENT_LANGUAGE ou o idioma do sistema)",
    "cli.help.chat": "conversa interativa com o agente (digite /ajuda dentro dela)",
    "cli.help.ask": "faz uma pergunta e sai",
    "cli.help.debug": "descobre o que está falhando, explica cada bug e propõe correções",
    "cli.help.focus": "foco opcional: um container, um arquivo ou um sintoma",
    "cli.review_in_chat": "Revise e decida no chat: devops-agent chat, depois /diff, /explain, /apply ou /pr.",
    "cli.help.check": "verifica uma vez e investiga cada problema encontrado",
    "cli.help.watch": "monitora continuamente",
    "cli.help.only": "só estes containers (separados por vírgula)",
    "cli.help.scan_logs": "também procura linhas de erro nos logs",
    "cli.help.interval": "segundos entre verificações (padrão 30)",
    "cli.help.cooldown": "segundos antes de alertar de novo o mesmo container (padrão 600)",
    "cli.help.workers": "investigações em paralelo (padrão: AGENT_WORKERS ou 2)",
}
