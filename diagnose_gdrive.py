#!/usr/bin/env python3
"""
Google Drive Import Diagnose-Tool
Führen Sie aus: python diagnose_gdrive.py
"""
import requests
import re
import os
from pathlib import Path

def diagnose_folder(folder_url: str):
    """Analysiert einen Google Drive Ordner-Link"""

    print("=" * 70)
    print("GOOGLE DRIVE IMPORT DIAGNOSE")
    print("=" * 70)

    # Extrahiere Folder-ID
    folder_id = None
    patterns = [
        r'folders/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, folder_url)
        if match:
            folder_id = match.group(1)
            break

    if not folder_id:
        print("❌ FEHLER: Konnte keine Folder-ID aus dem Link extrahieren!")
        print(f"   Link: {folder_url}")
        return

    print(f"✓ Folder-ID erkannt: {folder_id}")
    print(f"  Link: {folder_url}")
    print()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    # Test 1: Embed-URL
    print("-" * 70)
    print("TEST 1: Embed-Ansicht")
    print("-" * 70)

    embed_url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"
    print(f"URL: {embed_url}")

    try:
        response = requests.get(embed_url, headers=headers, timeout=30, allow_redirects=True)
        print(f"Status: {response.status_code}")
        print(f"Finale URL: {response.url}")
        print(f"Content-Länge: {len(response.text)} Zeichen")

        html = response.text

        # Suche nach Dateien
        file_links = re.findall(r'file/d/([a-zA-Z0-9_-]{20,})', html)
        folder_links = re.findall(r'folders/([a-zA-Z0-9_-]{20,})', html)
        folder_links = [f for f in folder_links if f != folder_id]

        print(f"\nGefunden via Links:")
        print(f"  - Dateien: {len(set(file_links))}")
        print(f"  - Unterordner: {len(set(folder_links))}")

        # Speichere Debug-Datei
        debug_dir = Path("data/debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        debug_file = debug_dir / "diagnose_embed.html"
        with open(debug_file, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n  Debug-HTML gespeichert: {debug_file}")

    except Exception as e:
        print(f"❌ FEHLER: {e}")

    # Test 2: Standard-URL
    print()
    print("-" * 70)
    print("TEST 2: Standard-Ansicht")
    print("-" * 70)

    standard_url = f"https://drive.google.com/drive/folders/{folder_id}"
    print(f"URL: {standard_url}")

    try:
        response = requests.get(standard_url, headers=headers, timeout=30, allow_redirects=True)
        print(f"Status: {response.status_code}")
        print(f"Finale URL: {response.url}")
        print(f"Content-Länge: {len(response.text)} Zeichen")

        html = response.text
        html_lower = html.lower()

        # Prüfe auf Zugriffsprobleme
        print("\nZugriffsprüfung:")

        if 'accounts.google.com' in response.url:
            print("  ❌ PROBLEM: Weiterleitung zur Google-Anmeldung!")
            print("     -> Der Ordner ist NICHT öffentlich freigegeben!")
            print("     -> Lösung: Ordner-Freigabe auf 'Jeder mit dem Link' setzen")
        elif 'you need access' in html_lower or 'zugriff anfordern' in html_lower:
            print("  ❌ PROBLEM: Zugriff verweigert!")
            print("     -> Der Ordner ist nicht öffentlich freigegeben")
        elif 'sorry, the file you have requested does not exist' in html_lower:
            print("  ❌ PROBLEM: Ordner nicht gefunden!")
            print("     -> Der Link ist ungültig oder der Ordner wurde gelöscht")
        else:
            print("  ✓ Ordner scheint zugänglich zu sein")

        # Suche nach Dateien/Ordnern mit verschiedenen Methoden
        print("\nInhaltsanalyse:")

        # Methode 1: Links
        file_ids = set(re.findall(r'file/d/([a-zA-Z0-9_-]{20,})', html))
        folder_ids = set(re.findall(r'folders/([a-zA-Z0-9_-]{20,})', html))
        folder_ids.discard(folder_id)

        print(f"  Methode 1 (Links):")
        print(f"    - Dateien: {len(file_ids)}")
        print(f"    - Ordner: {len(folder_ids)}")

        # Methode 2: JSON-Arrays
        pattern = r'\["([a-zA-Z0-9_-]{25,})","([^"]+)"'
        matches = re.findall(pattern, html)
        unique = {}
        for fid, name in matches:
            if fid not in unique and not name.startswith('_') and len(name) > 1:
                # Filtere UI-Elemente
                if name.lower() not in ['sign in', 'anmelden', 'drive', 'google']:
                    unique[fid] = name

        print(f"  Methode 2 (JSON-Arrays):")
        print(f"    - Einträge: {len(unique)}")

        if unique:
            print("\n  Gefundene Dateien/Ordner:")
            for fid, name in list(unique.items())[:15]:
                # Prüfe ob Datei oder Ordner
                is_folder = '.' not in name or name.endswith('/')
                icon = "📁" if is_folder else "📄"
                print(f"    {icon} {name[:60]}")

        # Methode 3: data-id Attribute
        data_ids = set(re.findall(r'data-id="([a-zA-Z0-9_-]{20,})"', html))
        print(f"  Methode 3 (data-id):")
        print(f"    - Einträge: {len(data_ids)}")

        # Speichere Debug-Datei
        debug_file = debug_dir / "diagnose_standard.html"
        with open(debug_file, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n  Debug-HTML gespeichert: {debug_file}")

    except Exception as e:
        print(f"❌ FEHLER: {e}")

    print()
    print("=" * 70)
    print("ZUSAMMENFASSUNG")
    print("=" * 70)

    total_found = len(file_ids) + len(folder_ids) + len(unique)
    if total_found > 0:
        print(f"✓ {total_found} Elemente gefunden - Import sollte funktionieren!")
        print("  Falls der Import trotzdem fehlschlägt, teilen Sie die")
        print("  Debug-Dateien unter data/debug/ mit dem Entwickler.")
    else:
        print("❌ Keine Dateien/Ordner gefunden!")
        print()
        print("Mögliche Ursachen:")
        print("1. Ordner ist nicht öffentlich freigegeben")
        print("   -> Rechtsklick auf Ordner → Freigeben → 'Jeder mit dem Link'")
        print("2. Google hat das HTML-Format geändert")
        print("   -> Teilen Sie die Debug-Dateien mit dem Entwickler")
        print()
        print(f"Debug-Dateien: {debug_dir.absolute()}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = input("Google Drive Ordner-Link eingeben: ").strip()

    if url:
        diagnose_folder(url)
    else:
        print("Kein Link eingegeben!")
