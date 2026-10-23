\set pgpass `echo "$POSTGRES_PASSWORD"`
ALTER USER authenticator WITH PASSWORD :'pgpass';
ALTER USER supabase_auth_admin WITH PASSWORD :'pgpass';
ALTER USER supabase_storage_admin WITH PASSWORD :'pgpass';
CREATE ROLE analysis_app LOGIN PASSWORD :'pgpass';
CREATE SCHEMA IF NOT EXISTS analysis AUTHORIZATION analysis_app;
GRANT USAGE ON SCHEMA auth TO analysis_app;
