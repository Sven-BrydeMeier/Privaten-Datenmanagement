-- Fix für Supabase Security Error: security_definer_view
-- Views mit SECURITY DEFINER umgehen RLS - das ist ein Sicherheitsrisiko.
--
-- OPTION 1: Views komplett löschen (wenn nicht benötigt)
-- DROP VIEW IF EXISTS public.lb_cases_stats;
-- DROP VIEW IF EXISTS public.lb_dashboard_stats;

-- OPTION 2: Views mit SECURITY INVOKER neu erstellen
-- Dafür musst du zuerst die aktuelle View-Definition holen:
-- SELECT pg_get_viewdef('public.lb_cases_stats', true);
-- SELECT pg_get_viewdef('public.lb_dashboard_stats', true);
--
-- Dann:
-- DROP VIEW public.lb_cases_stats;
-- CREATE VIEW public.lb_cases_stats
-- WITH (security_invoker = true)  -- oder einfach ohne SECURITY DEFINER
-- AS
-- ... (deine SELECT-Abfrage) ...;

-- Schnellfix: Views löschen und sehen ob etwas kaputt geht
-- Führe diese Befehle einzeln im Supabase SQL Editor aus:

-- 1. Prüfe zuerst was die Views machen:
SELECT 'lb_cases_stats' as view_name, pg_get_viewdef('public.lb_cases_stats', true) as definition
UNION ALL
SELECT 'lb_dashboard_stats', pg_get_viewdef('public.lb_dashboard_stats', true);

-- 2. Wenn du sicher bist, lösche sie:
-- DROP VIEW IF EXISTS public.lb_cases_stats;
-- DROP VIEW IF EXISTS public.lb_dashboard_stats;
