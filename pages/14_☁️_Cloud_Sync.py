"""
Cloud-Sync Seite
Synchronisation von Dokumenten aus Dropbox und Google Drive
"""
import streamlit as st
from datetime import datetime, timedelta
import json

# Imports
try:
    from services.cloud_sync_service import CloudSyncService, parse_cloud_link, CloudProvider
    from database.extended_models import CloudSyncConnection, CloudSyncLog, SyncStatus
    from database.models import Folder, get_session
    CLOUD_SYNC_AVAILABLE = True
except ImportError:
    CLOUD_SYNC_AVAILABLE = False


def render_cloud_sync_page():
    """Rendert die Cloud-Sync Seite"""
    st.title("Cloud-Synchronisation")
    st.markdown("Automatischer Import von Dokumenten aus Dropbox und Google Drive")

    if not CLOUD_SYNC_AVAILABLE:
        st.error("Cloud-Sync Module nicht verfügbar. Bitte starten Sie die App neu.")
        return

    # Benutzer-Check
    if "user" not in st.session_state or not st.session_state.user:
        st.warning("Bitte melden Sie sich an, um Cloud-Sync zu verwenden.")
        return

    user_id = st.session_state.user.get("id", 1)
    sync_service = CloudSyncService(user_id)

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "Verbindungen", "Neue Verbindung", "Sync-Protokoll", "Einstellungen"
    ])

    with tab1:
        render_connections_tab(sync_service, user_id)

    with tab2:
        render_new_connection_tab(sync_service, user_id)

    with tab3:
        render_sync_log_tab(sync_service)

    with tab4:
        render_settings_tab(sync_service)


def render_connections_tab(sync_service: CloudSyncService, user_id: int):
    """Tab: Bestehende Verbindungen"""
    st.subheader("Aktive Verbindungen")

    connections = sync_service.get_connections(active_only=False)

    if not connections:
        st.info("Noch keine Cloud-Verbindungen eingerichtet.")
        st.markdown("""
        **So funktioniert's:**
        1. Erstellen Sie eine neue Verbindung im Tab "Neue Verbindung"
        2. Geben Sie einen Dropbox- oder Google Drive-Link ein
        3. Dateien werden automatisch importiert und verarbeitet
        4. Bereits importierte Dateien werden nicht erneut heruntergeladen
        """)
        return

    for conn in connections:
        with st.expander(
            f"{'🟢' if conn.is_active else '🔴'} {conn.provider_name or conn.provider.value} - {conn.remote_folder_path[:50]}...",
            expanded=conn.is_active
        ):
            col1, col2, col3 = st.columns([2, 1, 1])

            with col1:
                st.markdown(f"**Provider:** {get_provider_icon(conn.provider)} {conn.provider.value}")
                st.markdown(f"**Ordner:** `{conn.remote_folder_path}`")
                st.markdown(f"**Status:** {get_status_badge(conn.status)}")

                if conn.last_sync_at:
                    st.markdown(f"**Letzte Sync:** {conn.last_sync_at.strftime('%d.%m.%Y %H:%M')}")
                else:
                    st.markdown("**Letzte Sync:** Noch nie")

                if conn.last_sync_error:
                    st.error(f"Letzter Fehler: {conn.last_sync_error}")

            with col2:
                st.metric("Sync. Dateien", conn.total_files_synced or 0)
                st.metric("Intervall", f"{conn.sync_interval_minutes} Min.")

            with col3:
                # Aktionen
                if st.button("Jetzt synchronisieren", key=f"sync_{conn.id}"):
                    with st.spinner("Synchronisiere..."):
                        result = sync_service.sync_connection(conn.id)
                        if result["files_synced"] > 0:
                            st.success(f"{result['files_synced']} Dateien importiert!")
                        elif result["files_skipped"] > 0:
                            st.info(f"Keine neuen Dateien. {result['files_skipped']} bereits vorhanden.")
                        if result["errors"]:
                            for err in result["errors"][:3]:
                                st.warning(err)
                        st.rerun()

                if conn.is_active:
                    if st.button("Deaktivieren", key=f"deactivate_{conn.id}"):
                        sync_service.update_connection(conn.id, is_active=False)
                        st.success("Verbindung deaktiviert")
                        st.rerun()
                else:
                    if st.button("Aktivieren", key=f"activate_{conn.id}"):
                        sync_service.update_connection(conn.id, is_active=True)
                        st.success("Verbindung aktiviert")
                        st.rerun()

                if st.button("Löschen", key=f"delete_{conn.id}", type="secondary"):
                    if st.session_state.get(f"confirm_delete_{conn.id}"):
                        sync_service.delete_connection(conn.id)
                        st.success("Verbindung gelöscht")
                        st.rerun()
                    else:
                        st.session_state[f"confirm_delete_{conn.id}"] = True
                        st.warning("Erneut klicken zum Bestätigen")

    # Statistiken
    st.divider()
    st.subheader("Gesamtstatistik")

    stats = sync_service.get_sync_statistics()
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Gesamt synchronisiert", stats["total_synced"])
    with col2:
        st.metric("Übersprungen (Duplikate)", stats["total_skipped"])
    with col3:
        st.metric("Fehler", stats["total_errors"])
    with col4:
        st.metric("Gesamtgröße", f"{stats['total_mb']} MB")


def render_new_connection_tab(sync_service: CloudSyncService, user_id: int):
    """Tab: Neue Verbindung erstellen"""
    st.subheader("Neue Cloud-Verbindung")

    st.markdown("""
    ### Unterstützte Dienste

    | Dienst | Link-Format | Hinweis |
    |--------|-------------|---------|
    | **Dropbox** | Freigabe-Link eines Ordners | Ordner muss öffentlich freigegeben sein |
    | **Google Drive** | Link zu einem Ordner | Ordner muss "Jeder mit dem Link" haben |
    """)

    st.divider()

    # Einfache Link-Eingabe
    st.markdown("### 1. Cloud-Link eingeben")

    cloud_link = st.text_input(
        "Dropbox- oder Google Drive-Link",
        placeholder="https://www.dropbox.com/sh/... oder https://drive.google.com/drive/folders/...",
        help="Kopieren Sie den Freigabe-Link des Ordners"
    )

    provider, folder_id = None, None

    if cloud_link:
        provider, folder_id = parse_cloud_link(cloud_link)

        if provider:
            st.success(f"Erkannt: {get_provider_icon(provider)} {provider.value}")
        else:
            st.error("Link nicht erkannt. Bitte verwenden Sie einen gültigen Dropbox oder Google Drive Link.")

    st.divider()
    st.markdown("### 2. Einstellungen")

    col1, col2 = st.columns(2)

    with col1:
        # Zielordner auswählen
        with get_session() as session:
            folders = session.query(Folder).filter(
                Folder.user_id == user_id
            ).all()

        folder_options = {"Kein Ordner (Root)": None}
        for f in folders:
            folder_options[f.name] = f.id

        selected_folder = st.selectbox(
            "Zielordner in der App",
            options=list(folder_options.keys()),
            help="Wohin sollen die Dokumente importiert werden?"
        )
        target_folder_id = folder_options[selected_folder]

        # Verbindungsname
        connection_name = st.text_input(
            "Name der Verbindung",
            value=f"Cloud-Import {datetime.now().strftime('%d.%m.%Y')}",
            help="Ein beschreibender Name für diese Verbindung"
        )

    with col2:
        # Sync-Intervall
        sync_interval = st.selectbox(
            "Sync-Intervall",
            options=[5, 15, 30, 60, 120, 360, 720, 1440],
            index=1,
            format_func=lambda x: f"{x} Minuten" if x < 60 else f"{x//60} Stunde(n)",
            help="Wie oft soll nach neuen Dateien gesucht werden?"
        )

        # Automatische Verarbeitung
        auto_process = st.checkbox(
            "Dokumente automatisch verarbeiten",
            value=True,
            help="OCR, Klassifizierung und Metadaten-Extraktion"
        )

        # Dateifilter
        st.markdown("**Dateifilter:**")
        filter_pdf = st.checkbox("PDF", value=True)
        filter_images = st.checkbox("Bilder (JPG, PNG)", value=True)
        filter_office = st.checkbox("Office (DOC, XLS)", value=True)

    # Dateiendungen zusammenstellen
    file_extensions = []
    if filter_pdf:
        file_extensions.append(".pdf")
    if filter_images:
        file_extensions.extend([".jpg", ".jpeg", ".png", ".gif"])
    if filter_office:
        file_extensions.extend([".doc", ".docx", ".xls", ".xlsx"])

    st.divider()

    # API-Credentials (optional für OAuth)
    with st.expander("Erweitert: API-Zugangsdaten (optional)"):
        st.markdown("""
        Für private Ordner benötigen Sie API-Zugangsdaten:
        - **Dropbox:** [App Console](https://www.dropbox.com/developers/apps)
        - **Google:** [Cloud Console](https://console.cloud.google.com)
        """)

        api_client_id = st.text_input("Client ID", type="password")
        api_client_secret = st.text_input("Client Secret", type="password")
        access_token = st.text_input("Access Token (falls vorhanden)", type="password")

    st.divider()

    # Verbindung erstellen
    if st.button("Verbindung erstellen", type="primary", disabled=not provider):
        if not cloud_link:
            st.error("Bitte geben Sie einen Cloud-Link ein.")
            return

        try:
            # Verbindung erstellen
            connection = sync_service.create_connection(
                provider=provider,
                remote_folder_path=cloud_link,
                access_token=access_token or "public",  # Placeholder für öffentliche Links
                local_folder_id=target_folder_id,
                provider_name=connection_name
            )

            # Einstellungen aktualisieren
            sync_service.update_connection(
                connection.id,
                sync_interval_minutes=sync_interval,
                auto_process=auto_process,
                file_extensions=file_extensions,
                remote_folder_id=folder_id
            )

            st.success("Verbindung erfolgreich erstellt!")

            # Erste Synchronisation anbieten
            if st.button("Jetzt erste Synchronisation starten"):
                with st.spinner("Synchronisiere..."):
                    result = sync_service.sync_connection(connection.id, auto_process)
                    st.success(f"Erste Sync abgeschlossen: {result['files_synced']} Dateien importiert")

            st.info("Wechseln Sie zum Tab 'Verbindungen' um den Status zu sehen.")

        except Exception as e:
            st.error(f"Fehler beim Erstellen der Verbindung: {e}")


def render_sync_log_tab(sync_service: CloudSyncService):
    """Tab: Sync-Protokoll"""
    st.subheader("Synchronisations-Protokoll")

    # Verbindung auswählen
    connections = sync_service.get_connections(active_only=False)

    if not connections:
        st.info("Keine Verbindungen vorhanden.")
        return

    conn_options = {f"{c.provider_name or c.provider.value} ({c.id})": c.id for c in connections}
    conn_options["Alle Verbindungen"] = None

    selected_conn = st.selectbox(
        "Verbindung filtern",
        options=list(conn_options.keys())
    )
    connection_id = conn_options[selected_conn]

    # Logs abrufen
    logs = sync_service.get_sync_logs(connection_id, limit=100)

    if not logs:
        st.info("Noch keine Sync-Einträge vorhanden.")
        return

    # Statistik
    stats = sync_service.get_sync_statistics(connection_id)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Erfolgreich", stats["total_synced"])
    with col2:
        st.metric("Übersprungen", stats["total_skipped"])
    with col3:
        st.metric("Fehler", stats["total_errors"])
    with col4:
        st.metric("Gesamtgröße", f"{stats['total_mb']} MB")

    st.divider()

    # Log-Tabelle
    st.markdown("### Letzte Synchronisationen")

    for log in logs[:50]:
        status_icon = "✅" if log.sync_status == "synced" else "⏭️" if log.sync_status == "skipped" else "❌"

        with st.expander(f"{status_icon} {log.original_filename} - {log.synced_at.strftime('%d.%m.%Y %H:%M')}"):
            col1, col2 = st.columns(2)

            with col1:
                st.markdown(f"**Quelldatei:** `{log.remote_file_path}`")
                st.markdown(f"**Größe:** {format_size(log.file_size)}")
                st.markdown(f"**MIME-Type:** {log.mime_type}")

            with col2:
                st.markdown(f"**Status:** {log.sync_status}")
                if log.document_id:
                    st.markdown(f"**Dokument-ID:** {log.document_id}")
                if log.error_message:
                    st.error(f"Fehler: {log.error_message}")

    # Log-Datei herunterladen
    st.divider()
    st.markdown("### Log-Datei")

    if connection_id:
        log_content = sync_service.get_log_file_content(connection_id)
        if log_content:
            st.download_button(
                "Log-Datei herunterladen",
                data=log_content,
                file_name=f"sync_log_{connection_id}_{datetime.now().strftime('%Y%m%d')}.log",
                mime="text/plain"
            )


def render_settings_tab(sync_service: CloudSyncService):
    """Tab: Einstellungen"""
    st.subheader("Sync-Einstellungen")

    st.markdown("### Globale Einstellungen")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Automatische Synchronisation**")
        auto_sync = st.checkbox(
            "Aktiviert",
            value=True,
            help="Führt Synchronisationen im Hintergrund aus"
        )

        if auto_sync:
            st.info("Die automatische Synchronisation läuft gemäß den Intervallen der einzelnen Verbindungen.")

    with col2:
        st.markdown("**Benachrichtigungen**")
        notify_new = st.checkbox("Bei neuen Dokumenten", value=True)
        notify_error = st.checkbox("Bei Fehlern", value=True)

    st.divider()

    st.markdown("### Speicherplatz")

    # Speicherplatz-Info
    stats = sync_service.get_sync_statistics()

    st.metric(
        "Gesamter Speicher durch Cloud-Sync",
        f"{stats['total_mb']} MB",
        help="Gesamtgröße aller über Cloud-Sync importierten Dateien"
    )

    st.divider()

    st.markdown("### Hilfe & Dokumentation")

    st.markdown("""
    #### Dropbox einrichten

    1. Öffnen Sie den gewünschten Ordner in Dropbox
    2. Klicken Sie auf "Teilen" → "Link erstellen"
    3. Kopieren Sie den Link und fügen Sie ihn hier ein

    #### Google Drive einrichten

    1. Öffnen Sie den gewünschten Ordner in Google Drive
    2. Rechtsklick → "Freigeben" → "Link abrufen"
    3. Setzen Sie "Jeder mit dem Link" und kopieren Sie den Link

    #### Wichtig: Keine Überschreibung

    - Bereits importierte Dateien werden **nicht** erneut heruntergeladen
    - Die Erkennung erfolgt über den Datei-Hash (Inhalt)
    - Alle Importe werden im Log protokolliert
    """)


# ==================== HILFSFUNKTIONEN ====================

def get_provider_icon(provider: CloudProvider) -> str:
    """Gibt Icon für Provider zurück"""
    icons = {
        CloudProvider.DROPBOX: "📦",
        CloudProvider.GOOGLE_DRIVE: "📁",
        CloudProvider.ONEDRIVE: "☁️",
        CloudProvider.NEXTCLOUD: "🌐"
    }
    return icons.get(provider, "☁️")


def get_status_badge(status: SyncStatus) -> str:
    """Gibt Status-Badge zurück"""
    badges = {
        SyncStatus.PENDING: "🟡 Ausstehend",
        SyncStatus.SYNCING: "🔄 Synchronisiert...",
        SyncStatus.COMPLETED: "🟢 Abgeschlossen",
        SyncStatus.ERROR: "🔴 Fehler",
        SyncStatus.PAUSED: "⏸️ Pausiert"
    }
    return badges.get(status, str(status))


def format_size(size_bytes: int) -> str:
    """Formatiert Dateigröße"""
    if not size_bytes:
        return "0 B"

    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024

    return f"{size_bytes:.1f} TB"


# ==================== HAUPTFUNKTION ====================

if __name__ == "__main__":
    st.set_page_config(
        page_title="Cloud-Sync",
        page_icon="☁️",
        layout="wide"
    )
    render_cloud_sync_page()
else:
    render_cloud_sync_page()
