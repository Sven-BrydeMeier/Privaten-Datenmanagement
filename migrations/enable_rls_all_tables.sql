-- ============================================================
-- SUPABASE RLS (Row Level Security) MIGRATION
-- ============================================================
-- Dieses Skript aktiviert RLS auf allen Tabellen und erstellt
-- passende Policies für sicheren Zugriff.
--
-- WICHTIG: Im Supabase SQL Editor ausführen!
--
-- Die App verwendet SQLAlchemy mit direkter Datenbankverbindung
-- (Service Role), daher sind die Policies primär für API-Schutz.
-- ============================================================

-- ============================================================
-- SCHRITT 1: RLS auf allen Tabellen aktivieren
-- ============================================================

-- Benutzerverwaltung
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

-- Dokumente & Ordner
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.folders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_shares ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shared_documents ENABLE ROW LEVEL SECURITY;

-- Tags & Zuordnungen
ALTER TABLE public.tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_virtual_folders ENABLE ROW LEVEL SECURITY;

-- Finanzen
ALTER TABLE public.bank_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bank_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bank_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.receipt_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.receipt_group_members ENABLE ROW LEVEL SECURITY;

-- Kalender & Kontakte
ALTER TABLE public.calendar_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contacts ENABLE ROW LEVEL SECURITY;

-- E-Mail-System
ALTER TABLE public.emails ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_signatures ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_dispositions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_classification_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_processing_logs ENABLE ROW LEVEL SECURITY;

-- Klassifikation & Suche
ALTER TABLE public.classification_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.classification_explanations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.folder_keywords ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.search_index ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.smart_folders ENABLE ROW LEVEL SECURITY;

-- Entitäten & Feedback
ALTER TABLE public.entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback_events ENABLE ROW LEVEL SECURITY;

-- Feld-Annotationen & Templates
ALTER TABLE public.field_annotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.layout_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_templates ENABLE ROW LEVEL SECURITY;

-- Aktentasche
ALTER TABLE public.carts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cart_items ENABLE ROW LEVEL SECURITY;

-- Benachrichtigungen & Logs
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.backup_logs ENABLE ROW LEVEL SECURITY;

-- Wiederkehrende Muster
ALTER TABLE public.recurring_patterns ENABLE ROW LEVEL SECURITY;

-- Aufgaben & Timer
ALTER TABLE public.todos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alarms ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.voice_commands ENABLE ROW LEVEL SECURITY;

-- Immobilien & Fahrzeuge
ALTER TABLE public.properties ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vehicles ENABLE ROW LEVEL SECURITY;

-- Versicherungen & Garantien
ALTER TABLE public.insurances ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.insurance_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.warranties ENABLE ROW LEVEL SECURITY;

-- Abonnements & Inventar
ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.inventory_items ENABLE ROW LEVEL SECURITY;

-- Cloud Sync
ALTER TABLE public.cloud_sync_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cloud_sync_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cloud_sync_diagnostics ENABLE ROW LEVEL SECURITY;

-- Familie
ALTER TABLE public.family_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.family_members ENABLE ROW LEVEL SECURITY;


-- ============================================================
-- SCHRITT 2: Policies erstellen
-- ============================================================
--
-- Da die App SQLAlchemy mit Service Role verwendet, wird RLS
-- automatisch umgangen. Diese Policies schützen vor direktem
-- API-Zugriff (PostgREST) durch nicht autorisierte Benutzer.
--
-- Für authenticated users: Zugriff nur auf eigene Daten (user_id)
-- ============================================================

-- -------- USERS --------
CREATE POLICY "Users can view own profile" ON public.users
    FOR SELECT TO authenticated
    USING (id = (SELECT id FROM auth.users WHERE auth.uid() = auth.users.id LIMIT 1)::int);

CREATE POLICY "Users can update own profile" ON public.users
    FOR UPDATE TO authenticated
    USING (id = (SELECT id FROM auth.users WHERE auth.uid() = auth.users.id LIMIT 1)::int);

-- -------- DOCUMENTS --------
CREATE POLICY "Users can view own documents" ON public.documents
    FOR SELECT TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

CREATE POLICY "Users can insert own documents" ON public.documents
    FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

CREATE POLICY "Users can update own documents" ON public.documents
    FOR UPDATE TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

CREATE POLICY "Users can delete own documents" ON public.documents
    FOR DELETE TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- FOLDERS --------
CREATE POLICY "Users can view own folders" ON public.folders
    FOR SELECT TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

CREATE POLICY "Users can manage own folders" ON public.folders
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- BANK_ACCOUNTS --------
CREATE POLICY "Users can manage own bank accounts" ON public.bank_accounts
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- BANK_CONNECTIONS --------
CREATE POLICY "Users can manage own bank connections" ON public.bank_connections
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- BANK_TRANSACTIONS --------
CREATE POLICY "Users can manage own transactions" ON public.bank_transactions
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- CLOUD_SYNC_CONNECTIONS --------
CREATE POLICY "Users can manage own cloud connections" ON public.cloud_sync_connections
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- CLOUD_SYNC_LOGS --------
CREATE POLICY "Users can view own sync logs" ON public.cloud_sync_logs
    FOR SELECT TO authenticated
    USING (connection_id IN (
        SELECT id FROM public.cloud_sync_connections
        WHERE user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1)
    ));

-- -------- CLOUD_SYNC_DIAGNOSTICS --------
CREATE POLICY "Users can view own sync diagnostics" ON public.cloud_sync_diagnostics
    FOR SELECT TO authenticated
    USING (connection_id IN (
        SELECT id FROM public.cloud_sync_connections
        WHERE user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1)
    ));

-- -------- EMAILS --------
CREATE POLICY "Users can manage own emails" ON public.emails
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- EMAIL_ATTACHMENTS --------
CREATE POLICY "Users can view own email attachments" ON public.email_attachments
    FOR SELECT TO authenticated
    USING (email_id IN (
        SELECT id FROM public.emails
        WHERE user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1)
    ));

-- -------- EMAIL_SIGNATURES --------
CREATE POLICY "Users can manage own email signatures" ON public.email_signatures
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- EMAIL_DISPOSITIONS --------
CREATE POLICY "Users can manage own email dispositions" ON public.email_dispositions
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- EMAIL_CLASSIFICATION_RULES --------
CREATE POLICY "Users can manage own email rules" ON public.email_classification_rules
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- EMAIL_PROCESSING_LOGS --------
CREATE POLICY "Users can view own email logs" ON public.email_processing_logs
    FOR SELECT TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- CALENDAR_EVENTS --------
CREATE POLICY "Users can manage own calendar events" ON public.calendar_events
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- CONTACTS --------
CREATE POLICY "Users can manage own contacts" ON public.contacts
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- CARTS --------
CREATE POLICY "Users can manage own carts" ON public.carts
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- CART_ITEMS --------
CREATE POLICY "Users can manage own cart items" ON public.cart_items
    FOR ALL TO authenticated
    USING (cart_id IN (
        SELECT id FROM public.carts
        WHERE user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1)
    ));

-- -------- RECEIPTS --------
CREATE POLICY "Users can manage own receipts" ON public.receipts
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- RECEIPT_GROUPS --------
CREATE POLICY "Users can manage own receipt groups" ON public.receipt_groups
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- RECEIPT_GROUP_MEMBERS --------
CREATE POLICY "Users can view own group members" ON public.receipt_group_members
    FOR SELECT TO authenticated
    USING (group_id IN (
        SELECT id FROM public.receipt_groups
        WHERE user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1)
    ));

-- -------- CLASSIFICATION_RULES --------
CREATE POLICY "Users can manage own classification rules" ON public.classification_rules
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- FOLDER_KEYWORDS --------
CREATE POLICY "Users can manage own folder keywords" ON public.folder_keywords
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- SMART_FOLDERS --------
CREATE POLICY "Users can manage own smart folders" ON public.smart_folders
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- ENTITIES --------
CREATE POLICY "Users can manage own entities" ON public.entities
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- FEEDBACK_EVENTS --------
CREATE POLICY "Users can manage own feedback events" ON public.feedback_events
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- FIELD_ANNOTATIONS --------
CREATE POLICY "Users can manage own field annotations" ON public.field_annotations
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- LAYOUT_TEMPLATES --------
CREATE POLICY "Users can manage own layout templates" ON public.layout_templates
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- TODOS --------
CREATE POLICY "Users can manage own todos" ON public.todos
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- ALARMS --------
CREATE POLICY "Users can manage own alarms" ON public.alarms
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- VOICE_COMMANDS --------
CREATE POLICY "Users can manage own voice commands" ON public.voice_commands
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- PROPERTIES --------
CREATE POLICY "Users can manage own properties" ON public.properties
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- NOTIFICATIONS --------
CREATE POLICY "Users can manage own notifications" ON public.notifications
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- AUDIT_LOGS --------
CREATE POLICY "Users can view own audit logs" ON public.audit_logs
    FOR SELECT TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- RECURRING_PATTERNS --------
CREATE POLICY "Users can manage own recurring patterns" ON public.recurring_patterns
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- DOCUMENT_NOTES --------
CREATE POLICY "Users can manage own document notes" ON public.document_notes
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- DOCUMENT_SHARES --------
CREATE POLICY "Users can manage own document shares" ON public.document_shares
    FOR ALL TO authenticated
    USING (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1))
    WITH CHECK (user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1));

-- -------- TAGS (Global, Read-Only für alle) --------
CREATE POLICY "All users can view tags" ON public.tags
    FOR SELECT TO authenticated
    USING (true);

-- -------- DOCUMENT_TAGS (Join-Table) --------
CREATE POLICY "Users can manage own document tags" ON public.document_tags
    FOR ALL TO authenticated
    USING (document_id IN (
        SELECT id FROM public.documents
        WHERE user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1)
    ));

-- -------- DOCUMENT_VIRTUAL_FOLDERS (Join-Table) --------
CREATE POLICY "Users can manage own virtual folder links" ON public.document_virtual_folders
    FOR ALL TO authenticated
    USING (document_id IN (
        SELECT id FROM public.documents
        WHERE user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1)
    ));

-- -------- DOCUMENT_ENTITIES (Join-Table) --------
CREATE POLICY "Users can manage own document entity links" ON public.document_entities
    FOR ALL TO authenticated
    USING (document_id IN (
        SELECT id FROM public.documents
        WHERE user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1)
    ));

-- -------- SEARCH_INDEX --------
CREATE POLICY "Users can view own search index" ON public.search_index
    FOR SELECT TO authenticated
    USING (document_id IN (
        SELECT id FROM public.documents
        WHERE user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1)
    ));

-- -------- CLASSIFICATION_EXPLANATIONS --------
CREATE POLICY "Users can view own classification explanations" ON public.classification_explanations
    FOR SELECT TO authenticated
    USING (document_id IN (
        SELECT id FROM public.documents
        WHERE user_id = (SELECT id FROM public.users WHERE email = auth.email() LIMIT 1)
    ));

-- -------- Tabellen ohne user_id (Service-Only oder Global) --------
-- Diese Tabellen erlauben nur Service-Role Zugriff (keine authenticated Policy)

-- VEHICLES, INSURANCES, INSURANCE_CLAIMS, WARRANTIES, SUBSCRIPTIONS,
-- INVENTORY_ITEMS, BACKUP_LOGS, FAMILY_GROUPS, FAMILY_MEMBERS,
-- DOCUMENT_VERSIONS, DOCUMENT_COMMENTS, SHARED_DOCUMENTS, DOCUMENT_TEMPLATES

-- Für diese Tabellen: Kein direkter API-Zugriff erlaubt
-- Der Zugriff erfolgt nur über Service Role (SQLAlchemy)

-- ANON Role komplett aussperren
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon;

-- ============================================================
-- SCHRITT 3: Verifikation
-- ============================================================

-- Zeige alle Tabellen mit RLS-Status
SELECT
    schemaname,
    tablename,
    rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;

-- Zeige alle Policies
SELECT
    schemaname,
    tablename,
    policyname,
    permissive,
    roles,
    cmd,
    qual
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename, policyname;

-- ============================================================
-- HINWEISE:
-- ============================================================
-- 1. Service Role (SQLAlchemy-Verbindung) umgeht RLS automatisch
-- 2. Die App verwendet SQLAlchemy, daher sind diese Policies
--    primär für direkten API-Zugriff (PostgREST) relevant
-- 3. Bei Problemen: Policies können mit DROP POLICY entfernt werden
-- 4. Anon-Benutzer haben keinen Zugriff auf Tabellen
-- ============================================================
