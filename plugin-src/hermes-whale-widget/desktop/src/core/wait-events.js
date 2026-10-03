/**
 * Wait events — clarify tool.start/complete observation → /ingest/wait-event.
 *
 * STUB (M0). Implemented in M8 (A-level question reminder): subscribe
 * tool.start/tool.complete, match name === 'clarify', pair by tool_id,
 * per-session slots, forward to POST /ingest/wait-event.
 */

export const CLARIFY_TOOL_NAME = 'clarify'
