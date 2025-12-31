"""
Sprachbefehl-Service für die Diktierfunktion
Erkennt und verarbeitet Sprachbefehle für Kalender, Erinnerungen, Wecker und To-dos
"""
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List
from dateutil.parser import parse as parse_date
from dateutil.relativedelta import relativedelta
import json

from config.settings import get_settings


class VoiceCommandParser:
    """Parser für deutsche Sprachbefehle"""

    # Befehlsmuster (deutsche Schlüsselwörter)
    COMMAND_PATTERNS = {
        'calendar': [
            r'(?:erstelle|lege|mach|plane|trage)\s*(?:einen?)?\s*(?:termin|meeting|besprechung)',
            r'(?:neuer?|neue)\s*(?:termin|meeting|besprechung)',
            r'termin\s+(?:am|für|um)',
            r'kalender(?:eintrag)?',
        ],
        'reminder': [
            r'erinner(?:e|ung)\s*(?:mich)?',
            r'(?:erstelle|mach)\s*(?:eine?)?\s*erinnerung',
            r'nicht\s*vergessen',
            r'denk(?:e)?\s*(?:dran|daran)',
        ],
        'alarm': [
            r'(?:stelle?|stell)\s*(?:einen?)?\s*wecker',
            r'(?:weck|wecke)\s*mich',
            r'wecker\s+(?:auf|für|um)',
            r'(?:neuer?)\s*wecker',
        ],
        'timer': [
            r'(?:stelle?|stell|start(?:e)?)\s*(?:einen?)?\s*timer',
            r'timer\s+(?:auf|für)',
            r'(?:zähle?|countdown)\s*(?:herunter)?',
            r'(?:\d+)\s*(?:minuten?|sekunden?|stunden?)\s*timer',
        ],
        'todo': [
            r'(?:neue?|erstelle|mach)\s*(?:eine?)?\s*(?:aufgabe|todo|to-do)',
            r'(?:füge?|hinzufügen)\s*(?:zur?)?\s*(?:todo|aufgaben)',
            r'(?:ich\s*muss|muss\s*noch)',
            r'aufgabe\s*(?:bis|für)',
            r'todo\s*(?:bis|für)',
        ],
    }

    # Zeitausdrücke (Deutsch)
    TIME_EXPRESSIONS = {
        'jetzt': lambda: datetime.now(),
        'gleich': lambda: datetime.now() + timedelta(minutes=5),
        'heute': lambda: datetime.now().replace(hour=9, minute=0, second=0, microsecond=0),
        'morgen': lambda: (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0),
        'übermorgen': lambda: (datetime.now() + timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0),
        'nächste woche': lambda: (datetime.now() + timedelta(weeks=1)).replace(hour=9, minute=0, second=0, microsecond=0),
        'nächsten montag': lambda: VoiceCommandParser._next_weekday(0),
        'nächsten dienstag': lambda: VoiceCommandParser._next_weekday(1),
        'nächsten mittwoch': lambda: VoiceCommandParser._next_weekday(2),
        'nächsten donnerstag': lambda: VoiceCommandParser._next_weekday(3),
        'nächsten freitag': lambda: VoiceCommandParser._next_weekday(4),
        'nächsten samstag': lambda: VoiceCommandParser._next_weekday(5),
        'nächsten sonntag': lambda: VoiceCommandParser._next_weekday(6),
        'montag': lambda: VoiceCommandParser._next_weekday(0),
        'dienstag': lambda: VoiceCommandParser._next_weekday(1),
        'mittwoch': lambda: VoiceCommandParser._next_weekday(2),
        'donnerstag': lambda: VoiceCommandParser._next_weekday(3),
        'freitag': lambda: VoiceCommandParser._next_weekday(4),
        'samstag': lambda: VoiceCommandParser._next_weekday(5),
        'sonntag': lambda: VoiceCommandParser._next_weekday(6),
    }

    # Dauer-Ausdrücke
    DURATION_PATTERNS = [
        (r'(\d+)\s*(?:sekunden?|sek)', 'seconds'),
        (r'(\d+)\s*(?:minuten?|min)', 'minutes'),
        (r'(\d+)\s*(?:stunden?|std|h)', 'hours'),
        (r'(?:eine?|1)\s*(?:halbe?)\s*stunde', 'half_hour'),
        (r'(?:eine?|1)\s*(?:viertel)\s*stunde', 'quarter_hour'),
    ]

    # Priorität-Ausdrücke
    PRIORITY_KEYWORDS = {
        'urgent': ['dringend', 'wichtig', 'sofort', 'asap', 'eilig'],
        'high': ['hoch', 'priorität'],
        'low': ['niedrig', 'später', 'irgendwann'],
    }

    @staticmethod
    def _next_weekday(weekday: int) -> datetime:
        """Findet den nächsten Wochentag (0=Montag)"""
        today = datetime.now()
        days_ahead = weekday - today.weekday()
        if days_ahead <= 0:  # Zielwochentag bereits diese Woche vorbei
            days_ahead += 7
        return (today + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0, microsecond=0)

    def detect_command_type(self, text: str) -> Optional[str]:
        """Erkennt den Befehlstyp aus dem Text"""
        text_lower = text.lower()

        for cmd_type, patterns in self.COMMAND_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    return cmd_type

        return None

    def parse_time(self, text: str) -> Optional[datetime]:
        """Extrahiert Datum/Uhrzeit aus dem Text"""
        text_lower = text.lower()

        # Prüfe bekannte Zeitausdrücke
        for expr, time_func in self.TIME_EXPRESSIONS.items():
            if expr in text_lower:
                base_time = time_func()

                # Suche nach Uhrzeit
                time_match = re.search(r'(?:um\s+)?(\d{1,2})(?::(\d{2}))?\s*(?:uhr)?', text_lower)
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2)) if time_match.group(2) else 0
                    base_time = base_time.replace(hour=hour, minute=minute)

                return base_time

        # Versuche Datum zu parsen (z.B. "am 15.12." oder "15. Dezember")
        date_patterns = [
            r'(?:am\s+)?(\d{1,2})\.(\d{1,2})\.?(?:(\d{2,4}))?',  # 15.12. oder 15.12.2024
            r'(?:am\s+)?(\d{1,2})\.\s*(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)',
        ]

        month_names = {
            'januar': 1, 'februar': 2, 'märz': 3, 'april': 4,
            'mai': 5, 'juni': 6, 'juli': 7, 'august': 8,
            'september': 9, 'oktober': 10, 'november': 11, 'dezember': 12
        }

        for pattern in date_patterns:
            match = re.search(pattern, text_lower)
            if match:
                groups = match.groups()
                try:
                    day = int(groups[0])
                    if groups[1].isdigit():
                        month = int(groups[1])
                        year = int(groups[2]) if len(groups) > 2 and groups[2] else datetime.now().year
                        if year < 100:
                            year += 2000
                    else:
                        month = month_names.get(groups[1], 1)
                        year = datetime.now().year

                    parsed_date = datetime(year, month, day, 9, 0)

                    # Suche nach Uhrzeit
                    time_match = re.search(r'(?:um\s+)?(\d{1,2})(?::(\d{2}))?\s*(?:uhr)?', text_lower)
                    if time_match:
                        hour = int(time_match.group(1))
                        minute = int(time_match.group(2)) if time_match.group(2) else 0
                        parsed_date = parsed_date.replace(hour=hour, minute=minute)

                    return parsed_date
                except (ValueError, TypeError):
                    pass

        # Nur Uhrzeit (für heute)
        time_only = re.search(r'(?:um\s+)?(\d{1,2})(?::(\d{2}))?\s*uhr', text_lower)
        if time_only:
            hour = int(time_only.group(1))
            minute = int(time_only.group(2)) if time_only.group(2) else 0
            return datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)

        return None

    def parse_duration(self, text: str) -> Optional[int]:
        """Extrahiert eine Dauer in Sekunden aus dem Text"""
        text_lower = text.lower()

        for pattern, unit in self.DURATION_PATTERNS:
            match = re.search(pattern, text_lower)
            if match:
                if unit == 'half_hour':
                    return 30 * 60
                elif unit == 'quarter_hour':
                    return 15 * 60
                else:
                    value = int(match.group(1))
                    if unit == 'seconds':
                        return value
                    elif unit == 'minutes':
                        return value * 60
                    elif unit == 'hours':
                        return value * 3600

        return None

    def extract_title(self, text: str, command_type: str) -> str:
        """Extrahiert den Titel/Betreff aus dem Befehl"""
        text_clean = text

        # Entferne Befehlswörter
        remove_patterns = [
            r'(?:erstelle|lege|mach|plane|trage)\s*(?:einen?)?\s*(?:termin|meeting|besprechung|erinnerung|aufgabe|todo|wecker|timer)',
            r'(?:neuer?|neue)\s*(?:termin|meeting|besprechung|erinnerung|aufgabe|todo|wecker|timer)',
            r'erinner(?:e|ung)\s*(?:mich)?(?:\s*(?:an|daran))?',
            r'(?:stelle?|stell)\s*(?:einen?)?\s*(?:wecker|timer)',
            r'(?:weck|wecke)\s*mich',
            r'nicht\s*vergessen',
            r'(?:ich\s*muss|muss\s*noch)',
            r'(?:um|für|am|bis)\s+\d{1,2}(?::\d{2})?\s*(?:uhr)?',
            r'(?:morgen|heute|übermorgen|nächste\s*woche)',
            r'(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)',
            r'\d{1,2}\.\d{1,2}\.?(?:\d{2,4})?',
            r'(?:\d+)\s*(?:minuten?|sekunden?|stunden?)',
        ]

        for pattern in remove_patterns:
            text_clean = re.sub(pattern, '', text_clean, flags=re.IGNORECASE)

        # Bereinige Leerzeichen
        text_clean = re.sub(r'\s+', ' ', text_clean).strip()

        # Entferne führende Wörter wie "für", "an", "zum"
        text_clean = re.sub(r'^(?:für|an|zum|zur|dass?|mit)\s+', '', text_clean, flags=re.IGNORECASE)

        return text_clean.strip() if text_clean else f"Sprachbefehl vom {datetime.now().strftime('%d.%m.%Y %H:%M')}"

    def parse_priority(self, text: str) -> str:
        """Erkennt Priorität aus dem Text"""
        text_lower = text.lower()

        for priority, keywords in self.PRIORITY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return priority

        return 'medium'

    def parse_command(self, text: str) -> Dict[str, Any]:
        """
        Hauptmethode: Parst einen Sprachbefehl vollständig

        Returns:
            Dict mit:
            - command_type: calendar, reminder, alarm, timer, todo, oder None
            - title: Extrahierter Titel
            - datetime: Datum/Uhrzeit (wenn erkannt)
            - duration: Dauer in Sekunden (für Timer)
            - priority: Priorität (für Todos)
            - raw_text: Original-Text
        """
        command_type = self.detect_command_type(text)

        result = {
            'command_type': command_type,
            'title': self.extract_title(text, command_type) if command_type else text,
            'datetime': self.parse_time(text),
            'duration': self.parse_duration(text) if command_type == 'timer' else None,
            'priority': self.parse_priority(text) if command_type == 'todo' else None,
            'raw_text': text,
        }

        # Für Timer: Berechne Zielzeit aus Dauer
        if command_type == 'timer' and result['duration'] and not result['datetime']:
            result['datetime'] = datetime.now() + timedelta(seconds=result['duration'])

        return result


class VoiceCommandService:
    """Service für die Ausführung von Sprachbefehlen"""

    def __init__(self):
        self.parser = VoiceCommandParser()
        self.settings = get_settings()

    def execute_command(self, text: str, user_id: int) -> Dict[str, Any]:
        """
        Führt einen Sprachbefehl aus

        Args:
            text: Transkribierter Text
            user_id: Benutzer-ID

        Returns:
            Dict mit Ergebnis
        """
        from database.models import (
            get_session, CalendarEvent, EventType, Todo, TodoStatus, TodoPriority,
            Alarm, AlarmType, VoiceCommand as VoiceCommandModel
        )

        # Parse den Befehl
        parsed = self.parser.parse_command(text)

        session = get_session()
        result = {
            'success': False,
            'command_type': parsed['command_type'],
            'message': '',
            'entity_id': None,
            'entity_type': None,
        }

        try:
            # Protokolliere den Befehl
            voice_cmd = VoiceCommandModel(
                user_id=user_id,
                transcribed_text=text,
                command_type=parsed['command_type'],
                parsed_data=json.dumps(parsed, default=str),
            )
            session.add(voice_cmd)

            if parsed['command_type'] == 'calendar':
                result = self._create_calendar_event(session, parsed, user_id)

            elif parsed['command_type'] == 'reminder':
                result = self._create_reminder(session, parsed, user_id)

            elif parsed['command_type'] == 'alarm':
                result = self._create_alarm(session, parsed, user_id, AlarmType.ALARM)

            elif parsed['command_type'] == 'timer':
                result = self._create_alarm(session, parsed, user_id, AlarmType.TIMER)

            elif parsed['command_type'] == 'todo':
                result = self._create_todo(session, parsed, user_id)

            else:
                result['message'] = "Befehl nicht erkannt. Versuchen Sie: 'Erstelle einen Termin...', 'Erinnere mich...', 'Stelle einen Wecker...', 'Timer für...', oder 'Neue Aufgabe...'"

            # Update Voice Command Log
            voice_cmd.was_successful = result['success']
            voice_cmd.result_message = result['message']
            voice_cmd.created_entity_type = result.get('entity_type')
            voice_cmd.created_entity_id = result.get('entity_id')
            if not result['success']:
                voice_cmd.error_message = result.get('error')

            session.commit()

        except Exception as e:
            session.rollback()
            result['success'] = False
            result['error'] = str(e)
            result['message'] = f"Fehler bei der Ausführung: {str(e)}"
        finally:
            session.close()

        return result

    def _create_calendar_event(self, session, parsed: Dict, user_id: int) -> Dict:
        """Erstellt einen Kalendereintrag"""
        from database.models import CalendarEvent, EventType

        if not parsed['datetime']:
            parsed['datetime'] = datetime.now() + timedelta(days=1)
            parsed['datetime'] = parsed['datetime'].replace(hour=9, minute=0)

        event = CalendarEvent(
            user_id=user_id,
            title=parsed['title'],
            description=f"Erstellt per Sprachbefehl: {parsed['raw_text']}",
            event_type=EventType.APPOINTMENT,
            start_date=parsed['datetime'],
            end_date=parsed['datetime'] + timedelta(hours=1),
            all_day=False,
            reminder_days_before=1,
        )
        session.add(event)
        session.flush()

        return {
            'success': True,
            'message': f"✅ Termin '{parsed['title']}' am {parsed['datetime'].strftime('%d.%m.%Y um %H:%M')} Uhr erstellt",
            'entity_type': 'calendar_event',
            'entity_id': event.id,
        }

    def _create_reminder(self, session, parsed: Dict, user_id: int) -> Dict:
        """Erstellt eine Erinnerung"""
        from database.models import CalendarEvent, EventType

        if not parsed['datetime']:
            parsed['datetime'] = datetime.now() + timedelta(hours=1)

        event = CalendarEvent(
            user_id=user_id,
            title=f"⏰ {parsed['title']}",
            description=f"Erinnerung erstellt per Sprachbefehl: {parsed['raw_text']}",
            event_type=EventType.REMINDER,
            start_date=parsed['datetime'],
            all_day=False,
            reminder_days_before=0,
        )
        session.add(event)
        session.flush()

        return {
            'success': True,
            'message': f"✅ Erinnerung '{parsed['title']}' für {parsed['datetime'].strftime('%d.%m.%Y um %H:%M')} Uhr erstellt",
            'entity_type': 'calendar_event',
            'entity_id': event.id,
        }

    def _create_alarm(self, session, parsed: Dict, user_id: int, alarm_type) -> Dict:
        """Erstellt einen Wecker oder Timer"""
        from database.models import Alarm, AlarmType

        if not parsed['datetime']:
            if alarm_type == AlarmType.TIMER and parsed['duration']:
                parsed['datetime'] = datetime.now() + timedelta(seconds=parsed['duration'])
            else:
                # Standard: Morgen 7 Uhr
                parsed['datetime'] = (datetime.now() + timedelta(days=1)).replace(hour=7, minute=0, second=0)

        alarm = Alarm(
            user_id=user_id,
            alarm_type=alarm_type,
            title=parsed['title'] if parsed['title'] else (
                "Timer" if alarm_type == AlarmType.TIMER else "Wecker"
            ),
            message=f"Erstellt per Sprachbefehl: {parsed['raw_text']}",
            trigger_time=parsed['datetime'],
            duration_seconds=parsed['duration'],
            is_active=True,
            created_by_voice=True,
            original_voice_text=parsed['raw_text'],
        )
        session.add(alarm)
        session.flush()

        if alarm_type == AlarmType.TIMER:
            duration_str = self._format_duration(parsed['duration'])
            return {
                'success': True,
                'message': f"✅ Timer für {duration_str} gestartet (endet um {parsed['datetime'].strftime('%H:%M')} Uhr)",
                'entity_type': 'alarm',
                'entity_id': alarm.id,
            }
        else:
            return {
                'success': True,
                'message': f"✅ Wecker für {parsed['datetime'].strftime('%d.%m.%Y um %H:%M')} Uhr gestellt",
                'entity_type': 'alarm',
                'entity_id': alarm.id,
            }

    def _create_todo(self, session, parsed: Dict, user_id: int) -> Dict:
        """Erstellt eine Aufgabe"""
        from database.models import Todo, TodoStatus, TodoPriority

        priority_map = {
            'urgent': TodoPriority.URGENT,
            'high': TodoPriority.HIGH,
            'medium': TodoPriority.MEDIUM,
            'low': TodoPriority.LOW,
        }

        todo = Todo(
            user_id=user_id,
            title=parsed['title'],
            description=f"Erstellt per Sprachbefehl: {parsed['raw_text']}",
            status=TodoStatus.OPEN,
            priority=priority_map.get(parsed['priority'], TodoPriority.MEDIUM),
            due_date=parsed['datetime'],
            created_by_voice=True,
            original_voice_text=parsed['raw_text'],
        )
        session.add(todo)
        session.flush()

        due_str = f" (fällig: {parsed['datetime'].strftime('%d.%m.%Y')})" if parsed['datetime'] else ""
        return {
            'success': True,
            'message': f"✅ Aufgabe '{parsed['title']}'{due_str} erstellt",
            'entity_type': 'todo',
            'entity_id': todo.id,
        }

    def _format_duration(self, seconds: int) -> str:
        """Formatiert Sekunden zu lesbarem String"""
        if seconds < 60:
            return f"{seconds} Sekunden"
        elif seconds < 3600:
            mins = seconds // 60
            return f"{mins} Minute{'n' if mins != 1 else ''}"
        else:
            hours = seconds // 3600
            mins = (seconds % 3600) // 60
            if mins:
                return f"{hours} Stunde{'n' if hours != 1 else ''} {mins} Minute{'n' if mins != 1 else ''}"
            return f"{hours} Stunde{'n' if hours != 1 else ''}"

    def use_ai_parsing(self, text: str) -> Dict[str, Any]:
        """
        Verwendet KI für bessere Befehlserkennung (optional)

        Args:
            text: Transkribierter Text

        Returns:
            Geparster Befehl
        """
        if not self.settings.openai_api_key:
            return self.parser.parse_command(text)

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.settings.openai_api_key)

            prompt = f"""Analysiere den folgenden deutschen Sprachbefehl und extrahiere die Informationen.

Befehl: "{text}"

Antworte im JSON-Format:
{{
    "command_type": "calendar" | "reminder" | "alarm" | "timer" | "todo" | null,
    "title": "Extrahierter Titel/Betreff",
    "date": "YYYY-MM-DD" oder null,
    "time": "HH:MM" oder null,
    "duration_minutes": Zahl oder null (für Timer),
    "priority": "low" | "medium" | "high" | "urgent" oder null
}}

Nur JSON ausgeben, keine Erklärung."""

            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=200
            )

            content = response.choices[0].message.content
            if not content or not content.strip():
                return self.parser.parse_command(text)

            # JSON aus Antwort extrahieren (falls zusätzlicher Text vorhanden)
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                content = content[json_start:json_end]

            ai_result = json.loads(content)

            # Konvertiere zu unserem Format
            parsed_dt = None
            if ai_result.get('date'):
                try:
                    parsed_dt = datetime.strptime(ai_result['date'], '%Y-%m-%d')
                    if ai_result.get('time'):
                        time_parts = ai_result['time'].split(':')
                        parsed_dt = parsed_dt.replace(
                            hour=int(time_parts[0]),
                            minute=int(time_parts[1]) if len(time_parts) > 1 else 0
                        )
                except (ValueError, TypeError):
                    pass

            return {
                'command_type': ai_result.get('command_type'),
                'title': ai_result.get('title', text),
                'datetime': parsed_dt,
                'duration': ai_result.get('duration_minutes', 0) * 60 if ai_result.get('duration_minutes') else None,
                'priority': ai_result.get('priority'),
                'raw_text': text,
            }

        except Exception as e:
            # Fallback auf regelbasiertes Parsing
            return self.parser.parse_command(text)


def get_voice_command_service() -> VoiceCommandService:
    """Factory-Funktion für den VoiceCommandService"""
    return VoiceCommandService()
