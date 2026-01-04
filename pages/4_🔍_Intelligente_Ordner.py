"""
Intelligente Ordner und Aktentaschen
"""
import streamlit as st
from pathlib import Path
import sys
import json
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import (
    Document, Folder, SmartFolder, Cart, CartItem,
    InvoiceStatus, DocumentStatus
)
from config.settings import DOCUMENT_CATEGORIES
from utils.helpers import format_currency, format_date
from utils.components import render_sidebar_cart, add_to_cart

st.set_page_config(page_title="Intelligente Ordner", page_icon="🔍", layout="wide")
init_db()

# Sidebar mit Aktentasche
render_sidebar_cart()

user_id = get_current_user_id()

st.title("🔍 Intelligente Ordner & Aktentaschen")

tab_smart, tab_cart, tab_request = st.tabs([
    "📁 Intelligente Ordner",
    "💼 Aktentaschen",
    "📋 Dokumentenanforderung"
])


with tab_smart:
    st.subheader("Intelligente Ordner")
    st.markdown("Dynamische Ordner basierend auf Filterregeln")

    col_list, col_content = st.columns([1, 2])

    with col_list:
        # Vordefinierte intelligente Ordner
        predefined = [
            {
                "name": "📬 Offene Rechnungen",
                "rules": {"category": "Rechnung", "invoice_status": "OPEN"},
                "highlight": ["invoice_amount", "iban"]
            },
            {
                "name": "⏰ Fristen diese Woche",
                "rules": {"has_deadline": True, "deadline_within_days": 7},
                "highlight": []
            },
            {
                "name": "📅 Verträge (ablaufend)",
                "rules": {"category": "Vertrag", "contract_end_within_days": 90},
                "highlight": ["contract_end"]
            },
            {
                "name": "🏠 Versicherungen",
                "rules": {"category": "Versicherung"},
                "highlight": []
            }
        ]

        # Benutzerdefinierte Smart Folders laden (Daten extrahieren während Session offen)
        with get_db() as session:
            custom_folders_query = session.query(SmartFolder).filter(
                SmartFolder.user_id == user_id
            ).all()
            # Daten extrahieren während Session noch offen ist
            custom_folders = [
                {"id": cf.id, "name": cf.name, "filter_rules": cf.filter_rules}
                for cf in custom_folders_query
            ]

        st.markdown("**Vordefiniert**")
        for pf in predefined:
            if st.button(pf["name"], use_container_width=True, key=f"smart_{pf['name']}"):
                st.session_state.active_smart_folder = pf

        st.divider()
        st.markdown("**Benutzerdefiniert**")

        for cf in custom_folders:
            # Icon basierend auf Modus
            mode = cf['filter_rules'].get("mode", "auto") if cf['filter_rules'] else "auto"
            icon = "📋" if mode == "manual" else "🔍"
            if st.button(f"{icon} {cf['name']}", use_container_width=True, key=f"custom_{cf['id']}"):
                st.session_state.active_smart_folder = {
                    "id": cf['id'],  # ID für Bearbeitung
                    "name": cf['name'],
                    "rules": cf['filter_rules'] or {},
                    "highlight": []
                }

        # Neuen intelligenten Ordner erstellen
        with st.expander("➕ Neuer intelligenter Ordner"):
            sf_name = st.text_input("Name", key="sf_name", placeholder="z.B. Porsche Taycan, Bankanforderung 2024")

            # Modus-Auswahl
            sf_mode = st.radio(
                "Ordner-Modus",
                options=["auto", "manual"],
                format_func=lambda x: "🔍 Automatische Suche (findet passende Dokumente)" if x == "auto"
                                      else "📋 Manuelle Sammlung (Sie fügen Dokumente hinzu)",
                key="sf_mode",
                horizontal=True
            )

            if sf_mode == "auto":
                st.caption("Dokumente werden automatisch anhand der Suchkriterien gefunden")
                sf_search = st.text_input("Suchbegriff", key="sf_search",
                                          placeholder="Leer = Ordnername als Suchbegriff",
                                          help="Sucht in Titel, Dateiname, Absender, OCR-Text")
                sf_category = st.selectbox("Kategorie (optional)", ["Alle"] + DOCUMENT_CATEGORIES, key="sf_cat")
                sf_status = st.selectbox("Rechnungsstatus (optional)", ["Alle", "Offen", "Bezahlt"], key="sf_status")
            else:
                st.caption("Erstellen Sie einen leeren Ordner und fügen Sie manuell Dokumente hinzu")
                st.info("💡 Ideal für: Dokumentenanforderungen, Projektsammlungen, individuelle Zusammenstellungen")
                sf_search = ""
                sf_category = "Alle"
                sf_status = "Alle"

            if st.button("Erstellen", type="primary") and sf_name:
                rules = {"mode": sf_mode}

                if sf_mode == "auto":
                    # Automatische Suche: Suchbegriff verwenden
                    search_term = sf_search.strip() if sf_search.strip() else sf_name.strip()
                    rules["search_text"] = search_term

                    if sf_category != "Alle":
                        rules["category"] = sf_category
                    if sf_status == "Offen":
                        rules["invoice_status"] = "OPEN"
                    elif sf_status == "Bezahlt":
                        rules["invoice_status"] = "PAID"
                else:
                    # Manueller Modus: Leere Dokumentenliste
                    rules["manual_docs"] = []

                with get_db() as session:
                    new_sf = SmartFolder(
                        user_id=user_id,
                        name=sf_name,
                        filter_rules=rules
                    )
                    session.add(new_sf)
                    session.commit()

                if sf_mode == "auto":
                    st.success(f"✅ Erstellt! Sucht automatisch nach: '{rules.get('search_text', sf_name)}'")
                else:
                    st.success(f"✅ Erstellt! Sie können jetzt Dokumente manuell hinzufügen.")
                st.rerun()

    with col_content:
        if 'active_smart_folder' in st.session_state:
            sf = st.session_state.active_smart_folder
            st.subheader(sf["name"])

            rules = sf["rules"]
            highlight_fields = sf.get("highlight", [])
            is_manual_mode = rules.get("mode") == "manual"
            folder_id = sf.get("id")  # ID für benutzerdefinierte Ordner

            with get_db() as session:
                from sqlalchemy import or_

                if is_manual_mode:
                    # MANUELLER MODUS: Dokumente aus gespeicherter Liste
                    st.caption("📋 **Manuelle Sammlung** - Fügen Sie Dokumente hinzu")

                    manual_doc_ids = rules.get("manual_docs", [])

                    # Dokumente hinzufügen
                    with st.expander("➕ Dokumente hinzufügen"):
                        search_query = st.text_input("🔍 Dokument suchen", key="manual_search",
                                                     placeholder="Titel, Absender, etc.")

                        if search_query:
                            search_pattern = f"%{search_query}%"
                            available_docs = session.query(Document).filter(
                                Document.user_id == user_id,
                                ~Document.id.in_(manual_doc_ids) if manual_doc_ids else True,
                                or_(
                                    Document.title.ilike(search_pattern),
                                    Document.filename.ilike(search_pattern),
                                    Document.sender.ilike(search_pattern)
                                )
                            ).limit(10).all()

                            for doc in available_docs:
                                col_d, col_a = st.columns([4, 1])
                                with col_d:
                                    st.write(f"📄 {doc.title or doc.filename}")
                                    st.caption(f"{doc.sender or '—'} | {doc.category or '—'}")
                                with col_a:
                                    if st.button("➕", key=f"add_manual_{doc.id}"):
                                        # Dokument zur Liste hinzufügen
                                        if folder_id:
                                            sf_obj = session.get(SmartFolder, folder_id)
                                            if sf_obj:
                                                current_rules = sf_obj.filter_rules or {}
                                                current_docs = current_rules.get("manual_docs", [])
                                                if doc.id not in current_docs:
                                                    current_docs.append(doc.id)
                                                current_rules["manual_docs"] = current_docs
                                                sf_obj.filter_rules = current_rules
                                                session.commit()
                                                # Session State aktualisieren
                                                st.session_state.active_smart_folder["rules"]["manual_docs"] = current_docs
                                                st.rerun()

                    # Dokumente anzeigen
                    if manual_doc_ids:
                        documents = session.query(Document).filter(
                            Document.id.in_(manual_doc_ids)
                        ).all()
                        st.caption(f"{len(documents)} Dokumente in dieser Sammlung")
                    else:
                        documents = []
                        st.info("Noch keine Dokumente hinzugefügt. Nutzen Sie die Suche oben.")

                else:
                    # AUTOMATISCHER MODUS: Dokumente nach Regeln filtern
                    query = session.query(Document).filter(Document.user_id == user_id)

                    # Textsuche
                    if rules.get("search_text"):
                        search_term = rules["search_text"].lower()
                        search_pattern = f"%{search_term}%"
                        query = query.filter(
                            or_(
                                Document.title.ilike(search_pattern),
                                Document.filename.ilike(search_pattern),
                                Document.sender.ilike(search_pattern),
                                Document.ocr_text.ilike(search_pattern),
                                Document.subject.ilike(search_pattern),
                                Document.ai_summary.ilike(search_pattern)
                            )
                        )
                        st.caption(f"🔍 Automatische Suche nach: **{rules['search_text']}**")

                    if rules.get("category"):
                        query = query.filter(Document.category == rules["category"])

                    if rules.get("invoice_status") == "OPEN":
                        query = query.filter(Document.invoice_status == InvoiceStatus.OPEN)
                    elif rules.get("invoice_status") == "PAID":
                        query = query.filter(Document.invoice_status == InvoiceStatus.PAID)

                    if rules.get("contract_end_within_days"):
                        days = rules["contract_end_within_days"]
                        end_date = datetime.now() + timedelta(days=days)
                        query = query.filter(
                            Document.contract_end.isnot(None),
                            Document.contract_end <= end_date
                        )

                    documents = query.order_by(Document.created_at.desc()).all()
                    st.caption(f"{len(documents)} Dokumente gefunden")

                # Dokumente anzeigen (beide Modi)
                for doc in documents:
                    with st.container():
                        col1, col2, col3 = st.columns([3, 1, 1])

                        with col1:
                            st.markdown(f"**{doc.title or doc.filename}**")
                            st.caption(f"{doc.sender or 'Unbekannt'} | {format_date(doc.document_date)}")

                        with col2:
                            if "invoice_amount" in highlight_fields and doc.invoice_amount:
                                st.markdown(f"**:red[{format_currency(doc.invoice_amount)}]**")
                            elif doc.invoice_amount:
                                st.write(format_currency(doc.invoice_amount))

                        with col3:
                            btn_col1, btn_col2 = st.columns(2)
                            with btn_col1:
                                if st.button("📋", key=f"add_cart_{doc.id}", help="In Aktentasche"):
                                    if 'active_cart_items' not in st.session_state:
                                        st.session_state.active_cart_items = []
                                    if doc.id not in st.session_state.active_cart_items:
                                        st.session_state.active_cart_items.append(doc.id)
                            with btn_col2:
                                # Entfernen-Button nur im manuellen Modus
                                if is_manual_mode and folder_id:
                                    if st.button("❌", key=f"remove_manual_{doc.id}", help="Entfernen"):
                                        sf_obj = session.get(SmartFolder, folder_id)
                                        if sf_obj:
                                            current_rules = sf_obj.filter_rules or {}
                                            current_docs = current_rules.get("manual_docs", [])
                                            if doc.id in current_docs:
                                                current_docs.remove(doc.id)
                                            current_rules["manual_docs"] = current_docs
                                            sf_obj.filter_rules = current_rules
                                            session.commit()
                                            st.session_state.active_smart_folder["rules"]["manual_docs"] = current_docs
                                            st.rerun()

                        st.divider()
        else:
            st.info("Wählen Sie einen intelligenten Ordner aus")


with tab_cart:
    st.subheader("💼 Aktentaschen")

    col_carts, col_items = st.columns([1, 2])

    with col_carts:
        # Aktive Aktentasche
        st.markdown("**Aktuelle Aktentasche**")
        cart_items = st.session_state.get('active_cart_items', [])
        cart_name = st.session_state.get('active_cart_name', 'Aktuelle Aktentasche')

        st.info(f"💼 {cart_name}: {len(cart_items)} Dokumente")

        # Aktentasche-Aktionen
        new_cart_name = st.text_input("Aktentasche umbenennen", value=cart_name)
        if new_cart_name != cart_name:
            st.session_state.active_cart_name = new_cart_name

        if st.button("🗑️ Aktentasche leeren"):
            st.session_state.active_cart_items = []
            st.rerun()

        st.divider()

        # Gespeicherte Aktentaschen
        st.markdown("**Gespeicherte Aktentaschen**")

        with get_db() as session:
            saved_carts = session.query(Cart).filter(Cart.user_id == user_id).all()

            for cart in saved_carts:
                item_count = session.query(CartItem).filter(CartItem.cart_id == cart.id).count()
                if st.button(f"💼 {cart.name} ({item_count})", key=f"load_cart_{cart.id}"):
                    # Aktentasche laden
                    items = session.query(CartItem).filter(CartItem.cart_id == cart.id).all()
                    st.session_state.active_cart_items = [item.document_id for item in items]
                    st.session_state.active_cart_name = cart.name
                    st.rerun()

        # Aktuelle Aktentasche speichern
        if st.button("💾 Aktentasche speichern") and cart_items:
            with get_db() as session:
                new_cart = Cart(
                    user_id=user_id,
                    name=st.session_state.get('active_cart_name', 'Aktentasche')
                )
                session.add(new_cart)
                session.flush()

                for doc_id in cart_items:
                    item = CartItem(cart_id=new_cart.id, document_id=doc_id)
                    session.add(item)
                session.commit()
            st.success("Gespeichert!")

    with col_items:
        st.markdown("**Dokumente in der Aktentasche**")

        if cart_items:
            with get_db() as session:
                documents = session.query(Document).filter(
                    Document.id.in_(cart_items)
                ).all()

                for doc in documents:
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.write(f"📄 {doc.title or doc.filename}")
                        st.caption(f"{doc.category or 'Keine Kategorie'}")
                    with col2:
                        if st.button("❌", key=f"remove_{doc.id}"):
                            st.session_state.active_cart_items.remove(doc.id)
                            st.rerun()

                st.divider()

                # Aktionen
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("📧 Per E-Mail senden", use_container_width=True):
                        st.session_state.send_cart_email = True

                with col_b:
                    if st.button("🔗 Freigabelink erstellen", use_container_width=True):
                        from utils.helpers import generate_share_link
                        links = []
                        for doc_id in cart_items:
                            link = generate_share_link(doc_id)
                            links.append(link)
                        st.session_state.share_links = links

                # Aktentasche teilen
                if st.button("✂️ Aktentasche aufteilen", use_container_width=True):
                    st.session_state.split_cart = True

        else:
            st.info("Die Aktentasche ist leer. Fügen Sie Dokumente aus der Dokumentenansicht hinzu.")

        # Freigabelinks anzeigen
        if 'share_links' in st.session_state:
            st.subheader("🔗 Freigabelinks")
            for link in st.session_state.share_links:
                st.code(link)
            if st.button("Schließen"):
                del st.session_state.share_links


with tab_request:
    st.subheader("📋 Dokumentenanforderung")
    st.markdown("""
    Laden Sie eine Dokumentenanforderung hoch (z.B. von einer Bank oder Behörde).
    Die App erkennt die benötigten Dokumente und sammelt sie automatisch.
    """)

    # Anforderung eingeben
    request_method = st.radio(
        "Anforderung eingeben als:",
        ["Text", "Datei-Upload"],
        horizontal=True
    )

    requirement_text = ""

    if request_method == "Text":
        requirement_text = st.text_area(
            "Anforderungstext",
            height=200,
            placeholder="z.B.:\n- Lohnabrechnungen der letzten 3 Monate\n- Aktueller Kontoauszug\n- Mietvertrag"
        )
    else:
        req_file = st.file_uploader("Anforderungsdokument", type=['pdf', 'jpg', 'png'])
        if req_file:
            from services.ocr import get_ocr_service
            ocr = get_ocr_service()
            file_data = req_file.read()

            if req_file.type == "application/pdf":
                results = ocr.extract_text_from_pdf(file_data)
                requirement_text = "\n".join(text for text, _ in results)
            else:
                from PIL import Image
                image = Image.open(io.BytesIO(file_data))
                requirement_text, _ = ocr.extract_text_from_image(image)

            st.text_area("Erkannter Text", requirement_text, height=150, disabled=True)

    if st.button("🔍 Dokumente suchen", type="primary") and requirement_text:
        from services.ai_service import get_ai_service
        from services.search_service import get_search_service

        ai = get_ai_service()
        search = get_search_service(user_id)

        with st.spinner("Analysiere Anforderung..."):
            if ai.any_ai_available:
                requirements = ai.analyze_document_requirement(requirement_text)
            else:
                # Einfache Textanalyse
                requirements = []
                keywords = ["lohnabrechnung", "kontoauszug", "mietvertrag", "versicherung",
                           "rechnung", "vertrag", "bescheinigung"]
                for kw in keywords:
                    if kw in requirement_text.lower():
                        requirements.append({
                            "document_type": kw.capitalize(),
                            "search_terms": [kw]
                        })

        if requirements:
            st.subheader("Gefundene Anforderungen:")

            found_docs = []
            for req in requirements:
                st.write(f"**{req.get('document_type', 'Dokument')}**")
                if req.get('period'):
                    st.caption(req['period'])

                # Suchen
                search_terms = req.get('search_terms', [req.get('document_type', '')])
                for term in search_terms:
                    results = search.search(term, limit=5)
                    for item in results['items']:
                        found_docs.append(item['id'])
                        st.write(f"  ✓ {item.get('title', 'Unbenannt')}")

            # In Aktentasche legen
            st.divider()
            cart_name = st.text_input("Aktentasche-Name", value="Dokumentenanforderung")

            if st.button("💼 Alle in Aktentasche legen"):
                st.session_state.active_cart_items = list(set(found_docs))
                st.session_state.active_cart_name = cart_name
                st.success(f"{len(found_docs)} Dokumente in Aktentasche gelegt!")

            # Begleitschreiben generieren
            if ai.any_ai_available and st.button("📝 Begleitschreiben generieren"):
                with get_db() as session:
                    doc_names = []
                    for doc_id in found_docs:
                        doc = session.get(Document, doc_id)
                        if doc:
                            doc_names.append(doc.title or doc.filename)

                with st.spinner("Generiere Begleitschreiben..."):
                    cover_letter = ai.generate_cover_letter(requirement_text, doc_names)
                    st.text_area("Begleitschreiben", cover_letter, height=300)

        else:
            st.warning("Keine konkreten Anforderungen erkannt")
