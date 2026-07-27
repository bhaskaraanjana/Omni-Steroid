-- 0013_detection_auto_start_default_all.sql
-- Product default flipped: auto-start every known meeting-app source
-- (adhoc_loopback stays opt-in). Existing installs that still have the old
-- empty allowlist [] are upgraded once so Zoom/Teams/etc. work without a
-- Settings visit. Users who later clear the list stay cleared.

UPDATE app_settings
SET value_json = '["bluejeans","browser_meet","browser_teams","browser_webex","browser_whereby","browser_zoom","chime","discord","gotomeeting","ringcentral","skype","slack","teams","telegram","whatsapp","zoom"]',
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE key = 'detection_auto_start_sources'
  AND (value_json = '[]' OR value_json IS NULL);
