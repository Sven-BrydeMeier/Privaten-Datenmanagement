"""
Finanzen & Bon-Teilen - Kassenbons erfassen und in Gruppen aufteilen
"""
import streamlit as st
from pathlib import Path
import sys
import io
from datetime import datetime, timedelta
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import Receipt, ReceiptGroup, ReceiptGroupMember, Document
from config.settings import RECEIPT_CATEGORIES
from services.ocr import get_ocr_service
from utils.helpers import format_currency, format_date, send_email_notification

st.set_page_config(page_title="Finanzen", page_icon="💰", layout="wide")
init_db()

user_id = get_current_user_id()

st.title("💰 Finanzen & Bon-Teilen")

# Tabs
tab_receipts, tab_groups, tab_overview = st.tabs([
    "🧾 Bons erfassen",
    "👥 Gruppen & Teilen",
    "📊 Übersicht"
])


with tab_receipts:
    col_upload, col_list = st.columns([1, 2])

    with col_upload:
        st.subheader("🧾 Bon erfassen")

        # Bon hochladen oder manuell eingeben
        input_method = st.radio("Eingabemethode", ["📷 Foto/Scan", "✏️ Manuell"], horizontal=True)

        if input_method == "📷 Foto/Scan":
            bon_file = st.file_uploader("Bon-Foto", type=['jpg', 'jpeg', 'png', 'pdf'])

            if bon_file:
                # OCR
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

                    # Metadaten extrahieren
                    metadata = ocr.extract_metadata(text)

                # Vorausgefüllte Felder
                st.text_area("Erkannter Text", text, height=100, disabled=True)

                merchant = st.text_input("Händler", value="")
                bon_date = st.date_input("Datum", value=datetime.now())

                # Betrag aus OCR oder manuell
                detected_amount = metadata.get('amounts', [0])[0] if metadata.get('amounts') else 0
                amount = st.number_input("Betrag (€)", value=float(detected_amount), min_value=0.0, step=0.01)

        else:
            merchant = st.text_input("Händler")
            bon_date = st.date_input("Datum")
            amount = st.number_input("Betrag (€)", min_value=0.0, step=0.01)

        category = st.selectbox("Kategorie", RECEIPT_CATEGORIES)
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

            # Zahler (wenn Gruppe)
            paid_by = None
            if selected_group:
                group = session.query(ReceiptGroup).get(selected_group)
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
                receipt = Receipt(
                    user_id=user_id,
                    group_id=selected_group,
                    merchant=merchant,
                    date=datetime.combine(bon_date, datetime.min.time()),
                    total_amount=amount,
                    category=category,
                    notes=notes,
                    paid_by_member_id=paid_by
                )
                session.add(receipt)
                session.commit()

            st.success("Bon gespeichert!")
            st.rerun()

    with col_list:
        st.subheader("📋 Letzte Bons")

        # Filter
        filter_cat = st.selectbox("Kategorie filtern", ["Alle"] + RECEIPT_CATEGORIES, key="filter_bon_cat")

        with get_db() as session:
            query = session.query(Receipt).filter(Receipt.user_id == user_id)

            if filter_cat != "Alle":
                query = query.filter(Receipt.category == filter_cat)

            receipts = query.order_by(Receipt.date.desc()).limit(20).all()

            if receipts:
                for receipt in receipts:
                    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

                    with col1:
                        st.write(f"🧾 {receipt.merchant or 'Unbekannt'}")
                        st.caption(receipt.category)

                    with col2:
                        st.write(format_currency(receipt.total_amount))

                    with col3:
                        st.caption(format_date(receipt.date))

                    with col4:
                        if receipt.group_id:
                            st.caption("👥 Gruppe")

                    st.divider()
            else:
                st.info("Keine Bons erfasst")


with tab_groups:
    col_groups, col_balance = st.columns([1, 2])

    with col_groups:
        st.subheader("👥 Gruppen verwalten")

        # Neue Gruppe erstellen
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

        # Gruppenliste
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

                # Mitgliederliste
                st.markdown("**Mitglieder:**")
                for member in members:
                    st.write(f"👤 {member.name}")

                st.markdown("---")

                # Bons in dieser Gruppe
                st.markdown(f"**Bons ({len(receipts)}):**")
                total = 0
                for receipt in receipts:
                    col1, col2, col3 = st.columns([2, 1, 1])
                    with col1:
                        st.write(f"🧾 {receipt.merchant}")
                    with col2:
                        st.write(format_currency(receipt.total_amount))
                    with col3:
                        # Wer hat bezahlt
                        if receipt.paid_by_member_id:
                            payer = session.query(ReceiptGroupMember).get(receipt.paid_by_member_id)
                            st.caption(f"von {payer.name}" if payer else "")
                    total += receipt.total_amount

                st.markdown("---")
                st.markdown(f"**Gesamt: {format_currency(total)}**")

                # Bilanz berechnen
                st.markdown("---")
                st.subheader("💰 Bilanz")

                if members and receipts:
                    n_members = len(members)
                    per_person = total / n_members

                    # Wer hat wie viel bezahlt
                    paid = {m.id: 0 for m in members}
                    for receipt in receipts:
                        if receipt.paid_by_member_id:
                            paid[receipt.paid_by_member_id] += receipt.total_amount

                    # Bilanz
                    balance = {}
                    for member in members:
                        member_paid = paid.get(member.id, 0)
                        member_share = per_person
                        diff = member_paid - member_share
                        balance[member.id] = {
                            'name': member.name,
                            'paid': member_paid,
                            'share': member_share,
                            'balance': diff
                        }

                    # Anzeige
                    st.write(f"Pro Person: {format_currency(per_person)}")
                    st.markdown("")

                    for member_id, data in balance.items():
                        if data['balance'] > 0:
                            st.success(f"✓ {data['name']} bekommt {format_currency(data['balance'])} zurück")
                        elif data['balance'] < 0:
                            st.error(f"✗ {data['name']} schuldet {format_currency(abs(data['balance']))}")
                        else:
                            st.info(f"= {data['name']} ist ausgeglichen")

                    # Ausgleichszahlungen berechnen
                    st.markdown("---")
                    st.markdown("**Ausgleichszahlungen:**")

                    debtors = [(m_id, d) for m_id, d in balance.items() if d['balance'] < 0]
                    creditors = [(m_id, d) for m_id, d in balance.items() if d['balance'] > 0]

                    debtors.sort(key=lambda x: x[1]['balance'])
                    creditors.sort(key=lambda x: x[1]['balance'], reverse=True)

                    transactions = []
                    for d_id, debtor in debtors:
                        debt = abs(debtor['balance'])
                        for c_id, creditor in creditors:
                            if debt <= 0:
                                break
                            credit = creditor['balance']
                            if credit <= 0:
                                continue

                            amount = min(debt, credit)
                            if amount > 0.01:  # Nur wenn > 1 Cent
                                transactions.append({
                                    'from': debtor['name'],
                                    'to': creditor['name'],
                                    'amount': amount
                                })
                                debt -= amount
                                creditor['balance'] -= amount

                    for t in transactions:
                        st.write(f"💸 {t['from']} → {t['to']}: {format_currency(t['amount'])}")

                    # Einladungen senden
                    st.markdown("---")
                    if st.button("📧 Einladungen senden"):
                        for member in members:
                            if member.email and not member.invitation_sent:
                                send_email_notification(
                                    member.email,
                                    f"Einladung zur Gruppe: {group.name}",
                                    f"""Hallo {member.name},

Sie wurden zur Bon-Teilungsgruppe "{group.name}" eingeladWen.

Ihr Zugangscode: {member.access_token}

Mit freundlichen Grüßen
""",
                                    None
                                )
                                member.invitation_sent = True
                        session.commit()
                        st.success("Einladungen gesendet!")

                # Gruppe abschließen
                if group.is_active:
                    if st.button("🏁 Gruppe abschließen"):
                        group.is_active = False
                        session.commit()
                        st.success("Gruppe abgeschlossen!")
                        st.rerun()
        else:
            st.info("Wählen Sie eine Gruppe aus der Liste")


with tab_overview:
    st.subheader("📊 Finanzübersicht")

    # Zeitraum
    col1, col2 = st.columns(2)
    with col1:
        period = st.selectbox("Zeitraum", ["Dieser Monat", "Letzter Monat", "Dieses Jahr", "Alle"])
    with col2:
        group_by = st.selectbox("Gruppieren nach", ["Kategorie", "Händler", "Monat"])

    # Daten laden
    with get_db() as session:
        query = session.query(Receipt).filter(Receipt.user_id == user_id)

        # Zeitfilter
        now = datetime.now()
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

        if receipts:
            import pandas as pd

            data = [{
                'Datum': r.date,
                'Händler': r.merchant or 'Unbekannt',
                'Kategorie': r.category or 'Sonstiges',
                'Betrag': r.total_amount,
                'Monat': r.date.strftime('%Y-%m') if r.date else ''
            } for r in receipts]

            df = pd.DataFrame(data)

            # Gesamtsumme
            total = df['Betrag'].sum()
            st.metric("Gesamtausgaben", format_currency(total))

            st.markdown("---")

            # Gruppierte Ansicht
            if group_by == "Kategorie":
                grouped = df.groupby('Kategorie')['Betrag'].sum().sort_values(ascending=False)
            elif group_by == "Händler":
                grouped = df.groupby('Händler')['Betrag'].sum().sort_values(ascending=False)
            else:
                grouped = df.groupby('Monat')['Betrag'].sum().sort_values()

            # Balkendiagramm
            import plotly.express as px

            fig = px.bar(
                x=grouped.index,
                y=grouped.values,
                labels={'x': group_by, 'y': 'Betrag (€)'},
                title=f"Ausgaben nach {group_by}"
            )
            st.plotly_chart(fig, use_container_width=True)

            # Detailtabelle
            st.markdown("---")
            st.markdown("**Details:**")

            for name, amount in grouped.items():
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(name)
                with col2:
                    st.write(format_currency(amount))
        else:
            st.info("Keine Daten für den gewählten Zeitraum")
