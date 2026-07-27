"""Built-in agent skills.

A "skill" is a system prompt + tool allowlist. The default rail agent
is what dispatches when the user types plain chat (no prefix) into
the rail. More skills (ingest, project-curator, allowlist-helper,
…) get added as their tabs/flows land.
"""

from . import rail_default

__all__ = ["rail_default"]
