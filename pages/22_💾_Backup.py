"""
Backup & Restore Seite
Datensicherung und Wiederherstellung
"""
import streamlit as st
from datetime import datetime
from pathlib import Path

# Imports
try:
    from services.backup_service import BackupService, DeveloperSnapshot, get_snapshot_service
    BACKUP_AVAILABLE = True
    SNAPSHOT_AVAILABLE = True
except ImportError:
    try:
        from services.backup_service import BackupService
        BACKUP_AVAILABLE = True
        SNAPSHOT_AVAILABLE = False
    except ImportError:
        BACKUP_AVAILABLE = False
        SNAPSHOT_AVAILABLE = False


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

    # Tabs - mit Entwickler-Snapshot wenn verfügbar
    if SNAPSHOT_AVAILABLE:
        tab1, tab2, tab3, tab4 = st.tabs([
            "Backup erstellen",
            "Wiederherstellen",
            "Historie",
            "🔧 Entwickler-Snapshot"
        ])
    else:
        tab1, tab2, tab3 = st.tabs(["Backup erstellen", "Wiederherstellen", "Historie"])

    with tab1:
        render_create_backup(service)

    with tab2:
        render_restore(service)

    with tab3:
        render_history(service)

    if SNAPSHOT_AVAILABLE:
        with tab4:
            render_developer_snapshot()


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


def format_size(size_bytes: int) -> str:
    """Formatiert Bytes als lesbare Größe"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def render_developer_snapshot():
    """Tab: Entwickler-Snapshots für vollständige Datensicherung"""
    st.subheader("🔧 Entwickler-Snapshot")

    st.info("""
    **Entwickler-Snapshots** sind vollständige Kopien der Datenbank und aller Dateien.

    Im Gegensatz zum normalen Backup wird hier die **komplette SQLite-Datenbank**
    direkt kopiert - inklusive aller Tabellen, Indizes und Strukturen.

    **Vorteile:**
    - Schnelle Wiederherstellung ohne Neuaufbau der Datenbank
    - Perfekt für Entwicklung und Tests
    - Enthält alle Daten, nicht nur exportierte Felder
    """)

    snapshot_service = get_snapshot_service()

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Neuen Snapshot erstellen")

        snapshot_name = st.text_input(
            "Snapshot-Name (optional)",
            placeholder="z.B. vor_feature_xyz"
        )

        include_index = st.checkbox(
            "Suchindex einschließen",
            value=False,
            help="Der Suchindex kann groß sein und wird bei Bedarf neu aufgebaut"
        )

        if st.button("📸 Snapshot erstellen", type="primary"):
            with st.spinner("Snapshot wird erstellt..."):
                result = snapshot_service.create_snapshot(
                    name=snapshot_name if snapshot_name else None,
                    include_index=include_index
                )

                if result["success"]:
                    st.success("✅ Snapshot erfolgreich erstellt!")

                    metrics_col1, metrics_col2, metrics_col3 = st.columns(3)
                    with metrics_col1:
                        st.metric("Datenbank", format_size(result["database_size"]))
                    with metrics_col2:
                        st.metric("Dateien", result["files_count"])
                    with metrics_col3:
                        st.metric("Gesamt (ZIP)", format_size(result["total_size"]))

                    # Download anbieten
                    if result["snapshot_path"]:
                        snapshot_file = Path(result["snapshot_path"])
                        if snapshot_file.exists():
                            with open(snapshot_file, "rb") as f:
                                st.download_button(
                                    "💾 Snapshot herunterladen",
                                    data=f.read(),
                                    file_name=snapshot_file.name,
                                    mime="application/zip"
                                )
                else:
                    st.error("❌ Snapshot fehlgeschlagen!")
                    for error in result.get("errors", []):
                        st.error(error)

    with col2:
        st.markdown("### Vorhandene Snapshots")

        snapshots = snapshot_service.list_snapshots()

        if snapshots:
            for snapshot in snapshots:
                with st.expander(f"📦 {snapshot['name']}", expanded=False):
                    st.markdown(f"**Erstellt:** {snapshot['created'].strftime('%d.%m.%Y %H:%M')}")
                    st.markdown(f"**Größe:** {format_size(snapshot['size'])}")
                    st.markdown(f"**Dateien:** {snapshot['files_count']}")
                    st.markdown(f"**Datenbank:** {format_size(snapshot['database_size'])}")

                    btn_col1, btn_col2, btn_col3 = st.columns(3)

                    with btn_col1:
                        # Download
                        snapshot_file = Path(snapshot["path"])
                        if snapshot_file.exists():
                            with open(snapshot_file, "rb") as f:
                                st.download_button(
                                    "⬇️ Download",
                                    data=f.read(),
                                    file_name=snapshot["filename"],
                                    mime="application/zip",
                                    key=f"dl_{snapshot['filename']}"
                                )

                    with btn_col2:
                        # Wiederherstellen
                        if st.button("🔄 Restore", key=f"restore_{snapshot['filename']}"):
                            st.session_state[f"confirm_restore_{snapshot['filename']}"] = True
                            st.rerun()

                    with btn_col3:
                        # Löschen
                        if st.button("🗑️ Löschen", key=f"del_{snapshot['filename']}"):
                            if snapshot_service.delete_snapshot(snapshot["path"]):
                                st.success("Gelöscht!")
                                st.rerun()

                    # Bestätigungsdialog für Restore
                    if st.session_state.get(f"confirm_restore_{snapshot['filename']}"):
                        st.warning("⚠️ **ACHTUNG:** Dies überschreibt ALLE aktuellen Daten!")
                        st.markdown("Die aktuelle Datenbank wird als `.db.old` gesichert.")

                        confirm_col1, confirm_col2 = st.columns(2)
                        with confirm_col1:
                            if st.button("✅ Ja, wiederherstellen", key=f"yes_{snapshot['filename']}"):
                                with st.spinner("Wiederherstellung läuft..."):
                                    result = snapshot_service.restore_snapshot(
                                        snapshot["path"],
                                        confirm=True
                                    )
                                    if result["success"]:
                                        st.success(f"✅ Snapshot wiederhergestellt! {result['documents_restored']} Dateien.")
                                        st.info("Bitte laden Sie die Seite neu (F5), um die Änderungen zu sehen.")
                                        del st.session_state[f"confirm_restore_{snapshot['filename']}"]
                                    else:
                                        st.error("❌ Wiederherstellung fehlgeschlagen!")
                                        for error in result.get("errors", []):
                                            st.error(error)

                        with confirm_col2:
                            if st.button("❌ Abbrechen", key=f"no_{snapshot['filename']}"):
                                del st.session_state[f"confirm_restore_{snapshot['filename']}"]
                                st.rerun()
        else:
            st.info("Keine Snapshots vorhanden.")

    # Snapshot hochladen
    st.divider()
    st.markdown("### Snapshot hochladen")

    uploaded_snapshot = st.file_uploader(
        "Snapshot-ZIP hochladen",
        type=["zip"],
        key="snapshot_upload"
    )

    if uploaded_snapshot:
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
            tmp.write(uploaded_snapshot.getvalue())
            tmp_path = tmp.name

        # Snapshot-Info anzeigen
        info = snapshot_service.get_snapshot_info(tmp_path)
        if info:
            st.success(f"✅ Gültiger Snapshot: **{info.get('name', 'Unbekannt')}**")
            st.markdown(f"- Erstellt: {info.get('created_at', 'Unbekannt')}")
            st.markdown(f"- Dateien: {info.get('files_count', 0)}")

            if st.button("📥 Hochgeladenen Snapshot wiederherstellen", type="primary"):
                st.session_state["confirm_upload_restore"] = True
                st.rerun()

            if st.session_state.get("confirm_upload_restore"):
                st.warning("⚠️ **ACHTUNG:** Dies überschreibt ALLE aktuellen Daten!")

                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("✅ Bestätigen"):
                        with st.spinner("Wiederherstellung läuft..."):
                            result = snapshot_service.restore_snapshot(tmp_path, confirm=True)
                            if result["success"]:
                                st.success("✅ Erfolgreich wiederhergestellt!")
                                st.info("Bitte laden Sie die Seite neu (F5).")
                                del st.session_state["confirm_upload_restore"]
                            else:
                                st.error("❌ Fehlgeschlagen!")
                with col_b:
                    if st.button("❌ Abbrechen"):
                        del st.session_state["confirm_upload_restore"]
                        st.rerun()
        else:
            st.error("❌ Keine gültige Snapshot-Datei (manifest.json fehlt)")


# ==================== HAUPTFUNKTION ====================

if __name__ == "__main__":
    st.set_page_config(page_title="Backup", page_icon="💾", layout="wide")
    render_backup_page()
else:
    render_backup_page()
