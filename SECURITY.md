# Security Policy

🇧🇷 [Versão em português abaixo](#política-de-segurança)

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private reporting instead:
**Security** tab → **Report a vulnerability**.

Please include the affected version or commit, steps to reproduce and the impact you expect.

## What the agent protects

| Risk | Protection |
|---|---|
| The model running arbitrary commands | There is no shell tool. Docker runs with fixed argument lists (`shell=False`) and validated container names. |
| The model breaking something | Every state-changing tool requires human approval. The default answer is **no**, and no answer (Enter, Ctrl+C, EOF) means no. |
| Secrets in container logs | Tool outputs and audit records go through `devops_agent/redaction.py` before reaching the model, the terminal or the disk. |
| Secrets in the container config | `docker inspect` is summarized with environment variable **names only**, never values. |
| Secrets in the repository | `.env` is git-ignored, `.env.example` holds only variable names, gitleaks runs on every commit (pre-commit) and on every push (CI). |
| The model reading project secrets | File access is confined to `AGENT_WORKSPACE`; `.env*` (except `.env.example`), private keys, `.netrc`, `.npmrc`, `.pypirc` and `.git/` are never read, listed, searched or diffed. |
| The model writing secrets or changing code without consent | Changes are only *proposed*, as commits on separate `agent/...` branches. New text that looks like a secret is refused. Only `/apply` (after confirmation) merges, `/undo` reverts, and `/pr` (after confirmation) is the only way anything is pushed. |

## Your responsibilities as an operator

- Keep real values only in `.env` or in your secret manager. Never commit them.
- Mounting `/var/run/docker.sock` gives the agent root-equivalent access to the host. Prefer a remote `DOCKER_HOST` with TLS, or a socket proxy that only allows the endpoints the agent uses.
- If `OLLAMA_HOST` points to another machine, (redacted) logs travel to it. Use a trusted network.
- `logs/audit.jsonl` contains redacted container output. Protect it like any other log.

Redaction is a safety net, not a guarantee: it recognizes common formats (PEM keys, tokens from AWS, GitHub, GitLab, Slack, Google, OpenAI-style keys, Telegram, JWTs, `user:password@host` URLs and `password=`/`token=`/`api_key=` style assignments). Custom formats may get through.

---

# Política de segurança

## Como reportar uma vulnerabilidade

**Não abra uma issue pública.** Use o reporte privado do GitHub:
aba **Security** → **Report a vulnerability**.

Inclua a versão ou commit afetado, os passos para reproduzir e o impacto esperado.

## O que o agente protege

| Risco | Proteção |
|---|---|
| O modelo executar comandos arbitrários | Não existe ferramenta de shell. O Docker roda com lista fixa de argumentos (`shell=False`) e nomes de container validados. |
| O modelo quebrar algo | Toda ferramenta que altera estado exige aprovação humana. A resposta padrão é **não**, e a falta de resposta (Enter, Ctrl+C, EOF) também. |
| Segredos nos logs dos containers | Saídas de ferramentas e registros de auditoria passam por `devops_agent/redaction.py` antes de chegar ao modelo, ao terminal ou ao disco. |
| Segredos na configuração do container | O `docker inspect` é resumido apenas com os **nomes** das variáveis de ambiente, nunca os valores. |
| Segredos no repositório | `.env` está no `.gitignore`, o `.env.example` tem só os nomes das variáveis e o gitleaks roda em todo commit (pre-commit) e em todo push (CI). |
| O modelo ler segredos do projeto | O acesso a arquivos fica restrito ao `AGENT_WORKSPACE`; `.env*` (exceto `.env.example`), chaves privadas, `.netrc`, `.npmrc`, `.pypirc` e `.git/` nunca são lidos, listados, buscados ou incluídos em diffs. |
| O modelo escrever segredos ou mudar o código sem permissão | As mudanças são só *propostas*, como commits em branches separadas `agent/...`. Texto novo que pareça segredo é recusado. Só o `/apply` (após confirmação) faz o merge, o `/undo` reverte, e só o `/pr` (após confirmação) envia algo para fora. |

## Responsabilidades de quem opera

- Mantenha valores reais apenas no `.env` ou no seu gerenciador de segredos. Nunca faça commit deles.
- Montar `/var/run/docker.sock` dá ao agente acesso equivalente a root no host. Prefira um `DOCKER_HOST` remoto com TLS, ou um proxy de socket que libere só os endpoints que o agente usa.
- Se `OLLAMA_HOST` apontar para outra máquina, os logs (já redigidos) trafegam até ela. Use uma rede confiável.
- `logs/audit.jsonl` contém saídas de containers redigidas. Proteja-o como qualquer outro log.

A redação é uma rede de proteção, não uma garantia: ela reconhece formatos comuns (chaves PEM, tokens da AWS, GitHub, GitLab, Slack, Google, chaves no estilo OpenAI, Telegram, JWTs, URLs `usuario:senha@host` e atribuições como `password=`, `token=` e `api_key=`). Formatos próprios podem passar.
