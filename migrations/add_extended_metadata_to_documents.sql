-- Migration: Add extended_metadata column to documents table
-- Date: 2026-01-18
-- Description: Stores document-type specific metadata (insurance details, contract terms, loan info)

-- Add the extended_metadata JSON column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'documents'
        AND column_name = 'extended_metadata'
    ) THEN
        ALTER TABLE documents ADD COLUMN extended_metadata JSONB DEFAULT '{}';
        RAISE NOTICE 'Column extended_metadata added to documents table';
    ELSE
        RAISE NOTICE 'Column extended_metadata already exists in documents table';
    END IF;
END $$;

-- Create index for better JSON query performance (optional)
CREATE INDEX IF NOT EXISTS idx_documents_extended_metadata
ON documents USING gin (extended_metadata)
WHERE extended_metadata IS NOT NULL;

-- Comment on the column
COMMENT ON COLUMN documents.extended_metadata IS 'Document-type specific metadata: insurance (monthly_rate, surrender_value, payout_amount), contracts (renewal_type, minimum_term), loans (interest_rate, remaining_debt)';
