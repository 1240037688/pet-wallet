/**
 * Ingest client — POST /ingest/turn forwarding with backoff retry.
 *
 * STUB (M0). Implemented in M1 (IMPLEMENTATION_PLAN M1 task 2):
 *   - payload: session_id/profile/model/usage cumulative snapshot/raw usage
 *     sub-object/received_at/status/after_reconnect;
 *   - exponential backoff (max 3 attempts), in-memory dead letter + UI hint
 *     "accounting temporarily unavailable";
 *   - pause during gateway.reconnecting; first post-reconnect complete is
 *     tagged after_reconnect:true (Python aligns watermark without settling,
 *     DATA_MODEL §3.4).
 */

export const INGEST_TURN_PATH = '/ingest/turn'

/** Build the /ingest/turn payload from a normalized TURN_FINISHED event (M1 entry point). */
export function buildTurnPayload(turnFinished, { receivedAt, afterReconnect = false }) {
  return {
    session_id: turnFinished.session_id ?? null,
    profile: turnFinished.profile ?? null,
    usage: turnFinished.usage ?? null,
    received_at: receivedAt,
    status: turnFinished.status ?? 'complete',
    after_reconnect: afterReconnect === true,
  }
}
