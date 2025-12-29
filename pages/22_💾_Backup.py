"""
Backup & Restore Seite
Datensicherung und Wiederherstellung
"""
import streamlit as st
from datetime import datetime
from pathlib import Path

# Imports
try:
    from services.backup_service import BackupService
    BACKUP_AVAILABLE = True
except ImportError:
    BACKUP_AVAILABLE = False


def render_backup_page():
    """Rendert die Backup-Seite"""
    st.title("Backup & Wiederherstellung")
    st.markdown("Sichern und Wiederherstellen Ihrer Dokumente")

    if not BACKUP_AVAILABLE:
        st.error("Backup-Module nicht verfügbar.")
        return

    if "user" not in st.session_state or not st.session_state.user:
        st.warning("Bitte melden Sie sich an.")
        return

    user_id = st.session_state.user.get("id", 1)
    service = BackupService(user_id)

    # Tabs
    tab1, tab2, tab3 = st.tabs(["Backup erstellen", "Wiederherstellen", "Historie"])

    with tab1:
        render_create_backup(service)

    with tab2:
        render_restore(service)

    with tab3:
        render_history(service)


def render_create_backup(service: BackupService):
    """Tab: Backup erstellen"""
    st.subheader("Neues Backup erstellen")

    st.markdown("""
    **Backup-Typen:**
    - **Vollständig:** Alle Dokumente, Metadaten und Dateien
    - **Nur Metadaten:** Schnelles Backup ohne Dateien
    - **Nur Dokumente:** Dateien ohne Datenbankexport
    """)

    col1, col2 = st.columns(2)

    with col1:
        backup_type = st.selectbox(
            "Backup-Typ",
            options=["full", "metadata_only", "documents_only"],
            format_func=lambda x: {
                "full": "Vollständiges Backup",
                "metadata_only": "Nur Metadaten",
                "documents_only": "Nur Dokumente"
            }.get(x, x)
        )

        include_files = st.checkbox(
            "Dateien einschließen",
            value=backup_type != "metadata_only",
            disabled=backup_type == "metadata_only"
        )

    with col2:
        st.info("""
        **Empfehlung:**
        - Wöchentlich: Vollständiges Backup
        - Täglich: Nur Metadaten (schnell)
        """)

    st.divider()

    if st.button("Backup jetzt erstellen", type="primary"):
        with st.spinner("Backup wird erstellt..."):
            result = service.create_backup(
                backup_type=backup_type,
                include_files=include_files
            )

            if result["success"]:
                st.success("Backup erfolgreich erstellt!")

                col1, col2, col3 = st.columns(3)

                with col1:
                    st.metric("Dokumente", result["documents_count"])

                with col2:
                    size_mb = result["total_size"] / (1024 * 1024)
                    st.metric("Größe", f"{size_mb:.2f} MB")

                with col3:
                    if result["backup_path"]:
                        backup_file = Path(result["backup_path"])
                        st.markdown(f"**Datei:** `{backup_file.name}`")

                # Download anbieten
                if result["backup_path"]:
                    backup_file = Path(result["backup_path"])
                    if backup_file.exists():
                        with open(backup_file, "rb") as f:
                            st.download_button(
                                "Backup herunterladen",
                                data=f.read(),
                                file_name=backup_file.name,
                                mime="application/zip"
                            )
            else:
                st.error("Backup fehlgeschlagen!")
                for error in result.get("errors", []):
                    st.error(error)


def render_restore(service: BackupService):
    """Tab: Wiederherstellen"""
    st.subheader("Backup wiederherstellen")

    st.warning("""
    **Achtung:** Die Wiederherstellung überschreibt vorhandene Daten!
    Erstellen Sie vorher ein aktuelles Backup.
    """)

    # Vorhandene Backups
    st.markdown("### Vorhandene Backups")

    backups = service.list_backups()

    if backups:
        for backup in backups[:10]:
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])

            with col1:
                st.markdown(f"**{backup['filename']}**")

            with col2:
                st.markdown(backup["created"].strftime("%d.%m.%Y"))

            with col3:
                size_mb = backup["size"] / (1024 * 1024)
                st.markdown(f"{size_mb:.2f} MB")

            with col4:
                if st.button("Wiederherstellen", key=f"restore_{backup['filename']}"):
                    st.session_state[f"restore_confirm_{backup['filename']}"] = True
                    st.rerun()

            if st.session_state.get(f"restore_confirm_{backup['filename']}"):
                st.warning("Sind Sie sicher? Diese Aktion kann nicht rückgängig gemacht werden.")

                col_a, col_b = st.columns(2)

                with col_a:
                    restore_files = st.checkbox("Dateien wiederherstellen", value=True)
                    merge = st.checkbox("Mit bestehenden Daten zusammenführen", value=False)

                with col_b:
                    if st.button("Ja, wiederherstellen", type="primary"):
                        with st.spinner("Wiederherstellung läuft..."):
                            result = service.restore_backup(
                                backup["path"],
                                restore_files=restore_files,
                                merge=merge
                            )

                            if result["success"]:
                                st.success(f"Erfolgreich! {result['documents_restored']} Dokumente wiederhergestellt.")
                                del st.session_state[f"restore_confirm_{backup['filename']}"]
                            else:
                                st.error("Wiederherstellung fehlgeschlagen!")
                                for error in result.get("errors", []):
                                    st.error(error)

                    if st.button("Abbrechen"):
                        del st.session_state[f"restore_confirm_{backup['filename']}"]
                        st.rerun()

            st.divider()
    else:
        st.info("Keine Backups vorhanden.")

    # Backup hochladen
    st.markdown("### Backup-Datei hochladen")

    uploaded_file = st.file_uploader("ZIP-Datei auswählen", type=["zip"])

    if uploaded_file:
        # Temporär speichern
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        st.success(f"Datei hochgeladen: {uploaded_file.name}")

        if st.button("Hochgeladenes Backup wiederherstellen"):
            with st.spinner("Wiederherstellung läuft..."):
                result = service.restore_backup(tmp_path, restore_files=True, merge=False)

                if result["success"]:
                    st.success(f"Erfolgreich! {result['documents_restored']} Dokumente wiederhergestellt.")
                else:
                    st.error("Wiederherstellung fehlgeschlagen!")


def render_history(service: BackupService):
    """Tab: Historie"""
    st.subheader("Backup-Historie")

    history = service.get_backup_history(limit=20)

    if not history:
        st.info("Keine Backup-Historie vorhanden.")
        return

    for log in history:
        status_icon = "✅" if log.status == "completed" else "❌"

        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

        with col1:
            st.markdown(f"{status_icon} **{get_backup_type_name(log.backup_type)}**")
            st.caption(log.created_at.strftime("%d.%m.%Y %H:%M"))

        with col2:
            st.markdown(f"{log.documents_count or 0} Dok.")

        with col3:
            if log.backup_size:
                size_mb = log.backup_size / (1024 * 1024)
                st.markdown(f"{size_mb:.2f} MB")

        with col4:
            if log.status == "completed" and log.backup_path:
                backup_file = Path(log.backup_path)
                if backup_file.exists():
                    if st.button("Löschen", key=f"del_{log.id}"):
                        if service.delete_backup(log.backup_path):
                            st.success("Gelöscht!")
                            st.rerun()

        if log.error_message:
            st.error(f"Fehler: {log.error_message}")

        st.divider()

    # Speicherplatz
    st.subheader("Speicherplatz")

    backups = service.list_backups()
    total_size = sum(b["size"] for b in backups)
    total_mb = total_size / (1024 * 1024)

    st.metric("Backup-Speicher belegt", f"{total_mb:.2f} MB")

    if backups:
        st.markdown(f"**{len(backups)} Backups** gespeichert")

        # Alte Backups löschen
        if len(backups) > 10:
            st.warning(f"Sie haben mehr als 10 Backups. Erwägen Sie, alte Backups zu löschen.")

            if st.button("Alte Backups löschen (behalte letzte 5)"):
                deleted = 0
                for backup in backups[5:]:
                    if service.delete_backup(backup["path"]):
                        deleted += 1
                st.success(f"{deleted} alte Backups gelöscht!")
                st.rerun()


def get_backup_type_name(backup_type: str) -> str:
    """Gibt deutschen Namen für Backup-Typ zurück"""
    names = {
        "full": "Vollständiges Backup",
        "metadata_only": "Nur Metadaten",
        "documents_only": "Nur Dokumente",
        "incremental": "Inkrementell"
    }
    return names.get(backup_type, backup_type)


# ==================== HAUPTFUNKTION ====================

if __name__ == "__main__":
    st.set_page_config(page_title="Backup", page_icon="💾", layout="wide")
    render_backup_page()
else:
    render_backup_page()
