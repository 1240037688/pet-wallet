/**
 * Bubble pipeline — schema → resolver → render model → renderer → queue.
 *
 * STUBS (M0). Implemented in M7 (DR-5 decoupling; DSH §C2 v1 subset).
 * schema.js   Row/Module schema validation
 * resolver.js Definition → Render Model (placeholders, weighted random, avoidIdx)
 * renderer.js Render Model → DOM (row merge, ticker, `—` semantics)
 * queue.js    priority queue (rank/batching/TTL sweep/waiting-preempt/toast fallback)
 */

export const BUBBLE_PIPELINE_VERSION = 0
