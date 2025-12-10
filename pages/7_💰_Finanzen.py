"""
Finanzen & Bon-Teilen - Kassenbons erfassen und in Gruppen aufteilen
"""
import streamlit as st
from pathlib import Path
import sys
import io
import json
from datetime import datetime, timedelta
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import Receipt, ReceiptGroup, ReceiptGroupMember, Document, InvoiceStatus
from config.settings import RECEIPT_CATEGORIES
from services.ocr import get_ocr_service
from utils.helpers import format_currency, format_date, send_email_notification
from utils.components import render_sidebar_cart, apply_custom_css

st.set_page_config(page_title="Finanzen", page_icon="💰", layout="wide")
init_db()
apply_custom_css()
render_sidebar_cart()

user_id = get_current_user_id()

st.title("💰 Finanzen & Ausgaben")

# Tabs
tab_receipts, tab_groups, tab_overview, tab_invoices = st.tabs([
    "🧾 Bons erfassen",
    "👥 Gruppen & Teilen",
    "📊 Ausgaben-Übersicht",
    "📄 Rechnungen"
])


with tab_receipts:
    col_upload, col_list = st.columns([1, 2])

    with col_upload:
        st.subheader("🧾 Bon erfassen")

        # Bon hochladen oder manuell eingeben
        input_method = st.radio("Eingabemethode", ["📷 Foto/Scan", "✏️ Manuell"], horizontal=True)

        receipt_data = None
        detected_items = []

        if input_method == "📷 Foto/Scan":
            bon_file = st.file_uploader("Bon-Foto", type=['jpg', 'jpeg', 'png', 'pdf'])

            if bon_file:
                ocr = get_ocr_service()
                file_data = bon_file.read()

                with st.spinner("Analysiere Bon..."):
                    if bon_file.type == "application/pdf":
                        results = ocr.extract_text_from_pdf(file_data)
                        text = "\n".join(t for t, _ in results)
                    else:
                        from PIL import Image
                        image = Image.open(io.BytesIO(file_data))
                        st.image(image, width=300)
                        text, _ = ocr.extract_text_from_image(image)

                    # Erweiterte Bon-Analyse
                    receipt_data = ocr.extract_receipt_data(text)

                # OCR-Text anzeigen
                with st.expander("Erkannter Text"):
                    st.text(text)

                # Erkannte Daten anzeigen
                st.markdown("### Erkannte Daten")

                merchant = st.text_input("Händler", value=receipt_data.get('merchant') or "")
                bon_date = st.date_input(
                    "Datum",
                    value=receipt_data.get('date') or datetime.now()
                )
                amount = st.number_input(
                    "Gesamtbetrag (€)",
                    value=float(receipt_data.get('total') or 0.0),
                    min_value=0.0,
                    step=0.01
                )

                # Vorgeschlagene Kategorie
                suggested_cat = receipt_data.get('suggested_category', 'Sonstiges')
                cat_index = RECEIPT_CATEGORIES.index(suggested_cat) if suggested_cat in RECEIPT_CATEGORIES else 0
                category = st.selectbox("Kategorie", RECEIPT_CATEGORIES, index=cat_index)

                # Erkannte Positionen
                if receipt_data.get('items'):
                    st.markdown("### 📋 Erkannte Positionen")
                    detected_items = receipt_data['items']

                    for i, item in enumerate(detected_items):
                        col1, col2, col3 = st.columns([3, 1, 1])
                        with col1:
                            detected_items[i]['name'] = st.text_input(
                                f"Artikel {i+1}",
                                value=item['name'],
                                key=f"item_name_{i}"
                            )
                        with col2:
                            detected_items[i]['price'] = st.number_input(
                                "Preis",
                                value=float(item['price']),
                                key=f"item_price_{i}",
                                min_value=0.0
                            )
                        with col3:
                            detected_items[i]['quantity'] = st.number_input(
                                "Menge",
                                value=int(item.get('quantity', 1)),
                                key=f"item_qty_{i}",
                                min_value=1
                            )

                    # Summe der Positionen
                    items_total = sum(item['price'] * item.get('quantity', 1) for item in detected_items)
                    st.caption(f"Summe Positionen: {format_currency(items_total)}")

                # Zahlungsmethode
                payment = receipt_data.get('payment_method')
                if payment:
                    st.caption(f"💳 Zahlungsmethode: {payment}")

        else:
            # Manuelle Eingabe
            merchant = st.text_input("Händler")
            bon_date = st.date_input("Datum")
            amount = st.number_input("Betrag (€)", min_value=0.0, step=0.01)
            category = st.selectbox("Kategorie", RECEIPT_CATEGORIES)

            # Manuelle Positionen
            st.markdown("### Positionen hinzufügen (optional)")
            num_items = st.number_input("Anzahl Positionen", min_value=0, max_value=20, value=0)

            for i in range(num_items):
                col1, col2 = st.columns([3, 1])
                with col1:
                    name = st.text_input(f"Artikel {i+1}", key=f"man_item_{i}")
                with col2:
                    price = st.number_input("Preis", key=f"man_price_{i}", min_value=0.0)
                if name and price > 0:
                    detected_items.append({'name': name, 'price': price, 'quantity': 1})

        notes = st.text_input("Notizen (optional)")

        # Gruppe zuweisen
        with get_db() as session:
            groups = session.query(ReceiptGroup).filter(
                ReceiptGroup.user_id == user_id,
                ReceiptGroup.is_active == True
            ).all()

            group_options = {None: "Keine Gruppe"} | {g.id: g.name for g in groups}
            selected_group = st.selectbox(
                "Zur Gruppe hinzufügen",
                options=list(group_options.keys()),
                format_func=lambda x: group_options[x]
            )

            paid_by = None
            if selected_group:
                members = session.query(ReceiptGroupMember).filter(
                    ReceiptGroupMember.group_id == selected_group
                ).all()
                member_options = {m.id: m.name for m in members}
                paid_by = st.selectbox(
                    "Bezahlt von",
                    options=list(member_options.keys()),
                    format_func=lambda x: member_options[x]
                )

        if st.button("💾 Bon speichern", type="primary") and amount > 0:
            with get_db() as session:
                # Items als JSON speichern
                items_json = json.dumps(detected_items) if detected_items else None

                receipt = Receipt(
                    user_id=user_id,
                    group_id=selected_group,
                    merchant=merchant,
                    date=datetime.combine(bon_date, datetime.min.time()),
                    total_amount=amount,
                    category=category,
                    notes=notes,
                    paid_by_member_id=paid_by,
                    items=detected_items if detected_items else None
                )
                session.add(receipt)
                session.commit()

            st.success("Bon gespeichert!")
            st.rerun()

    with col_list:
        st.subheader("📋 Letzte Bons")

        filter_cat = st.selectbox("Kategorie filtern", ["Alle"] + RECEIPT_CATEGORIES, key="filter_bon_cat")

        with get_db() as session:
            query = session.query(Receipt).filter(Receipt.user_id == user_id)

            if filter_cat != "Alle":
                query = query.filter(Receipt.category == filter_cat)

            receipts = query.order_by(Receipt.date.desc()).limit(20).all()

            if receipts:
                for receipt in receipts:
                    with st.container():
                        col1, col2, col3 = st.columns([2, 1, 1])

                        with col1:
                            st.markdown(f"**🧾 {receipt.merchant or 'Unbekannt'}**")
                            st.caption(f"{receipt.category} | {format_date(receipt.date)}")

                        with col2:
                            st.markdown(f"**{format_currency(receipt.total_amount)}**")

                        with col3:
                            if receipt.group_id:
                                st.caption("👥")
                            with st.popover("📋"):
                                # Positionen anzeigen
                                if receipt.items:
                                    st.markdown("**Positionen:**")
                                    items = receipt.items if isinstance(receipt.items, list) else json.loads(receipt.items)
                                    for item in items:
                                        st.write(f"• {item['name']}: {format_currency(item['price'])}")

                        st.divider()
            else:
                st.info("Keine Bons erfasst")


with tab_groups:
    col_groups, col_balance = st.columns([1, 2])

    with col_groups:
        st.subheader("👥 Gruppen verwalten")

        with st.expander("➕ Neue Gruppe erstellen"):
            group_name = st.text_input("Gruppenname", placeholder="z.B. WG September, Urlaub 2024")
            group_desc = st.text_input("Beschreibung (optional)")

            use_timeframe = st.checkbox("Zeitraum festlegen")
            if use_timeframe:
                col_start, col_end = st.columns(2)
                with col_start:
                    start_date = st.date_input("Start", key="group_start")
                with col_end:
                    end_date = st.date_input("Ende", key="group_end")
            else:
                start_date = None
                end_date = None

            st.markdown("**Mitglieder hinzufügen:**")
            member_count = st.number_input("Anzahl Mitglieder", min_value=2, max_value=20, value=2)

            members_data = []
            for i in range(member_count):
                col1, col2 = st.columns(2)
                with col1:
                    name = st.text_input(f"Name {i+1}", key=f"member_name_{i}")
                with col2:
                    email = st.text_input(f"E-Mail {i+1}", key=f"member_email_{i}")
                members_data.append({"name": name, "email": email})

            if st.button("Gruppe erstellen") and group_name:
                with get_db() as session:
                    new_group = ReceiptGroup(
                        user_id=user_id,
                        name=group_name,
                        description=group_desc,
                        start_date=datetime.combine(start_date, datetime.min.time()) if start_date else None,
                        end_date=datetime.combine(end_date, datetime.min.time()) if end_date else None,
                        is_active=True
                    )
                    session.add(new_group)
                    session.flush()

                    for member in members_data:
                        if member["name"]:
                            m = ReceiptGroupMember(
                                group_id=new_group.id,
                                name=member["name"],
                                email=member["email"],
                                access_token=uuid.uuid4().hex
                            )
                            session.add(m)
                    session.commit()

                st.success("Gruppe erstellt!")
                st.rerun()

        st.divider()
        st.markdown("**Aktive Gruppen**")

        with get_db() as session:
            groups = session.query(ReceiptGroup).filter(
                ReceiptGroup.user_id == user_id
            ).order_by(ReceiptGroup.created_at.desc()).all()

            for group in groups:
                is_active = "🟢" if group.is_active else "⚪"
                if st.button(f"{is_active} {group.name}", key=f"group_{group.id}", use_container_width=True):
                    st.session_state.selected_group = group.id

    with col_balance:
        if 'selected_group' in st.session_state:
            group_id = st.session_state.selected_group

            with get_db() as session:
                group = session.query(ReceiptGroup).get(group_id)
                members = session.query(ReceiptGroupMember).filter(
                    ReceiptGroupMember.group_id == group_id
                ).all()
                receipts = session.query(Receipt).filter(Receipt.group_id == group_id).all()

                st.subheader(f"👥 {group.name}")

                if group.start_date and group.end_date:
                    st.caption(f"Zeitraum: {format_date(group.start_date)} - {format_date(group.end_date)}")

                st.markdown("---")

                st.markdown("**Mitglieder:**")
                for member in members:
                    st.write(f"👤 {member.name}")

                st.markdown("---")

                st.markdown(f"**Bons ({len(receipts)}):**")
                total = 0
                for receipt in receipts:
                    col1, col2, col3 = st.columns([2, 1, 1])
                    with col1:
                        st.write(f"🧾 {receipt.merchant}")
                    with col2:
                        st.write(format_currency(receipt.total_amount))
                    with col3:
                        if receipt.paid_by_member_id:
                            payer = session.query(ReceiptGroupMember).get(receipt.paid_by_member_id)
                            st.caption(f"von {payer.name}" if payer else "")
                    total += receipt.total_amount

                st.markdown("---")
                st.markdown(f"**Gesamt: {format_currency(total)}**")

                # Bilanz
                st.markdown("---")
                st.subheader("💰 Bilanz")

                if members and receipts:
                    n_members = len(members)
                    per_person = total / n_members

                    paid = {m.id: 0 for m in members}
                    for receipt in receipts:
                        if receipt.paid_by_member_id:
                            paid[receipt.paid_by_member_id] += receipt.total_amount

                    balance = {}
                    for member in members:
                        member_paid = paid.get(member.id, 0)
                        diff = member_paid - per_person
                        balance[member.id] = {
                            'name': member.name,
                            'paid': member_paid,
                            'share': per_person,
                            'balance': diff
                        }

                    st.write(f"Pro Person: {format_currency(per_person)}")
                    st.markdown("")

                    for member_id, data in balance.items():
                        if data['balance'] > 0:
                            st.success(f"✓ {data['name']} bekommt {format_currency(data['balance'])} zurück")
                        elif data['balance'] < 0:
                            st.error(f"✗ {data['name']} schuldet {format_currency(abs(data['balance']))}")
                        else:
                            st.info(f"= {data['name']} ist ausgeglichen")

                if group.is_active:
                    if st.button("🏁 Gruppe abschließen"):
                        group.is_active = False
                        session.commit()
                        st.success("Gruppe abgeschlossen!")
                        st.rerun()
        else:
            st.info("Wählen Sie eine Gruppe aus der Liste")


with tab_overview:
    st.subheader("📊 Ausgaben-Übersicht")

    col1, col2, col3 = st.columns(3)
    with col1:
        period = st.selectbox("Zeitraum", ["Dieser Monat", "Letzter Monat", "Dieses Jahr", "Alle"])
    with col2:
        group_by = st.selectbox("Gruppieren nach", ["Kategorie", "Händler", "Monat"])
    with col3:
        include_invoices = st.checkbox("Rechnungen einbeziehen", value=True)

    with get_db() as session:
        now = datetime.now()

        # Bons laden
        query = session.query(Receipt).filter(Receipt.user_id == user_id)

        if period == "Dieser Monat":
            query = query.filter(Receipt.date >= datetime(now.year, now.month, 1))
        elif period == "Letzter Monat":
            if now.month == 1:
                last_month = datetime(now.year - 1, 12, 1)
            else:
                last_month = datetime(now.year, now.month - 1, 1)
            query = query.filter(
                Receipt.date >= last_month,
                Receipt.date < datetime(now.year, now.month, 1)
            )
        elif period == "Dieses Jahr":
            query = query.filter(Receipt.date >= datetime(now.year, 1, 1))

        receipts = query.all()

        # Rechnungen laden (wenn aktiviert)
        invoices = []
        if include_invoices:
            inv_query = session.query(Document).filter(
                Document.user_id == user_id,
                Document.invoice_amount.isnot(None),
                Document.invoice_amount > 0
            )

            if period == "Dieser Monat":
                inv_query = inv_query.filter(Document.document_date >= datetime(now.year, now.month, 1))
            elif period == "Letzter Monat":
                if now.month == 1:
                    last_month = datetime(now.year - 1, 12, 1)
                else:
                    last_month = datetime(now.year, now.month - 1, 1)
                inv_query = inv_query.filter(
                    Document.document_date >= last_month,
                    Document.document_date < datetime(now.year, now.month, 1)
                )
            elif period == "Dieses Jahr":
                inv_query = inv_query.filter(Document.document_date >= datetime(now.year, 1, 1))

            invoices = inv_query.all()

        # Daten zusammenführen
        import pandas as pd

        data = []

        # Bons
        for r in receipts:
            data.append({
                'Typ': 'Bon',
                'Datum': r.date,
                'Beschreibung': r.merchant or 'Unbekannt',
                'Kategorie': r.category or 'Sonstiges',
                'Betrag': r.total_amount,
                'Monat': r.date.strftime('%Y-%m') if r.date else ''
            })

        # Rechnungen
        for inv in invoices:
            data.append({
                'Typ': 'Rechnung',
                'Datum': inv.document_date or inv.created_at,
                'Beschreibung': inv.sender or inv.title or 'Unbekannt',
                'Kategorie': inv.category or 'Rechnung',
                'Betrag': inv.invoice_amount,
                'Monat': (inv.document_date or inv.created_at).strftime('%Y-%m') if (inv.document_date or inv.created_at) else ''
            })

        if data:
            df = pd.DataFrame(data)

            # Kennzahlen
            col_m1, col_m2, col_m3 = st.columns(3)

            total_receipts = df[df['Typ'] == 'Bon']['Betrag'].sum()
            total_invoices = df[df['Typ'] == 'Rechnung']['Betrag'].sum()
            total_all = df['Betrag'].sum()

            with col_m1:
                st.metric("🧾 Bons", format_currency(total_receipts))
            with col_m2:
                st.metric("📄 Rechnungen", format_currency(total_invoices))
            with col_m3:
                st.metric("📊 Gesamt", format_currency(total_all))

            st.markdown("---")

            # Gruppierte Ansicht
            if group_by == "Kategorie":
                grouped = df.groupby('Kategorie')['Betrag'].sum().sort_values(ascending=False)
            elif group_by == "Händler":
                grouped = df.groupby('Beschreibung')['Betrag'].sum().sort_values(ascending=False)
            else:
                grouped = df.groupby('Monat')['Betrag'].sum().sort_values()

            # Chart
            import plotly.express as px

            fig = px.bar(
                x=grouped.index,
                y=grouped.values,
                labels={'x': group_by, 'y': 'Betrag (€)'},
                title=f"Ausgaben nach {group_by}",
                color_discrete_sequence=['#1E88E5']
            )
            st.plotly_chart(fig, use_container_width=True)

            # Typ-Aufteilung
            if include_invoices:
                col_pie, col_detail = st.columns([1, 1])

                with col_pie:
                    type_grouped = df.groupby('Typ')['Betrag'].sum()
                    fig_pie = px.pie(
                        values=type_grouped.values,
                        names=type_grouped.index,
                        title="Aufteilung nach Typ"
                    )
                    st.plotly_chart(fig_pie, use_container_width=True)

                with col_detail:
                    st.markdown("**Top 10 Ausgaben:**")
                    top_10 = df.nlargest(10, 'Betrag')[['Typ', 'Beschreibung', 'Betrag', 'Datum']]
                    for _, row in top_10.iterrows():
                        icon = "🧾" if row['Typ'] == 'Bon' else "📄"
                        st.write(f"{icon} {row['Beschreibung']}: **{format_currency(row['Betrag'])}**")
        else:
            st.info("Keine Daten für den gewählten Zeitraum")


with tab_invoices:
    st.subheader("📄 Rechnungen aus Dokumenten")

    col_filter, col_status = st.columns([2, 1])

    with col_filter:
        inv_period = st.selectbox("Zeitraum", ["Alle", "Dieser Monat", "Dieses Jahr"], key="inv_period")

    with col_status:
        inv_status_filter = st.selectbox("Status", ["Alle", "Offen", "Bezahlt"], key="inv_status")

    with get_db() as session:
        query = session.query(Document).filter(
            Document.user_id == user_id,
            Document.invoice_amount.isnot(None),
            Document.invoice_amount > 0
        )

        now = datetime.now()
        if inv_period == "Dieser Monat":
            query = query.filter(Document.document_date >= datetime(now.year, now.month, 1))
        elif inv_period == "Dieses Jahr":
            query = query.filter(Document.document_date >= datetime(now.year, 1, 1))

        if inv_status_filter == "Offen":
            query = query.filter(Document.invoice_status == InvoiceStatus.OPEN)
        elif inv_status_filter == "Bezahlt":
            query = query.filter(Document.invoice_status == InvoiceStatus.PAID)

        invoices = query.order_by(Document.document_date.desc()).all()

        # Zusammenfassung
        total_open = sum(inv.invoice_amount for inv in invoices if inv.invoice_status == InvoiceStatus.OPEN)
        total_paid = sum(inv.invoice_amount for inv in invoices if inv.invoice_status == InvoiceStatus.PAID)
        total_all = sum(inv.invoice_amount for inv in invoices)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("🔴 Offen", format_currency(total_open))
        with col2:
            st.metric("✅ Bezahlt", format_currency(total_paid))
        with col3:
            st.metric("📊 Gesamt", format_currency(total_all))

        st.markdown("---")

        if invoices:
            for inv in invoices:
                with st.container():
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])

                    with col1:
                        st.markdown(f"**{inv.title or inv.filename}**")
                        st.caption(f"{inv.sender or 'Unbekannt'} | {format_date(inv.document_date)}")

                    with col2:
                        st.markdown(f"**{format_currency(inv.invoice_amount)}**")

                    with col3:
                        if inv.invoice_status == InvoiceStatus.OPEN:
                            st.markdown("🔴 Offen")
                        elif inv.invoice_status == InvoiceStatus.PAID:
                            st.markdown("✅ Bezahlt")
                        else:
                            st.markdown("⚪ -")

                    with col4:
                        if inv.invoice_status == InvoiceStatus.OPEN:
                            if st.button("✓", key=f"pay_{inv.id}", help="Als bezahlt markieren"):
                                inv.invoice_status = InvoiceStatus.PAID
                                inv.invoice_paid_date = datetime.now()
                                session.commit()
                                st.rerun()
                        if st.button("💼", key=f"cart_inv_{inv.id}", help="In Aktentasche"):
                            from utils.components import add_to_cart
                            add_to_cart(inv.id)
                            st.success("Hinzugefügt!")

                    st.divider()
        else:
            st.info("Keine Rechnungen gefunden")
