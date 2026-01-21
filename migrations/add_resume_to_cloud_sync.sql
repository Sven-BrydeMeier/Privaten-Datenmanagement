-- Migration: Resume-Funktionalität für Cloud-Sync
-- Ermöglicht Fortsetzung unterbrochener Synchronisationen

-- Resume-Felder hinzufügen
ALTER TABLE cloud_sync_connections
ADD COLUMN IF NOT EXISTS resume_from_index INTEGER DEFAULT 0;

ALTER TABLE cloud_sync_connections
ADD COLUMN IF NOT EXISTS resume_session_id VARCHAR(50);

ALTER TABLE cloud_sync_connections
ADD COLUMN IF NOT EXISTS resume_total_files INTEGER;

ALTER TABLE cloud_sync_connections
ADD COLUMN IF NOT EXISTS resume_file_list_hash VARCHAR(64);

ALTER TABLE cloud_sync_connections
ADD COLUMN IF NOT EXISTS sync_interrupted_at TIMESTAMP;

ALTER TABLE cloud_sync_connections
ADD COLUMN IF NOT EXISTS last_successful_file VARCHAR(500);

-- Adaptive Sync-Felder hinzufügen
ALTER TABLE cloud_sync_connections
ADD COLUMN IF NOT EXISTS adaptive_batch_size INTEGER DEFAULT 50;

ALTER TABLE cloud_sync_connections
ADD COLUMN IF NOT EXISTS avg_file_processing_time FLOAT;

ALTER TABLE cloud_sync_connections
ADD COLUMN IF NOT EXISTS api_throttle_detected BOOLEAN DEFAULT FALSE;

-- Index für unterbrochene Syncs
CREATE INDEX IF NOT EXISTS idx_cloud_sync_interrupted
ON cloud_sync_connections(sync_interrupted_at)
WHERE sync_interrupted_at IS NOT NULL;

COMMENT ON COLUMN cloud_sync_connections.resume_from_index IS 'Datei-Index ab dem fortgesetzt werden soll';
COMMENT ON COLUMN cloud_sync_connections.resume_session_id IS 'Eindeutige Session-ID für Konsistenzprüfung';
COMMENT ON COLUMN cloud_sync_connections.resume_total_files IS 'Gesamtanzahl Dateien bei Unterbrechung';
COMMENT ON COLUMN cloud_sync_connections.resume_file_list_hash IS 'Hash der Dateiliste zur Erkennung von Änderungen';
COMMENT ON COLUMN cloud_sync_connections.sync_interrupted_at IS 'Zeitpunkt der letzten Unterbrechung';
COMMENT ON COLUMN cloud_sync_connections.last_successful_file IS 'Name der zuletzt erfolgreich synchronisierten Datei';
COMMENT ON COLUMN cloud_sync_connections.adaptive_batch_size IS 'Dynamisch angepasste Batch-Größe basierend auf Performance';
COMMENT ON COLUMN cloud_sync_connections.avg_file_processing_time IS 'Durchschnittliche Verarbeitungszeit pro Datei in Sekunden';
COMMENT ON COLUMN cloud_sync_connections.api_throttle_detected IS 'Flag ob API-Drosselung erkannt wurde';
