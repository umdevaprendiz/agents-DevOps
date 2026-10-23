# Agente DevOps (Ollama + Docker)

Agente que monitora seus containers Docker, investiga problemas sozinho (logs, exit code, healthcheck, memória) e propõe correções. Roda **100% local** com Ollama, então nenhum log sai da sua máquina.

Ele **lê e diagnostica sozinho**, mas **pede sua aprovação** antes de qualquer ação que altere algo (restart, start, stop).

## Como funciona

```
 monitor (regras simples, sem IA)          agente (modelo no Ollama)
 ────────────────────────────────          ─────────────────────────
 a cada N segundos olha os containers  ─▶  recebe "container X caiu com exit 1"
 detecta: exit != 0, restart em loop,      escolhe ferramentas: inspect, logs, stats
 unhealthy, OOMKilled, erros no log        lê os resultados, repete até entender
                                           propõe ação ─▶ você aprova (s/n)
                                           responde: Diagnóstico / Causa / Ação
```

O monitor não usa IA, então fica leve. O modelo só é chamado quando algo quebra.

## Instalação

```powershell
ollama pull qwen3:4b
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Uso

```powershell
# Conversa livre ("por que o container api caiu?", "quanto de memória o web usa?")
.\.venv\Scripts\python -m devops_agent chat

# Pergunta única
.\.venv\Scripts\python -m devops_agent ask "tem algum container com problema?"

# Verifica uma vez e diagnostica o que estiver quebrado
.\.venv\Scripts\python -m devops_agent check

# Monitora continuamente
.\.venv\Scripts\python -m devops_agent watch --interval 30 --scan-logs
```

Opções úteis:

| Opção | O que faz |
|---|---|
| `--model qwen3:8b` | Troca o modelo (vem antes do comando: `python -m devops_agent --model qwen3:8b chat`) |
| `--only api,worker` | Monitora só esses containers |
| `--scan-logs` | Também alerta quando aparecem várias linhas `ERROR`/`FATAL`/`panic` nos logs |
| `--cooldown 600` | Segundos até alertar de novo o mesmo container |

Variáveis de ambiente: `AGENT_MODEL`, `OLLAMA_HOST`, `AGENT_MAX_STEPS` (padrão 12), `AGENT_NUM_CTX` (padrão 8192), `AGENT_MAX_TOOL_OUTPUT` (padrão 4000 caracteres), `AGENT_AUDIT_FILE`.

## Testar com containers quebrados de propósito

```powershell
docker compose -f demo/docker-compose.yml up -d
.\.venv\Scripts\python -m devops_agent check
docker compose -f demo/docker-compose.yml down
```

| Container | Defeito | O que o agente deve concluir |
|---|---|---|
| `demo-web` | nenhum | não alerta |
| `demo-web-unhealthy` | healthcheck na porta errada | o problema está no healthcheck, não no nginx |
| `demo-api` | banco de dados não existe | reiniciar não resolve, falta o Postgres |
| `demo-worker` | falta a variável `QUEUE_URL` | loop de reinício; precisa configurar a variável |

## Segurança

- O modelo **não tem shell**. Ele só chama as funções de `devops_agent/tools.py`, que executam `docker` com argumentos fixos (sem shell) e nomes de container validados.
- Ações que alteram algo têm `needs_approval=True` e sempre pedem confirmação.
- O agente vê **só os nomes** das variáveis de ambiente, nunca os valores, que podem ser segredos.
- Todo evento (tarefa, ferramenta usada, aprovação, resposta) vai para `logs/audit.jsonl`.

## Estrutura

```
devops_agent/
  __main__.py      CLI (chat, ask, check, watch) e prompt de aprovação
  agent.py         loop modelo → ferramenta → resultado
  tools.py         ferramentas disponíveis para o modelo
  docker_tools.py  chamadas ao Docker
  monitor.py       detecção de problemas por regras
  audit.py         log de auditoria
  config.py        configurações
demo/              containers com defeitos para teste
```

## Sobre o modelo

Sem placa de vídeo dedicada, o modelo roda na CPU. O `qwen3:4b` é um bom equilíbrio entre velocidade e acerto ao chamar ferramentas. O `qwen3:8b` acerta mais, mas é cerca de 2x mais lento. Modelos de 1–3B (como `llama3.2:3b`) erram com frequência ao escolher ferramentas.

## Próximos passos possíveis

- Novas ferramentas: `docker compose`, uso de disco (`docker system df`), limpeza de imagens antigas (com aprovação).
- Alertas no Telegram/Discord com aprovação por botão.
- Kubernetes (`kubectl`) e análise de falhas de CI/CD.
- Memória de incidentes (usando o `bge-m3` que você já tem) para lembrar como problemas parecidos foram resolvidos.
