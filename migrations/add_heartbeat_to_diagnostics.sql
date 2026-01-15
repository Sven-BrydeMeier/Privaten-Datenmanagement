-- Migration: Add heartbeat tracking fields to cloud_sync_diagnostics
-- Diese Felder ermöglichen die Erkennung von hängenden Sync-Prozessen

-- Neue Spalten für Heartbeat und aktuellen Status
ALTER TABLE cloud_sync_diagnostics
ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMP;

ALTER TABLE cloud_sync_diagnostics
ADD COLUMN IF NOT EXISTS current_file_name VARCHAR(500);

ALTER TABLE cloud_sync_diagnostics
ADD COLUMN IF NOT EXISTS current_file_index INTEGER;

ALTER TABLE cloud_sync_diagnostics
ADD COLUMN IF NOT EXISTS current_step VARCHAR(100);

ALTER TABLE cloud_sync_diagnostics
ADD COLUMN IF NOT EXISTS current_step_detail TEXT;

-- Kommentar hinzufügen für Dokumentation
COMMENT ON COLUMN cloud_sync_diagnostics.heartbeat_at IS 'Letztes Lebenszeichen - wird alle 5-10s aktualisiert';
COMMENT ON COLUMN cloud_sync_diagnostics.current_file_name IS 'Name der aktuell verarbeiteten Datei';
COMMENT ON COLUMN cloud_sync_diagnostics.current_file_index IS 'Index der aktuellen Datei (0-basiert)';
COMMENT ON COLUMN cloud_sync_diagnostics.current_step IS 'Aktueller Schritt: downloading, ocr, analyzing, etc.';
COMMENT ON COLUMN cloud_sync_diagnostics.current_step_detail IS 'Detailbeschreibung des aktuellen Schritts';

-- Index für schnelle Abfrage nach hängenden Syncs
CREATE INDEX IF NOT EXISTS idx_sync_diag_heartbeat
ON cloud_sync_diagnostics(heartbeat_at)
WHERE sync_status = 'running';
