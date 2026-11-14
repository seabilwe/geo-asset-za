-- V013  Ownership
-- Migrations run as a superuser (PostGIS needs one to install). Afterwards everything is handed to gaz_owner,
-- an ordinary role, so that SECURITY DEFINER functions run with an owner's rights and not a superuser's.
-- admin.apply_ownership() is idempotent; the migration runner calls it after every run.

CREATE FUNCTION admin.apply_ownership() RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    r record;
    n integer := 0;
BEGIN
    FOR r IN SELECT nspname FROM pg_namespace
              WHERE nspname IN ('reference', 'assets', 'maintenance', 'operations', 'audit', 'staging', 'api', 'admin') LOOP
        EXECUTE format('ALTER SCHEMA %I OWNER TO gaz_owner', r.nspname);
    END LOOP;
    FOR r IN SELECT n.nspname, c.relname, c.relkind
               FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
              WHERE n.nspname IN ('reference', 'assets', 'maintenance', 'operations', 'audit', 'staging', 'api', 'admin')
                AND c.relkind IN ('r', 'v', 'm', 'S', 'p')
                AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'i')   -- skip identity sequences
                AND pg_get_userbyid(c.relowner) <> 'gaz_owner' LOOP
        EXECUTE format('ALTER %s %I.%I OWNER TO gaz_owner',
                       CASE r.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW' WHEN 'S' THEN 'SEQUENCE' ELSE 'TABLE' END,
                       r.nspname, r.relname);
        n := n + 1;
    END LOOP;
    FOR r IN SELECT p.oid::regprocedure AS sig
               FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
              WHERE n.nspname IN ('reference', 'assets', 'maintenance', 'operations', 'audit', 'staging', 'api', 'admin')
                AND pg_get_userbyid(p.proowner) <> 'gaz_owner' LOOP
        EXECUTE format('ALTER FUNCTION %s OWNER TO gaz_owner', r.sig);
        n := n + 1;
    END LOOP;
    RETURN n;
END $$;
COMMENT ON FUNCTION admin.apply_ownership() IS 'Gives every schema, table, view, sequence and function in the application schemas to gaz_owner.';

SELECT admin.apply_ownership();
