from __future__ import annotations

import pytest

from skill_mcp import server


@pytest.fixture(autouse=True)
def reset_server_scope():
    """The directory the server names in its error messages is a module global.

    It is set once by ``run_server`` because the process serves one directory for
    its whole life. Under pytest that lifetime is the whole session, so a test
    that configures it leaves the next one asserting against a directory that
    belonged to an already-deleted ``tmp_path`` — and the assertion still passes,
    for the wrong reason.
    """
    server._scope = ""
    yield
    server._scope = ""
