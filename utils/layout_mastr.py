"""
MaStR-Style Layout: Enterprise-Design mit Top-Header und aufklappbarer Sidebar-Navigation.
Basiert auf dem Bundesnetzagentur MaStR-Portal Design.
"""
import streamlit as st
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime

# ============================================================
# NAVIGATIONSSTRUKTUR
# ============================================================
NAVIGATION_STRUCTURE = {
    "start": {
        "label": "Persönliche Startseite",
        "icon": "🏠",
        "page": "pages/1_📊_Dashboard.py",
        "children": None
    },
    "dokumente": {
        "label": "Dokumente",
        "icon": "📄",
        "page": None,
        "children": {
            "aufnahme": {"label": "Dokumentenaufnahme", "page": "pages/2_📄_Dokumentenaufnahme.py"},
            "verwaltung": {"label": "Dokumentenverwaltung", "page": "pages/3_📁_Dokumente.py"},
            "suche": {"label": "Suche", "page": "pages/0_🔎_Suche.py"},
            "intelligente_ordner": {"label": "Intelligente Ordner", "page": "pages/4_🔍_Intelligente_Ordner.py"},
            "chat": {"label": "Dokument-Chat", "page": "pages/11_💬_Dokument_Chat.py"},
            "duplikate": {"label": "Duplikate prüfen", "page": "pages/25_🔄_Duplikate.py"},
        }
    },
    "finanzen": {
        "label": "Finanzen",
        "icon": "💰",
        "page": None,
        "children": {
            "uebersicht": {"label": "Finanzübersicht", "page": "pages/7_💰_Finanzen.py"},
            "dashboard": {"label": "Finanz-Dashboard", "page": "pages/13_📈_Finanz_Dashboard.py"},
            "steuer": {"label": "Steuer-Report", "page": "pages/21_📊_Steuer_Report.py"},
            "abonnements": {"label": "Abonnements", "page": "pages/17_💳_Abonnements.py"},
        }
    },
    "vertraege": {
        "label": "Verträge & Versicherungen",
        "icon": "📑",
        "page": None,
        "children": {
            "uebersicht": {"label": "Vertragsübersicht", "page": "pages/10_📑_Vertraege.py"},
            "versicherungen": {"label": "Versicherungen", "page": "pages/16_🏥_Versicherungen.py"},
            "garantien": {"label": "Garantien & Gewährleistungen", "page": "pages/15_🛡️_Garantien.py"},
        }
    },
    "objekte": {
        "label": "Objekte & Inventar",
        "icon": "🏠",
        "page": None,
        "children": {
            "immobilien": {"label": "Immobilien", "page": "pages/23_🏘️_Immobilien.py"},
            "entitaeten": {"label": "Entitäten (Personen/Firmen)", "page": "pages/24_👥_Entitäten.py"},
            "inventar": {"label": "Inventar", "page": "pages/18_🏠_Inventar.py"},
            "kilometer": {"label": "Kilometerlogbuch", "page": "pages/20_🚗_Kilometerlogbuch.py"},
        }
    },
    "organisation": {
        "label": "Organisation",
        "icon": "📅",
        "page": None,
        "children": {
            "kalender": {"label": "Kalender & Fristen", "page": "pages/5_📅_Kalender.py"},
            "email": {"label": "E-Mail Import", "page": "pages/6_📧_E-Mail.py"},
            "vorlagen": {"label": "Dokumentvorlagen", "page": "pages/19_📝_Vorlagen.py"},
        }
    },
    "tools": {
        "label": "Tools",
        "icon": "🔧",
        "page": None,
        "children": {
            "diktier": {"label": "Diktierfunktion", "page": "pages/9_🎤_Diktierfunktion.py"},
            "automation": {"label": "Automatisierung", "page": "pages/12_🤖_Automatisierung.py"},
            "feldmarkierung": {"label": "Feldmarkierung", "page": "pages/25_🎯_Feldmarkierung.py"},
            "backup": {"label": "Backup & Export", "page": "pages/22_💾_Backup.py"},
        }
    },
    "system": {
        "label": "Einstellungen",
        "icon": "⚙️",
        "page": None,
        "children": {
            "einstellungen": {"label": "Einstellungen", "page": "pages/8_⚙️_Einstellungen.py"},
            "diagnose": {"label": "System-Diagnose", "page": "pages/50_🔧_Diagnose.py"},
        }
    },
}

# Breadcrumb-Mapping: page_path -> (parent_label, child_label)
def get_breadcrumb_for_page(page_path: str) -> Tuple[str, str]:
    """Ermittelt Breadcrumb für eine Seite"""
    for key, nav_item in NAVIGATION_STRUCTURE.items():
        if nav_item.get("page") == page_path:
            return (nav_item["label"], None)
        children = nav_item.get("children")
        if children:
            for child_key, child_item in children.items():
                if child_item.get("page") == page_path:
                    return (nav_item["label"], child_item["label"])
    return ("Startseite", None)


def inject_mastr_css():
    """Injiziert das MaStR-ähnliche CSS"""
    st.markdown("""
    <style>
        /* ============================================
           GRUNDLEGENDE EINSTELLUNGEN
           ============================================ */

        /* Streamlit Standard-Navigation ausblenden */
        [data-testid="stSidebarNav"] {
            display: none !important;
        }

        /* Streamlit Header ausblenden */
        header[data-testid="stHeader"] {
            display: none !important;
        }

        /* Haupt-Container anpassen */
        .main .block-container {
            padding-top: 1rem !important;
            max-width: 100% !important;
        }

        /* ============================================
           TOP HEADER BAR (dunkelblau)
           ============================================ */
        .mastr-header {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            height: 60px;
            background: linear-gradient(135deg, #004b87 0%, #003366 100%);
            color: white;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 20px;
            z-index: 1000;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }

        .mastr-header-brand {
            display: flex;
            align-items: center;
            gap: 15px;
        }

        .mastr-header-brand-icon {
            font-size: 28px;
        }

        .mastr-header-brand-text {
            display: flex;
            flex-direction: column;
        }

        .mastr-header-brand-title {
            font-size: 18px;
            font-weight: 600;
            color: white;
        }

        .mastr-header-brand-subtitle {
            font-size: 11px;
            color: rgba(255,255,255,0.7);
        }

        .mastr-header-user {
            display: flex;
            align-items: center;
            gap: 25px;
        }

        .mastr-header-user-info {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 15px;
            background: rgba(255,255,255,0.1);
            border-radius: 5px;
            cursor: pointer;
        }

        .mastr-header-user-info:hover {
            background: rgba(255,255,255,0.2);
        }

        .mastr-header-user-avatar {
            width: 32px;
            height: 32px;
            background: rgba(255,255,255,0.3);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
        }

        .mastr-header-user-name {
            font-size: 14px;
            font-weight: 500;
        }

        .mastr-header-user-account {
            font-size: 11px;
            color: rgba(255,255,255,0.7);
        }

        .mastr-header-actions {
            display: flex;
            gap: 5px;
        }

        .mastr-header-action {
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 8px 15px;
            color: white;
            text-decoration: none;
            border-radius: 5px;
            transition: background 0.2s;
            cursor: pointer;
            background: transparent;
            border: none;
            min-width: 70px;
        }

        .mastr-header-action:hover {
            background: rgba(255,255,255,0.15);
        }

        .mastr-header-action-icon {
            font-size: 20px;
            position: relative;
        }

        .mastr-header-action-badge {
            position: absolute;
            top: -5px;
            right: -8px;
            background: #e53935;
            color: white;
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 10px;
            font-weight: bold;
        }

        .mastr-header-action-label {
            font-size: 11px;
            margin-top: 3px;
        }

        /* ============================================
           SIDEBAR (links)
           ============================================ */
        section[data-testid="stSidebar"] {
            background: #f5f7fa !important;
            padding-top: 70px !important;
        }

        section[data-testid="stSidebar"] > div {
            padding-top: 0 !important;
        }

        /* Sidebar Menu Item (Hauptebene) */
        .mastr-menu-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 15px;
            color: #004b87;
            cursor: pointer;
            border-left: 3px solid transparent;
            transition: all 0.2s;
            font-size: 14px;
            text-decoration: none;
        }

        .mastr-menu-item:hover {
            background: rgba(0, 75, 135, 0.08);
            border-left-color: #004b87;
        }

        .mastr-menu-item.active {
            background: rgba(0, 75, 135, 0.12);
            border-left-color: #004b87;
            font-weight: 600;
        }

        .mastr-menu-item.expanded {
            background: rgba(0, 75, 135, 0.05);
        }

        .mastr-menu-arrow {
            font-size: 12px;
            transition: transform 0.2s;
            color: #666;
        }

        .mastr-menu-arrow.expanded {
            transform: rotate(90deg);
        }

        /* Sidebar Untermenü */
        .mastr-submenu {
            background: white;
            border-left: 3px solid #e0e0e0;
            margin-left: 15px;
        }

        .mastr-submenu-item {
            display: block;
            padding: 10px 15px 10px 20px;
            color: #004b87;
            text-decoration: none;
            font-size: 13px;
            border-bottom: 1px solid #f0f0f0;
            cursor: pointer;
            transition: all 0.2s;
        }

        .mastr-submenu-item:hover {
            background: rgba(0, 75, 135, 0.05);
            color: #003366;
        }

        .mastr-submenu-item.active {
            background: rgba(0, 75, 135, 0.1);
            color: #003366;
            font-weight: 600;
            border-left: 2px solid #004b87;
        }

        /* Schnellsuche */
        .mastr-quicksearch {
            padding: 15px;
            border-top: 1px solid #e0e0e0;
            margin-top: 20px;
        }

        .mastr-quicksearch-label {
            font-size: 12px;
            color: #666;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 5px;
        }

        /* ============================================
           BREADCRUMB NAVIGATION
           ============================================ */
        .mastr-breadcrumb {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 10px 0;
            font-size: 13px;
            color: #666;
            border-bottom: 1px solid #e0e0e0;
            margin-bottom: 20px;
        }

        .mastr-breadcrumb-home {
            color: #004b87;
            text-decoration: none;
        }

        .mastr-breadcrumb-separator {
            color: #999;
        }

        .mastr-breadcrumb-item {
            color: #004b87;
            text-decoration: none;
        }

        .mastr-breadcrumb-item:hover {
            text-decoration: underline;
        }

        .mastr-breadcrumb-current {
            color: #333;
        }

        /* ============================================
           MAIN CONTENT AREA
           ============================================ */
        .mastr-page-title {
            font-size: 24px;
            font-weight: 600;
            color: #003366;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid #004b87;
        }

        .mastr-info-box {
            background: #e3f2fd;
            border-left: 4px solid #2196f3;
            padding: 15px 20px;
            margin-bottom: 20px;
            border-radius: 0 5px 5px 0;
        }

        .mastr-info-box-title {
            display: flex;
            align-items: center;
            gap: 8px;
            font-weight: 600;
            color: #1565c0;
            margin-bottom: 8px;
        }

        .mastr-info-box-content {
            color: #333;
            font-size: 14px;
            line-height: 1.5;
        }

        /* Tabs im MaStR-Stil */
        .mastr-tabs {
            display: flex;
            gap: 0;
            border-bottom: 2px solid #e0e0e0;
            margin-bottom: 20px;
        }

        .mastr-tab {
            padding: 12px 20px;
            background: #f5f5f5;
            border: 1px solid #e0e0e0;
            border-bottom: none;
            margin-bottom: -2px;
            cursor: pointer;
            color: #666;
            font-size: 14px;
            transition: all 0.2s;
        }

        .mastr-tab:hover {
            background: #e8e8e8;
        }

        .mastr-tab.active {
            background: white;
            color: #003366;
            font-weight: 600;
            border-bottom: 2px solid white;
        }

        /* Action Buttons */
        .mastr-action-buttons {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }

        .mastr-action-btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 20px;
            border-radius: 5px;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s;
            text-decoration: none;
        }

        .mastr-action-btn-primary {
            background: #004b87;
            color: white;
            border: none;
        }

        .mastr-action-btn-primary:hover {
            background: #003366;
        }

        .mastr-action-btn-secondary {
            background: white;
            color: #004b87;
            border: 1px solid #004b87;
        }

        .mastr-action-btn-secondary:hover {
            background: #f0f7ff;
        }

        /* ============================================
           STREAMLIT OVERRIDES
           ============================================ */

        /* Sidebar Buttons als Menu-Items stylen */
        section[data-testid="stSidebar"] .stButton button {
            background: transparent !important;
            border: none !important;
            border-left: 3px solid transparent !important;
            color: #004b87 !important;
            text-align: left !important;
            justify-content: flex-start !important;
            padding: 12px 15px !important;
            font-size: 14px !important;
            border-radius: 0 !important;
            width: 100% !important;
        }

        section[data-testid="stSidebar"] .stButton button:hover {
            background: rgba(0, 75, 135, 0.08) !important;
            border-left-color: #004b87 !important;
        }

        section[data-testid="stSidebar"] .stButton button:disabled {
            background: rgba(0, 75, 135, 0.12) !important;
            border-left-color: #004b87 !important;
            color: #003366 !important;
            font-weight: 600 !important;
            opacity: 1 !important;
        }

        /* Expander als Menü-Kategorie */
        section[data-testid="stSidebar"] [data-testid="stExpander"] {
            border: none !important;
            background: transparent !important;
        }

        section[data-testid="stSidebar"] [data-testid="stExpander"] > details > summary {
            padding: 12px 15px !important;
            color: #004b87 !important;
            font-weight: 500 !important;
            border-left: 3px solid transparent;
            transition: all 0.2s;
        }

        section[data-testid="stSidebar"] [data-testid="stExpander"] > details > summary:hover {
            background: rgba(0, 75, 135, 0.08);
            border-left-color: #004b87;
        }

        section[data-testid="stSidebar"] [data-testid="stExpander"] > details[open] > summary {
            background: rgba(0, 75, 135, 0.05);
            font-weight: 600;
        }

        section[data-testid="stSidebar"] .streamlit-expanderContent {
            background: white !important;
            border-left: 3px solid #e0e0e0 !important;
            margin-left: 15px !important;
            padding: 0 !important;
        }

        section[data-testid="stSidebar"] .streamlit-expanderContent .stButton button {
            padding: 10px 15px 10px 20px !important;
            font-size: 13px !important;
            border-bottom: 1px solid #f0f0f0 !important;
            border-left: none !important;
        }

        section[data-testid="stSidebar"] .streamlit-expanderContent .stButton button:disabled {
            border-left: 2px solid #004b87 !important;
        }

        /* Auto-Abmeldung Info */
        .mastr-auto-logout {
            position: fixed;
            top: 65px;
            right: 20px;
            font-size: 12px;
            color: #666;
            z-index: 999;
        }
    </style>
    """, unsafe_allow_html=True)


def render_header(user_name: str = "Benutzer", notification_count: int = 0):
    """Rendert den Top-Header im MaStR-Stil"""

    # Header HTML
    header_html = f"""
    <div class="mastr-header">
        <div class="mastr-header-brand">
            <span class="mastr-header-brand-icon">📁</span>
            <div class="mastr-header-brand-text">
                <span class="mastr-header-brand-title">DokuVerwaltung</span>
                <span class="mastr-header-brand-subtitle">Privates Dokumentenmanagement</span>
            </div>
        </div>

        <div class="mastr-header-user">
            <div class="mastr-header-user-info">
                <div class="mastr-header-user-avatar">👤</div>
                <div>
                    <div class="mastr-header-user-name">{user_name}</div>
                    <div class="mastr-header-user-account">Premium-Konto</div>
                </div>
                <span style="margin-left: 5px;">▼</span>
            </div>

            <div class="mastr-header-actions">
                <div class="mastr-header-action" onclick="window.location.href='#nachrichten'">
                    <span class="mastr-header-action-icon">
                        ✉️
                        {f'<span class="mastr-header-action-badge">{notification_count}</span>' if notification_count > 0 else ''}
                    </span>
                    <span class="mastr-header-action-label">Nachrichten</span>
                </div>
                <div class="mastr-header-action">
                    <span class="mastr-header-action-icon">❓</span>
                    <span class="mastr-header-action-label">FAQ</span>
                </div>
                <div class="mastr-header-action">
                    <span class="mastr-header-action-icon">ℹ️</span>
                    <span class="mastr-header-action-label">Hilfe</span>
                </div>
                <div class="mastr-header-action">
                    <span class="mastr-header-action-icon">🚪</span>
                    <span class="mastr-header-action-label">Abmelden</span>
                </div>
            </div>
        </div>
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)


def render_breadcrumb(parent: str, child: Optional[str] = None):
    """Rendert die Breadcrumb-Navigation"""
    breadcrumb_html = f"""
    <div class="mastr-breadcrumb">
        <a href="#" class="mastr-breadcrumb-home">🏠</a>
        <span class="mastr-breadcrumb-separator">/</span>
        {'<a href="#" class="mastr-breadcrumb-item">' + parent + '</a>' if child else '<span class="mastr-breadcrumb-current">' + parent + '</span>'}
        {('<span class="mastr-breadcrumb-separator">/</span><span class="mastr-breadcrumb-current">' + child + '</span>') if child else ''}
    </div>
    """
    st.markdown(breadcrumb_html, unsafe_allow_html=True)


def render_page_title(title: str):
    """Rendert den Seitentitel im MaStR-Stil"""
    st.markdown(f'<h1 class="mastr-page-title">{title}</h1>', unsafe_allow_html=True)


def render_info_box(title: str, content: str, icon: str = "ℹ️"):
    """Rendert eine Info-Box"""
    info_html = f"""
    <div class="mastr-info-box">
        <div class="mastr-info-box-title">{icon} {title}</div>
        <div class="mastr-info-box-content">{content}</div>
    </div>
    """
    st.markdown(info_html, unsafe_allow_html=True)


def render_sidebar_navigation():
    """Rendert die Sidebar-Navigation im MaStR-Stil"""
    current_page = st.session_state.get('_current_page', '')

    with st.sidebar:
        st.markdown("<div style='height: 10px'></div>", unsafe_allow_html=True)

        for nav_key, nav_item in NAVIGATION_STRUCTURE.items():
            label = nav_item["label"]
            icon = nav_item.get("icon", "📁")
            page = nav_item.get("page")
            children = nav_item.get("children")

            if children:
                # Kategorie mit Untermenü
                # Prüfen ob aktive Seite in dieser Kategorie
                has_active = any(
                    child.get("page") == current_page or child.get("page") in current_page
                    for child in children.values()
                )

                with st.expander(f"{icon} {label}", expanded=has_active):
                    for child_key, child_item in children.items():
                        child_label = child_item["label"]
                        child_page = child_item.get("page")
                        is_active = child_page and (child_page == current_page or child_page in current_page)

                        display_label = f"→ {child_label}" if is_active else child_label

                        if st.button(
                            display_label,
                            key=f"nav_{nav_key}_{child_key}",
                            disabled=is_active,
                            use_container_width=True
                        ):
                            if child_page:
                                st.session_state['_current_page'] = child_page
                                st.switch_page(child_page)
            else:
                # Direkter Link ohne Untermenü
                is_active = page and (page == current_page or page in current_page)
                display_label = f"{icon} → {label}" if is_active else f"{icon} {label}"

                if st.button(
                    display_label,
                    key=f"nav_{nav_key}",
                    disabled=is_active,
                    use_container_width=True
                ):
                    if page:
                        st.session_state['_current_page'] = page
                        st.switch_page(page)

        st.markdown("---")

        # Schnellsuche
        st.markdown("**🔍 Schnellsuche**")
        search_query = st.text_input(
            "Suche",
            placeholder="Dokument suchen...",
            key="sidebar_quick_search",
            label_visibility="collapsed"
        )
        if search_query:
            st.session_state.search_query_from_sidebar = search_query
            st.switch_page("pages/0_🔎_Suche.py")

        # Version
        st.markdown("---")
        from utils.components import get_version_string
        st.caption(get_version_string())


def apply_mastr_layout(page_title: str = None, show_info: bool = False, info_text: str = ""):
    """
    Wendet das MaStR-Layout auf die aktuelle Seite an.

    Args:
        page_title: Titel der Seite (optional, wird aus Navigation ermittelt)
        show_info: Zeigt Info-Box an
        info_text: Text für die Info-Box
    """
    # CSS injizieren
    inject_mastr_css()

    # Aktuelle Seite ermitteln
    import inspect
    try:
        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_file = frame.f_back.f_globals.get('__file__', '')
            if caller_file:
                caller_path = Path(caller_file)
                if 'pages' in caller_path.parts:
                    idx = caller_path.parts.index('pages')
                    rel_path = '/'.join(caller_path.parts[idx:])
                    st.session_state['_current_page'] = rel_path
    except Exception:
        pass

    current_page = st.session_state.get('_current_page', '')

    # Benutzer-Info abrufen (falls verfügbar)
    user_name = "Benutzer"
    if 'user_id' in st.session_state:
        try:
            from database.db import get_db
            from database.models import User
            with get_db() as session:
                user = session.query(User).filter(User.id == st.session_state.user_id).first()
                if user and user.display_name:
                    user_name = user.display_name
        except:
            pass

    # Header rendern
    render_header(user_name=user_name)

    # Sidebar Navigation rendern
    render_sidebar_navigation()

    # Breadcrumb ermitteln und rendern
    parent, child = get_breadcrumb_for_page(current_page)
    render_breadcrumb(parent, child)

    # Seitentitel
    if page_title:
        render_page_title(page_title)
    elif child:
        render_page_title(child)
    elif parent:
        render_page_title(parent)

    # Info-Box falls gewünscht
    if show_info and info_text:
        render_info_box("Hinweis", info_text)


def render_action_buttons(buttons: List[Dict]):
    """
    Rendert Action-Buttons im MaStR-Stil.

    Args:
        buttons: Liste von Button-Definitionen
                 [{"label": "...", "icon": "...", "primary": True/False, "key": "..."}]
    """
    cols = st.columns(len(buttons))
    results = {}

    for i, btn in enumerate(buttons):
        with cols[i]:
            btn_type = "primary" if btn.get("primary") else "secondary"
            icon = btn.get("icon", "")
            label = f"{icon} {btn['label']}" if icon else btn["label"]

            if st.button(label, key=btn.get("key", f"action_btn_{i}"), type=btn_type):
                results[btn.get("key", f"action_btn_{i}")] = True

    return results
