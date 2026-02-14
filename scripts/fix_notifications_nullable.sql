-- Fix notifications.created_at column to be NOT NULL
-- This script repairs databases where the migration was already applied with nullable=True

-- Set the column to NOT NULL
ALTER TABLE notifications ALTER COLUMN created_at SET NOT NULL;
