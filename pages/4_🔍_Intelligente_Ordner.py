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

        # Benutzerdefinierte Smart Folders laden
        with get_db() as session:
            custom_folders = session.query(SmartFolder).filter(
                SmartFolder.user_id == user_id
            ).all()

        st.markdown("**Vordefiniert**")
        for pf in predefined:
            if st.button(pf["name"], use_container_width=True, key=f"smart_{pf['name']}"):
                st.session_state.active_smart_folder = pf

        st.divider()
        st.markdown("**Benutzerdefiniert**")

        for cf in custom_folders:
            if st.button(f"📂 {cf.name}", use_container_width=True, key=f"custom_{cf.id}"):
                st.session_state.active_smart_folder = {
                    "name": cf.name,
                    "rules": cf.filter_rules,
                    "highlight": []
                }

        # Neuen intelligenten Ordner erstellen
        with st.expander("➕ Neuer intelligenter Ordner"):
            sf_name = st.text_input("Name", key="sf_name")
            sf_category = st.selectbox("Kategorie", ["Alle"] + DOCUMENT_CATEGORIES, key="sf_cat")
            sf_status = st.selectbox("Rechnungsstatus", ["Alle", "Offen", "Bezahlt"], key="sf_status")

            if st.button("Erstellen") and sf_name:
                rules = {}
                if sf_category != "Alle":
                    rules["category"] = sf_category
                if sf_status == "Offen":
                    rules["invoice_status"] = "OPEN"
                elif sf_status == "Bezahlt":
                    rules["invoice_status"] = "PAID"

                with get_db() as session:
                    new_sf = SmartFolder(
                        user_id=user_id,
                        name=sf_name,
                        filter_rules=rules
                    )
                    session.add(new_sf)
                    session.commit()
                st.success("Erstellt!")
                st.rerun()

    with col_content:
        if 'active_smart_folder' in st.session_state:
            sf = st.session_state.active_smart_folder
            st.subheader(sf["name"])

            rules = sf["rules"]
            highlight_fields = sf.get("highlight", [])

            # Dokumente nach Regeln filtern
            with get_db() as session:
                query = session.query(Document).filter(Document.user_id == user_id)

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

                st.caption(f"{len(documents)} Dokumente")

                for doc in documents:
                    with st.container():
                        col1, col2, col3 = st.columns([3, 1, 1])

                        with col1:
                            st.markdown(f"**{doc.title or doc.filename}**")
                            st.caption(f"{doc.sender or 'Unbekannt'} | {format_date(doc.document_date)}")

                        with col2:
                            # Hervorgehobene Felder
                            if "invoice_amount" in highlight_fields and doc.invoice_amount:
                                st.markdown(f"**:red[{format_currency(doc.invoice_amount)}]**")
                            elif doc.invoice_amount:
                                st.write(format_currency(doc.invoice_amount))

                        with col3:
                            if "iban" in highlight_fields and doc.iban:
                                st.code(doc.iban)
                            if st.button("📋", key=f"add_cart_{doc.id}", help="In Aktentasche"):
                                if 'active_cart_items' not in st.session_state:
                                    st.session_state.active_cart_items = []
                                if doc.id not in st.session_state.active_cart_items:
                                    st.session_state.active_cart_items.append(doc.id)

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
                        doc = session.query(Document).get(doc_id)
                        if doc:
                            doc_names.append(doc.title or doc.filename)

                with st.spinner("Generiere Begleitschreiben..."):
                    cover_letter = ai.generate_cover_letter(requirement_text, doc_names)
                    st.text_area("Begleitschreiben", cover_letter, height=300)

        else:
            st.warning("Keine konkreten Anforderungen erkannt")
