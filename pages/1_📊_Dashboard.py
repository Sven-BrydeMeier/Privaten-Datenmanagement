"""
Dashboard-Seite - Weiterleitung zur Hauptseite
"""
import streamlit as st

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")

# Weiterleitung zur Hauptseite
st.switch_page("streamlit_app.py")
