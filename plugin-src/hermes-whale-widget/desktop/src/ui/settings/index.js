/**
 * Settings page — DEFERRED-BY-DESIGN to V1/M12 (REMAINING_WORK.md P3-1).
 *
 * The core flows do not depend on it: configuration goes through config.json
 * (PUT /config) and the credential file/env (INSTALL.md §Credentials), and
 * the REST surface is complete. This module will contribute the settings
 * route + sidebar nav sections when M12 lands.
 */

export const SETTINGS_VERSION = 0
