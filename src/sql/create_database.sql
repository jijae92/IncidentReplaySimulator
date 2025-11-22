-- Create the Athena database if it does not exist.
-- The orchestrator replaces the {glue_database} token at runtime.

CREATE DATABASE IF NOT EXISTS {glue_database};