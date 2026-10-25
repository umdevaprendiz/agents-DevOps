"""Brazilian Portuguese texts. Keys and {placeholders} must match en.py (checked by tests/test_i18n.py).
Literal braces are doubled: {{ and }}."""

MESSAGES = {
    # --- Texts sent to the model -------------------------------------------------------------
    "prompt.system": """Você é um agente autônomo de DevOps. Você ajuda com qualquer coisa de DevOps: containers, arquivos de infraestrutura e configuração, código da aplicação, logs, alertas de segurança e prevenção de falhas.

Como você trabalha:
1. Investigue antes de concluir. Quando não souber onde está o problema, comece por collect_diagnostics; para questões de segurança, comece por audit_security. Ferramentas de Docker: list_containers, inspect_container, get_container_logs, get_container_stats. Ferramentas do projeto: list_files, read_file, search_files, git_status, git_log, git_diff, audit_security.
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
    "prompt.analyst_system": """Você é a etapa de investigação de um agente autônomo de DevOps. Um modelo mais forte vai escrever o diagnóstico final e a correção usando só o seu relatório.

Como você trabalha:
1. Investigue com suas ferramentas de leitura: comece por collect_diagnostics (ou audit_security em questões de segurança), depois leia os logs, inspecione os containers e leia ou busque os arquivos do projeto envolvidos.
2. Baseie-se só no que as ferramentas retornaram. Não invente nomes, arquivos, linhas ou números.
3. Não corrija nada e não explique como corrigir: isso é trabalho da próxima etapa.
4. Valores mostrados como [REDACTED] foram ocultados de propósito. Nunca tente revelá-los.

Responda em português com este relatório, curto e factual:
## Sintomas
## Evidências (linhas exatas, cada uma com a origem: container ou arquivo:linha)
## Causa suspeita
## Arquivos envolvidos (caminhos que a correção provavelmente vai alterar)
## Dúvidas em aberto""",
    "prompt.analyze": "Investigue este pedido e escreva o seu relatório:\n\n{task}",
    "prompt.resolve": (
        "{task}\n\nUm modelo mais rápido já investigou e escreveu este relatório:\n\n{brief}\n\n"
        "Confira as evidências principais (leia um arquivo antes de alterá-lo), depois responda no formato "
        "pedido e proponha a correção. Se o relatório estiver errado ou incompleto, investigue o que falta."
    ),
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
    "prompt.audit": (
        "Rode audit_security{focus} e aja sobre o resultado. Explique os achados de severidade alta e média no "
        "formato pedido, dos mais graves para os menos graves, e diga quando a evidência mostrar um falso "
        "positivo. Para achados em arquivos do projeto, chame propose_change com a menor correção; para "
        "containers em execução ou o host, mostre o comando ou a configuração exata. Cite os achados de "
        "severidade baixa numa única linha de resumo."
    ),
    "prompt.audit_focus": ", depois foque em: {focus}",
    "prompt.explain": (
        "Explique esta mudança proposta ao operador em linguagem simples: o que muda, por que é necessária, "
        "os riscos e como testar. Seja breve.\n\nTítulo: {title}\nExplicação do autor: {explanation}\n\n"
        "Diff:\n{diff}"
    ),
    # --- Agent ------------------------------------------------------------------------------------
    "agent.thinking": "pensando ({model})...",
    "team.brief_title": "Investigação · {model}",
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
    # --- Security audit -----------------------------------------------------------------------------
    "sec.severity.high": "ALTA",
    "sec.severity.medium": "MÉDIA",
    "sec.severity.low": "BAIXA",
    "sec.report.header": "Auditoria de segurança: {high} alta(s), {medium} média(s), {low} baixa(s).",
    "sec.report.none": "Auditoria de segurança: nenhum problema encontrado.",
    "sec.report.fix": "Como corrigir: {fix}",
    "sec.col.severity": "Severidade",
    "sec.col.rule": "Regra",
    "sec.col.location": "Onde",
    "sec.col.problem": "Problema e correção",
    "sec.location.service": "{path} (serviço {service})",
    "sec.location.container": "container {name}",
    "sec.detail.auth": "{count} falhas de autenticação; principais origens: {sources}",
    "sec.detail.attacks": "{count} requisições suspeitas, ex.: {example}",
    "sec.detail.secrets": "{count} linhas, ex.: {example}",
    "sec.df001.title": "Imagem base sem versão fixa (latest ou sem tag)",
    "sec.df001.fix": "Fixe a imagem numa versão (ex.: node:20.11-alpine) ou num digest (@sha256:...) para builds reproduzíveis.",
    "sec.df002.title": "Container roda como root",
    "sec.df002.fix": "Crie um usuário sem privilégios e troque para ele com USER no estágio final (ex.: RUN useradd -r app, depois USER app).",
    "sec.df003.title": "Script remoto executado direto no shell (curl | sh)",
    "sec.df003.fix": "Baixe o script, verifique o checksum ou a assinatura e só então execute; ou instale um pacote com versão fixa.",
    "sec.df004.title": "Segredo gravado na imagem (ENV/ARG)",
    "sec.df004.fix": "Tire o valor do Dockerfile; passe-o na execução (variável de ambiente, gerenciador de segredos) ou use segredos do BuildKit (RUN --mount=type=secret).",
    "sec.df005.title": "Todo o contexto de build copiado sem .dockerignore",
    "sec.df005.fix": "Crie um .dockerignore excluindo .env*, .git, chaves e dados locais, ou copie só os arquivos que a imagem precisa.",
    "sec.df006.title": "Imagem final sem HEALTHCHECK",
    "sec.df006.fix": "Adicione um HEALTHCHECK (ex.: HEALTHCHECK CMD wget -qO- http://localhost:PORTA/health || exit 1) ou defina um no compose.",
    "sec.df007.title": "apt-get install sem --no-install-recommends",
    "sec.df007.fix": "Use apt-get install --no-install-recommends e apague /var/lib/apt/lists/* no mesmo RUN para a imagem ficar menor.",
    "sec.df008.title": "Permissões de escrita para todos (chmod 777)",
    "sec.df008.fix": "Dê só o necessário (ex.: chown app:app e chmod 750) em vez de 777.",
    "sec.dc001.title": "Container privilegiado",
    "sec.dc001.fix": "Remova privileged: true e adicione só as capabilities que o serviço precisa com cap_add.",
    "sec.dc002.title": "Socket do Docker montado num container (acesso root ao host)",
    "sec.dc002.fix": "Evite montar /var/run/docker.sock; se for mesmo necessário, use um proxy de socket que libere só os endpoints exigidos.",
    "sec.dc003.title": "Segredo escrito no arquivo do compose",
    "sec.dc003.fix": "Mova o valor para um .env ignorado pelo git ou para Docker secrets e referencie como ${{VARIAVEL}}.",
    "sec.dc004.title": "Porta de banco de dados publicada em todas as interfaces de rede",
    "sec.dc004.fix": "Não publique a porta, ou prenda-a ao localhost (\"127.0.0.1:5432:5432\") e acesse o banco pela rede interna.",
    "sec.dc005.title": "Imagem sem versão fixa (latest ou sem tag)",
    "sec.dc005.fix": "Fixe a versão da imagem (ex.: postgres:16.3) para que todo deploy rode o mesmo software.",
    "sec.dc006.title": "Serviço usa a rede do host",
    "sec.dc006.fix": "Remova network_mode: host e publique só as portas que o serviço precisa.",
    "sec.dc007.title": "Serviço publica portas mas não tem healthcheck",
    "sec.dc007.fix": "Adicione um healthcheck para o Docker saber quando o serviço está pronto de verdade e poder reiniciá-lo se travar.",
    "sec.dc008.title": "Sem limite de memória",
    "sec.dc008.fix": "Defina mem_limit (ou deploy.resources.limits.memory) para que um serviço não esgote a memória do host.",
    "sec.rc001.title": "Container rodando em modo privilegiado",
    "sec.rc001.fix": "Recrie-o sem --privileged, adicionando só as capabilities necessárias (--cap-add).",
    "sec.rc002.title": "Container em execução com o socket do Docker montado",
    "sec.rc002.fix": "Recrie-o sem -v /var/run/docker.sock, ou coloque um proxy de socket no meio.",
    "sec.rc003.title": "Banco de dados em execução acessível em todas as interfaces de rede",
    "sec.rc003.fix": "Recrie-o publicando a porta só em 127.0.0.1 (-p 127.0.0.1:5432:5432) ou sem publicá-la.",
    "sec.rc004.title": "Container em execução roda como root",
    "sec.rc004.fix": "Rode-o com um usuário sem privilégios (USER no Dockerfile, --user, ou user: no compose).",
    "sec.rc005.title": "Container em execução usa a rede do host",
    "sec.rc005.fix": "Recrie-o numa rede bridge e publique só as portas necessárias.",
    "sec.rc006.title": "Container em execução sem limite de memória",
    "sec.rc006.fix": "Defina um limite de memória (--memory ou mem_limit) para que ele não esgote o host.",
    "sec.lg001.title": "Possível ataque de força bruta (muitas falhas de autenticação)",
    "sec.lg001.fix": "Bloqueie ou limite as origens (fail2ban, firewall, WAF), exija senhas fortes ou chaves e verifique se algum login teve sucesso.",
    "sec.lg002.title": "Tentativas de ataque nos logs (path traversal, SQL injection, scanners)",
    "sec.lg002.fix": "Confirme que as requisições foram recusadas (4xx), mantenha o software atualizado e considere um WAF ou rate limiting.",
    "sec.lg003.title": "Segredo impresso nos logs",
    "sec.lg003.fix": "Pare de registrar o valor (mascare-o na aplicação), troque o segredo exposto e restrinja o acesso aos logs.",
    "sec.sc001.title": "Segredo fixo no código do repositório",
    "sec.sc001.fix": "Mova o valor para uma variável de ambiente ou um gerenciador de segredos, troque-o (ele está no histórico do git) e referencie como ${{VARIAVEL}}.",
    "sec.sc002.title": "Arquivo de segredos commitado no git",
    "sec.sc002.fix": "Remova-o do repositório (git rm --cached), adicione ao .gitignore, troque todos os segredos dele e limpe o histórico se o repositório for público.",
    "sec.sc003.title": "Arquivo de segredos não ignorado pelo git (pode ser commitado sem querer)",
    "sec.sc003.fix": "Adicione-o ao .gitignore (ex.: .env e .env.*, mantendo !.env.example).",
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
    "cmd.help.audit": "Auditoria de segurança e prevenção de falhas; o agente explica os achados e propõe correções",
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
    "cmd.status.fast_model": "Modelo de investigação",
    "cmd.status.single_model": "(nenhum: um modelo faz tudo)",
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
    "cli.help.fast_model": "modelo mais rápido para a etapa de investigação (padrão: AGENT_FAST_MODEL; vazio = um modelo faz tudo)",
    "cli.help.lang": "idioma: en ou pt-BR (padrão: AGENT_LANGUAGE ou o idioma do sistema)",
    "cli.help.chat": "conversa interativa com o agente (digite /ajuda dentro dela)",
    "cli.help.ask": "faz uma pergunta e sai",
    "cli.help.debug": "descobre o que está falhando, explica cada bug e propõe correções",
    "cli.help.focus": "foco opcional: um container, um arquivo ou um sintoma",
    "cli.review_in_chat": "Revise e decida no chat: devops-agent chat, depois /diff, /explain, /apply ou /pr.",
    "cli.help.audit": "auditoria de segurança e prevenção de falhas (não precisa do modelo; ótima para CI)",
    "cli.help.fail_on": "sai com código 1 quando houver achado com pelo menos esta severidade: high, medium, low ou never (padrão high)",
    "cli.help.json": "mostra os achados em JSON",
    "cli.help.no_docker": "ignora os containers em execução e seus logs",
    "cli.help.check": "verifica uma vez e investiga cada problema encontrado",
    "cli.help.watch": "monitora continuamente",
    "cli.help.only": "só estes containers (separados por vírgula)",
    "cli.help.scan_logs": "também procura linhas de erro nos logs",
    "cli.help.interval": "segundos entre verificações (padrão 30)",
    "cli.help.cooldown": "segundos antes de alertar de novo o mesmo container (padrão 600)",
    "cli.help.workers": "investigações em paralelo (padrão: AGENT_WORKERS ou 2)",
    "cli.help.eval": "dá nota aos modelos em cenários simulados com bugs conhecidos (não precisa de Docker)",
    "cli.help.scenario": "roda só este cenário (pode repetir; veja --list)",
    "cli.help.scenarios_dir": "pasta com seus próprios cenários (*.yml) no lugar dos que vêm com o agente",
    "cli.help.repeat": "execuções por cenário, para medir a consistência do modelo (padrão 1)",
    "cli.help.fail_under_rate": "sai com código 1 quando a taxa de acerto fica abaixo desta porcentagem",
    "cli.help.eval_json": "imprime os resultados em JSON",
    "cli.help.verbose": "mostra cada passo do agente",
    "cli.help.list": "lista os cenários e sai",
    "cli.help.validate": "confere os cenários com as soluções de referência (sem modelo)",
    # --- Avaliação --------------------------------------------------------------------------------
    "eval.invalid": "Cenários inválidos:",
    "agent.reply_cut": "A resposta do modelo foi cortada em {tokens} tokens (AGENT_NUM_PREDICT).",
    "eval.git_missing": "O git não está instalado: a avaliação precisa dele para aplicar as correções propostas.",
    "eval.validating": "Conferindo os cenários...",
    "eval.running": "[{index}/{total}] {scenario} · tentativa {attempt}/{repeat}",
    "eval.run_line": "{scenario} · {seconds}s · {tools} chamada(s) de ferramenta · {proposals} proposta(s)",
    "eval.run_error": "{scenario}: a execução falhou: {error}",
    "eval.failed_checks": "falhou em: {checks}",
    "eval.models_two": "{resolver} (analista: {analyst})",
    "eval.title": "Avaliação · {models} · {scenarios} cenário(s) × {repeat}",
    "eval.total": "Passou em {passed} execuções ({rate}%) · diagnóstico {diagnosis} · correção {fix} · {seconds}s por execução em média",
    "eval.below_threshold": "A taxa de acerto {rate}% está abaixo de --fail-under {threshold}%.",
    "eval.list_title": "Cenários",
    "eval.focus_everything": "(tudo)",
    "eval.col.scenario": "Cenário",
    "eval.col.title": "Descrição",
    "eval.col.focus": "Foco",
    "eval.col.checks": "Avaliado",
    "eval.col.passed": "Passou",
    "eval.col.diagnosis": "Diagnóstico",
    "eval.col.analyst": "Analista",
    "eval.col.fix": "Correção",
    "eval.col.no_changes": "Sem mudanças",
    "eval.col.tools": "Ferramentas",
    "eval.col.denied": "Negadas",
    "eval.col.time": "Tempo",
    "eval.col.reference": "Referência",
    "eval.col.baseline": "Sem fazer nada",
    "eval.col.result": "Resultado",
    "eval.validate_title": "Conferência dos cenários (soluções de referência, sem modelo)",
    "eval.validate_summary": "{ok}/{total} cenário(s) válido(s).",
    "eval.passes": "passa",
    "eval.fails": "falha",
    "eval.valid": "ok",
    "eval.reference_fails": "a solução de referência não passa: {reason}",
    "eval.too_weak": "passa mesmo quando o agente não faz nada: deixe o 'expect' mais rigoroso",
    "eval.reference_title": "Correção de referência",
    "eval.error.folder": "Pasta não encontrada: {folder}",
    "eval.error.no_scenarios": "Nenhum arquivo de cenário (*.yml) em {folder}",
    "eval.error.yaml": "{source}: YAML inválido: {error}",
    "eval.error.unknown_scenario": "Cenário(s) desconhecido(s): {ids}. Disponíveis: {available}",
    "eval.error.duplicate": "Id de cenário repetido: {id}",
    "eval.error.id": "{source}: id inválido {id!r} (use letras minúsculas, números e hífens)",
    "eval.error.type": "{source}: '{field}' deve ser do tipo {expected}",
    "eval.error.unknown_fields": "{source}: campo(s) desconhecido(s) em {where}: {fields}",
    "eval.error.missing": "{source}: falta '{field}'",
    "eval.error.path": "{source}: caminho de arquivo inseguro {path!r} (use caminhos relativos, sem '..' nem .git)",
    "eval.error.expectation": "{source}: 'expect' precisa de diagnosis e/ou fix, ou no_changes (fix não pode vir junto com no_changes)",
    "eval.error.regex": "{source}: expressão regular inválida {pattern!r}: {error}",
    "eval.error.container_mapping": "cada container precisa ser um mapeamento",
    "eval.error.container_fields": "campo(s) de container desconhecido(s): {fields}",
    "eval.error.container_name": "todo container precisa de um name",
    "eval.error.container_value": "{name}: '{field}' deve ser um destes: {values}",
}
