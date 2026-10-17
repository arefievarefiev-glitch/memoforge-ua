"""Test support: the endpoint hosts of the servers this fork no longer bundles.

The scrubbing of an MCP endpoint address (`sources.public_url`, `sources.scrub_urls`, the docx annex)
is generic, but its tests need a host that is non-public and that `.mcp.json` maps to a labelled
server. This fork bundles only Legal Data Hunter, whose host is public, so the tests read the mapping
the first releases shipped. The mapping is installed per test module and removed afterwards.
"""

from __future__ import annotations

from unittest import mock

from memoforge import routing

LEGACY_HOSTS: dict[str, str] = {
    "mcp.casus.legal": "casus",
    "legaldatahunter.com": "legal-data-hunter",
}

_PATCHES: list = []


def install() -> None:
    patcher = mock.patch.object(routing, "manifest_hosts", lambda: dict(LEGACY_HOSTS))
    patcher.start()
    _PATCHES.append(patcher)


def uninstall() -> None:
    while _PATCHES:
        _PATCHES.pop().stop()
