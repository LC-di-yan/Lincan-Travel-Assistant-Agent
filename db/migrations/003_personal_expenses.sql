-- Bind existing ledger rows to a stable reference without changing their amounts.
BEGIN;
ALTER TABLE expenses ADD COLUMN IF NOT EXISTS entry_ref UUID;
ALTER TABLE expenses ADD COLUMN IF NOT EXISTS trip_plan_id UUID;
ALTER TABLE expenses ALTER COLUMN entry_ref SET DEFAULT gen_random_uuid();
UPDATE expenses SET entry_ref = gen_random_uuid() WHERE entry_ref IS NULL;
ALTER TABLE expenses ALTER COLUMN entry_ref SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_expense_owner_entry_ref ON expenses (user_id, entry_ref);
CREATE INDEX IF NOT EXISTS idx_expense_plan_day ON expenses (user_id, trip_plan_id, expense_date);
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conrelid = 'expenses'::regclass AND conname = 'fk_expenses_owned_plan'
    ) THEN
        ALTER TABLE expenses ADD CONSTRAINT fk_expenses_owned_plan
          FOREIGN KEY (user_id, trip_plan_id) REFERENCES trip_plans(user_id, plan_id);
    END IF;
END
$$;
COMMIT;
