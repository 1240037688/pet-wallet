"""Approval observation hooks (agent half) — IMPLEMENTED IN M8.

M0 placeholder. Design (IMPLEMENTATION_PLAN M8 task 3):

* register ``pre_approval_request`` / ``post_approval_response`` as
  observer-only hooks (no answering, no mutation of the approval flow);
* filter kwargs to ``surface == 'gateway'``;
* pending list persisted to ``<HERMES_HOME>/whale-widget/approval-state.json``
  (id / command / description / session_key / ts), written ATOMICALLY
  (tmp file + os.replace); dismissal removes the entry;
* consumed by ``whale_core.wait_bridge`` → GET /wait-state.
"""

from __future__ import annotations  # noqa: F401  (stub module — implemented in M8)
