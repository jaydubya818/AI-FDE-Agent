CREATE ROLE ai_fde_owner LOGIN PASSWORD 'ai_fde_owner' NOINHERIT;
CREATE ROLE ai_fde_app LOGIN PASSWORD 'ai_fde_app' NOINHERIT NOBYPASSRLS;
CREATE ROLE ai_fde_worker NOLOGIN NOINHERIT NOBYPASSRLS;
-- Explicit local-only logins. Production bootstrap creates exactly one passwordless,
-- deployment-derived login and retires every predecessor.
CREATE ROLE ai_fde_worker_a4eb94d71354 LOGIN PASSWORD 'ai_fde_worker' INHERIT NOBYPASSRLS;
CREATE ROLE ai_fde_worker_d98e602bb138 LOGIN PASSWORD 'ai_fde_worker' INHERIT NOBYPASSRLS;
GRANT ai_fde_worker TO ai_fde_worker_a4eb94d71354;
GRANT ai_fde_worker TO ai_fde_worker_d98e602bb138;

ALTER DATABASE ai_fde OWNER TO ai_fde_owner;
GRANT CONNECT ON DATABASE ai_fde TO ai_fde_app;
GRANT CONNECT ON DATABASE ai_fde TO ai_fde_worker;
CREATE EXTENSION IF NOT EXISTS vector;
