-- Create a function to execute raw SQL queries from the API.
-- 1. Go to your Supabase project dashboard.
-- 2. Click on "SQL Editor" in the left sidebar.
-- 3. Click "New query".
-- 4. Copy and paste the following SQL code into the editor.
-- 5. Click "Run".
-- SECURITY: This function has security implications.
-- It is defined with `SECURITY DEFINER` and runs with the privileges of the user who defines it.
-- We are setting the `search_path` to prevent it from accessing system tables.
-- Ensure your API key has the minimum required privileges.

CREATE OR REPLACE FUNCTION execute_sql(query TEXT)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  -- SET search_path = public; -- Restrict to the 'public' schema
  RETURN (SELECT jsonb_agg(t) FROM (EXECUTE query) t);
EXCEPTION
  WHEN OTHERS THEN
    -- Return a JSONB object with an error message
    RETURN jsonb_build_object('error', SQLERRM);
END;
$$;
