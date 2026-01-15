"""
Duplikaterkennung und -bereinigung
Findet und entfernt doppelte Dokumente in der Datenbank.
"""
import streamlit as st
from pathlib import Path
import sys
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import Document
from utils.helpers import format_date
from utils.components import render_sidebar_cart

st.set_page_config(page_title="Duplikate", page_icon="🔄", layout="wide")
init_db()
render_sidebar_cart()

user_id = get_current_user_id()

st.title("🔄 Duplikaterkennung")
st.markdown("Finde und entferne doppelte Dokumente in deiner Datenbank.")

# Tabs für verschiedene Duplikat-Typen
tab_hash, tab_name = st.tabs([
    "📊 Nach Inhalt (Hash)",
    "📝 Nach Dateiname"
])

with tab_hash:
    st.markdown("### Duplikate nach Datei-Inhalt")
    st.caption("Findet Dateien mit identischem Inhalt (gleicher Hash-Wert)")

    if st.button("🔍 Duplikate suchen", key="search_hash", type="primary"):
        with st.spinner("Analysiere Datenbank..."):
            with get_db() as session:
                # Finde alle Dokumente mit content_hash
                docs = session.query(Document).filter(
                    Document.user_id == user_id,
                    Document.content_hash != None,
                    (Document.is_deleted == False) | (Document.is_deleted == None)
                ).all()

                # Gruppiere nach Hash
                hash_groups = defaultdict(list)
                for doc in docs:
                    if doc.content_hash:
                        hash_groups[doc.content_hash].append({
                            'id': doc.id,
                            'filename': doc.filename,
                            'title': doc.title,
                            'created_at': doc.created_at,
                            'file_size': doc.file_size,
                            'folder_id': doc.folder_id
                        })

                # Nur Gruppen mit mehr als 1 Dokument = Duplikate
                duplicates = {k: v for k, v in hash_groups.items() if len(v) > 1}
                st.session_state.hash_duplicates = duplicates

    # Duplikate anzeigen
    if 'hash_duplicates' in st.session_state:
        duplicates = st.session_state.hash_duplicates

        if duplicates:
            total_dups = sum(len(v) - 1 for v in duplicates.values())
            st.warning(f"**{len(duplicates)} Duplikat-Gruppen** gefunden ({total_dups} überschüssige Dateien)")

            # Sammle alle zu löschenden IDs
            if 'selected_for_delete' not in st.session_state:
                st.session_state.selected_for_delete = set()

            # Bulk-Aktionen oben
            col_select, col_delete = st.columns([1, 1])
            with col_select:
                if st.button("☑️ Alle Duplikate auswählen", use_container_width=True):
                    for hash_val, docs in duplicates.items():
                        for doc in docs[1:]:  # Alle außer dem ersten (Original)
                            st.session_state.selected_for_delete.add(doc['id'])
                    st.rerun()

            with col_delete:
                selected_count = len(st.session_state.selected_for_delete)
                if selected_count > 0:
                    if st.button(f"🗑️ {selected_count} Duplikate löschen", type="primary", use_container_width=True):
                        with get_db() as session:
                            deleted = 0
                            for doc_id in st.session_state.selected_for_delete:
                                doc = session.get(Document, doc_id)
                                if doc:
                                    doc.is_deleted = True
                                    deleted += 1
                            session.commit()
                        st.success(f"✅ {deleted} Duplikate gelöscht!")
                        st.session_state.selected_for_delete = set()
                        del st.session_state.hash_duplicates
                        st.rerun()
                else:
                    st.button("🗑️ Keine ausgewählt", disabled=True, use_container_width=True)

            st.markdown("---")

            # Duplikat-Gruppen anzeigen
            for hash_val, docs in list(duplicates.items())[:50]:  # Max 50 Gruppen
                with st.expander(f"📁 {len(docs)} identische Dateien", expanded=False):
                    st.caption(f"Hash: `{hash_val[:16]}...`")

                    for i, doc in enumerate(docs):
                        col_check, col_info, col_date = st.columns([0.5, 5, 2])

                        with col_check:
                            if i == 0:
                                st.markdown("✅")  # Original
                            else:
                                is_selected = doc['id'] in st.session_state.selected_for_delete
                                if st.checkbox("", key=f"sel_{doc['id']}", value=is_selected):
                                    st.session_state.selected_for_delete.add(doc['id'])
                                else:
                                    st.session_state.selected_for_delete.discard(doc['id'])

                        with col_info:
                            label = "🏆 **Original behalten**" if i == 0 else "📄 Duplikat"
                            name = doc['title'] or doc['filename']
                            st.markdown(f"{label}: {name[:50]}{'...' if len(name) > 50 else ''}")
                            st.caption(f"ID: {doc['id']} | Größe: {doc['file_size'] or 0:,} Bytes")

                        with col_date:
                            if doc['created_at']:
                                st.caption(format_date(doc['created_at']))

            if len(duplicates) > 50:
                st.info(f"Zeige 50 von {len(duplicates)} Gruppen")

        else:
            st.success("✅ Keine Duplikate gefunden! Deine Datenbank ist sauber.")


with tab_name:
    st.markdown("### Duplikate nach Dateiname")
    st.caption("Findet Dateien mit gleichem oder ähnlichem Namen")

    if st.button("🔍 Nach Namen suchen", key="search_name", type="primary"):
        with st.spinner("Analysiere Dateinamen..."):
            with get_db() as session:
                docs = session.query(Document).filter(
                    Document.user_id == user_id,
                    (Document.is_deleted == False) | (Document.is_deleted == None)
                ).all()

                # Gruppiere nach normalisiertem Dateinamen
                name_groups = defaultdict(list)
                for doc in docs:
                    # Normalisiere: lowercase, ohne Extension
                    name = Path(doc.filename).stem.lower().strip()
                    name_groups[name].append({
                        'id': doc.id,
                        'filename': doc.filename,
                        'title': doc.title,
                        'created_at': doc.created_at,
                        'content_hash': doc.content_hash
                    })

                duplicates = {k: v for k, v in name_groups.items() if len(v) > 1}
                st.session_state.name_duplicates = duplicates
                # Reset selection when searching
                st.session_state.name_selected_for_delete = set()

    # Initialisiere Selection State
    if 'name_selected_for_delete' not in st.session_state:
        st.session_state.name_selected_for_delete = set()

    if 'name_duplicates' in st.session_state:
        duplicates = st.session_state.name_duplicates

        if duplicates:
            total_dups = sum(len(v) - 1 for v in duplicates.values())
            st.warning(f"**{len(duplicates)} Dateinamen** kommen mehrfach vor ({total_dups} überschüssige Dateien)")

            # Bulk-Aktionen oben
            col_select, col_delete = st.columns([1, 1])
            with col_select:
                if st.button("☑️ Alle Duplikate auswählen", key="select_all_name", use_container_width=True):
                    for name, docs in duplicates.items():
                        for doc in docs[1:]:  # Alle außer dem ersten (Original)
                            st.session_state.name_selected_for_delete.add(doc['id'])
                    st.rerun()

            with col_delete:
                selected_count = len(st.session_state.name_selected_for_delete)
                if selected_count > 0:
                    if st.button(f"🗑️ {selected_count} Duplikate löschen", key="bulk_del_name", type="primary", use_container_width=True):
                        with get_db() as session:
                            deleted = 0
                            for doc_id in st.session_state.name_selected_for_delete:
                                doc = session.get(Document, doc_id)
                                if doc:
                                    doc.is_deleted = True
                                    deleted += 1
                            session.commit()
                        st.success(f"✅ {deleted} Duplikate gelöscht!")
                        st.session_state.name_selected_for_delete = set()
                        del st.session_state.name_duplicates
                        st.rerun()
                else:
                    st.button("🗑️ Keine ausgewählt", key="no_sel_name", disabled=True, use_container_width=True)

            st.markdown("---")

            for name, docs in list(duplicates.items())[:30]:
                with st.expander(f"📄 '{name}' ({len(docs)}x)", expanded=False):
                    # Prüfe ob wirklich identisch (gleicher Hash)
                    hashes = [d['content_hash'] for d in docs if d['content_hash']]
                    if len(set(hashes)) == 1 and hashes:
                        st.success("✅ Identischer Inhalt - sicher zu löschen")
                    elif len(set(hashes)) > 1:
                        st.warning("⚠️ Unterschiedlicher Inhalt - prüfen!")
                    else:
                        st.info("ℹ️ Kein Hash verfügbar")

                    for i, doc in enumerate(docs):
                        col_check, col_info, col_hash = st.columns([0.5, 4, 2])

                        with col_check:
                            if i == 0:
                                st.markdown("✅")  # Original behalten
                            else:
                                is_selected = doc['id'] in st.session_state.name_selected_for_delete
                                if st.checkbox("", key=f"sel_name_{doc['id']}", value=is_selected, label_visibility="collapsed"):
                                    st.session_state.name_selected_for_delete.add(doc['id'])
                                else:
                                    st.session_state.name_selected_for_delete.discard(doc['id'])

                        with col_info:
                            label = "🏆 **Original behalten**" if i == 0 else "📄 Duplikat"
                            st.markdown(f"{label}: {doc['filename'][:50]}{'...' if len(doc['filename']) > 50 else ''}")
                            st.caption(f"ID: {doc['id']}")

                        with col_hash:
                            if doc['content_hash']:
                                st.caption(f"Hash: {doc['content_hash'][:8]}...")
                            else:
                                st.caption("Kein Hash")

            if len(duplicates) > 30:
                st.info(f"Zeige 30 von {len(duplicates)} Gruppen")
        else:
            st.success("✅ Keine Dateinamen-Duplikate gefunden!")


# Statistik
st.markdown("---")
st.markdown("### 📊 Datenbank-Statistik")

with get_db() as session:
    total = session.query(Document).filter(
        Document.user_id == user_id,
        (Document.is_deleted == False) | (Document.is_deleted == None)
    ).count()

    with_hash = session.query(Document).filter(
        Document.user_id == user_id,
        Document.content_hash != None,
        (Document.is_deleted == False) | (Document.is_deleted == None)
    ).count()

    deleted = session.query(Document).filter(
        Document.user_id == user_id,
        Document.is_deleted == True
    ).count()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Dokumente gesamt", total)
with col2:
    st.metric("Mit Hash (prüfbar)", with_hash)
with col3:
    st.metric("Im Papierkorb", deleted)

if deleted > 0:
    st.caption(f"💡 {deleted} Dokumente im Papierkorb werden bei der Suche ignoriert.")
