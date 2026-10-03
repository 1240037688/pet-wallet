/**
 * Wait events — clarify tool.start/complete observation → /ingest/wait-event.
 *
 * Implemented in M8 (A-level question reminder): the observation loop lives
 * in main.js (tool.start/tool.complete gated on CLARIFY_TOOL_NAME → POST
 * /ingest/wait-event); per-session slot pairing/state is the Python wait
 * bridge's job (whale_core/wait_bridge.py). This module only pins the tool
 * name constant shared by both sides.
 */

export const CLARIFY_TOOL_NAME = 'clarify'
