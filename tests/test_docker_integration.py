"""Testes contra o Docker real (só leitura). Pulados se o Docker não estiver rodando."""
import pytest

from devops_agent import docker_tools as dk


def _docker_running() -> bool:
    try:
        dk.server_version()
        return True
    except dk.DockerError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _docker_running(), reason="Docker não está rodando"),
]


def test_list_containers_returns_expected_fields():
    for container in dk.list_containers():
        assert set(container) == {"name", "image", "state", "status"}


def test_inspect_unknown_container_raises():
    with pytest.raises(dk.DockerError):
        dk.inspect_container("container-que-nao-existe-123")


def test_inspect_matches_listed_container():
    containers = dk.list_containers()
    if not containers:
        pytest.skip("nenhum container para inspecionar")
    name = containers[0]["name"]
    assert dk.inspect_container(name)["name"] == name
