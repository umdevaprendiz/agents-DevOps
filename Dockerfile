FROM python:3.12-slim

# Docker CLI only (no daemon): the agent talks to the daemon through DOCKER_HOST or a mounted socket.
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
COPY pyproject.toml README.md ./
COPY devops_agent ./devops_agent
RUN pip install --no-cache-dir .

# Never run as root inside the container.
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /data \
    && chown agent /data
USER agent
WORKDIR /data

ENV AGENT_AUDIT_FILE=/data/audit.jsonl \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]

ENTRYPOINT ["devops-agent"]
CMD ["watch"]
