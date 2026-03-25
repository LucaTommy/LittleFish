"""
Google Services integration layer for Little Fish.

Provides Gmail, Calendar, Drive, Docs, Sheets, Tasks, Contacts, and YouTube
access via Google APIs.  Every public function returns a plain string that
Fish can speak aloud.  Auth runs once (opens browser), then token auto-refreshes.
"""

import base64
import json
import os
import re
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths & scopes
# ---------------------------------------------------------------------------

CREDENTIALS_PATH = Path(os.environ.get("APPDATA", "")) / "LittleFish" / "google_credentials.json"
TOKEN_PATH = Path(os.environ.get("APPDATA", "")) / "LittleFish" / "google_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]

_NO_CREDS_MSG = (
    "Google not connected. Add credentials file to LittleFish folder."
)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def get_google_credentials():
    """Get valid credentials, refreshing or triggering OAuth flow if needed."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request

        if not CREDENTIALS_PATH.exists():
            print("[GOOGLE] No credentials file found at", CREDENTIALS_PATH)
            return None

        creds = None

        if TOKEN_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            except Exception as e:
                print(f"[GOOGLE] Failed to load token: {e}")
                creds = None

        if creds and creds.expired and creds.refresh_token:
            try:
                print("[GOOGLE] Refreshing expired token...")
                creds.refresh(Request())
            except Exception as e:
                print(f"[GOOGLE] Token refresh failed: {e}")
                creds = None

        if not creds or not creds.valid:
            print("[GOOGLE] Starting OAuth flow (opening browser)...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Persist token
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        print("[GOOGLE] Credentials ready.")
        return creds

    except Exception as e:
        print(f"[GOOGLE] Auth error: {e}")
        return None


def _build_service(api: str, version: str):
    """Build a Google API service object. Returns None on failure."""
    try:
        from googleapiclient.discovery import build as _build

        creds = get_google_credentials()
        if creds is None:
            return None
        return _build(api, version, credentials=creds)
    except Exception as e:
        print(f"[GOOGLE] Failed to build {api} service: {e}")
        return None


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

def gmail_get_unread(max_results: int = 10, groq_client=None) -> str:
    """Get unread emails. Optionally summarize with Groq if > 5."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("gmail", "v1")
        if not service:
            return _NO_CREDS_MSG

        results = service.users().messages().list(
            userId="me", q="is:unread", maxResults=max_results
        ).execute()
        messages = results.get("messages", [])

        if not messages:
            return "No unread emails."

        entries = []
        for msg in messages:
            m = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject"]
            ).execute()
            headers = {h["name"]: h["value"] for h in m.get("payload", {}).get("headers", [])}
            sender = headers.get("From", "Unknown")
            subject = headers.get("Subject", "(no subject)")
            # Extract just the name part from "Name <email>"
            sender_name = sender.split("<")[0].strip().strip('"') or sender
            snippet = m.get("snippet", "")[:100]
            entries.append(f"{sender_name} | {subject} | {snippet}")

        count = len(entries)

        if groq_client:
            try:
                listing = "\n".join(entries)
                resp = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": (
                            "Summarize these unread emails in 2-3 sentences max. "
                            "Be conversational and brief, like telling a friend. "
                            "Just mention the most important senders and topics. "
                            "Skip newsletters and notifications unless important."
                        )},
                        {"role": "user", "content": listing},
                    ],
                    max_tokens=200,
                    temperature=0.3,
                )
                summary = resp.choices[0].message.content.strip()
                return f"You have {count} unread emails. {summary}"
            except Exception as e:
                print(f"[GOOGLE] Groq summarization failed: {e}")

        # Fallback without Groq: brief listing
        brief = ". ".join(f"{e.split(' | ')[0]}: {e.split(' | ')[1]}" for e in entries)
        return f"You have {count} unread emails. {brief}"

    except Exception as e:
        print(f"[GOOGLE] gmail_get_unread error: {e}")
        return f"Couldn't check email: {e}"


def gmail_search(query: str, max_results: int = 5) -> str:
    """Search emails by query string."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("gmail", "v1")
        if not service:
            return _NO_CREDS_MSG

        results = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        messages = results.get("messages", [])

        if not messages:
            return f"No emails found for '{query}'."

        entries = []
        for msg in messages:
            m = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in m.get("payload", {}).get("headers", [])}
            sender = headers.get("From", "Unknown")
            subject = headers.get("Subject", "(no subject)")
            date = headers.get("Date", "")
            entries.append(f"{sender}: {subject} ({date})")

        return f"Found {len(entries)} emails. " + ". ".join(entries)

    except Exception as e:
        print(f"[GOOGLE] gmail_search error: {e}")
        return f"Email search failed: {e}"


def gmail_send(to: str, subject: str, body: str) -> str:
    """Send an email."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("gmail", "v1")
        if not service:
            return _NO_CREDS_MSG

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

        print(f"[GOOGLE] Email sent to {to}")
        return f"Sent email to {to} with subject {subject}"

    except Exception as e:
        print(f"[GOOGLE] gmail_send error: {e}")
        return f"Couldn't send email: {e}"


def gmail_draft_and_send(to: str, instructions: str, groq_client) -> str:
    """Use Groq to draft an email from instructions, then send it."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        if not groq_client:
            return "No AI client available to draft the email."

        resp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Draft a professional email based on the user's instructions. "
                        "Return ONLY valid JSON: {\"subject\": \"...\", \"body\": \"...\"} "
                        "No explanation, no markdown fences."
                    ),
                },
                {"role": "user", "content": f"To: {to}\nInstructions: {instructions}"},
            ],
            max_tokens=500,
            temperature=0.4,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]
        draft = json.loads(raw)
        subject = draft.get("subject", "No subject")
        body = draft.get("body", "")

        return gmail_send(to, subject, body)

    except Exception as e:
        print(f"[GOOGLE] gmail_draft_and_send error: {e}")
        return f"Couldn't draft and send email: {e}"


def gmail_mark_read(query: str) -> str:
    """Mark matching emails as read."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("gmail", "v1")
        if not service:
            return _NO_CREDS_MSG

        results = service.users().messages().list(
            userId="me", q=f"is:unread {query}", maxResults=50
        ).execute()
        messages = results.get("messages", [])

        if not messages:
            return f"No unread emails matching '{query}'."

        for msg in messages:
            service.users().messages().modify(
                userId="me", id=msg["id"],
                body={"removeLabelIds": ["UNREAD"]}
            ).execute()

        count = len(messages)
        print(f"[GOOGLE] Marked {count} emails as read")
        return f"Marked {count} emails as read."

    except Exception as e:
        print(f"[GOOGLE] gmail_mark_read error: {e}")
        return f"Couldn't mark emails as read: {e}"


def gmail_draft_reply(email_query: str, instructions: str, groq_client) -> str:
    """Find an email matching query, draft a reply with Groq, and send it."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        if not groq_client:
            return "I need Groq AI keys to draft replies. Add them in Settings."
        service = _build_service("gmail", "v1")
        if not service:
            return _NO_CREDS_MSG

        # Find the email
        results = service.users().messages().list(
            userId="me", q=email_query, maxResults=1
        ).execute()
        messages = results.get("messages", [])
        if not messages:
            return f"No email found matching '{email_query}'."

        m = service.users().messages().get(
            userId="me", id=messages[0]["id"], format="full"
        ).execute()
        headers = {h["name"]: h["value"] for h in m.get("payload", {}).get("headers", [])}
        sender = headers.get("From", "Unknown")
        subject = headers.get("Subject", "(no subject)")
        msg_id = headers.get("Message-ID", "")
        thread_id = m.get("threadId", "")

        # Extract body text
        body_text = m.get("snippet", "")
        payload = m.get("payload", {})
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    break
        if not parts and payload.get("body", {}).get("data"):
            body_text = base64.urlsafe_b64decode(
                payload["body"]["data"]
            ).decode("utf-8", errors="replace")

        # Draft reply with Groq
        resp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": (
                    "Draft a reply to this email. Be professional but natural. "
                    "Return ONLY the email body text, no subject line or greetings metadata."
                )},
                {"role": "user", "content": (
                    f"Instructions: {instructions}\n\n"
                    f"Original email from {sender}:\n"
                    f"Subject: {subject}\n"
                    f"Body: {body_text[:500]}"
                )},
            ],
            max_tokens=400,
            temperature=0.4,
        )
        reply_body = resp.choices[0].message.content.strip()

        # Build reply message
        reply_msg = MIMEText(reply_body)
        reply_msg["to"] = sender
        reply_msg["subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject
        if msg_id:
            reply_msg["In-Reply-To"] = msg_id
            reply_msg["References"] = msg_id
        raw = base64.urlsafe_b64encode(reply_msg.as_bytes()).decode()

        send_body = {"raw": raw}
        if thread_id:
            send_body["threadId"] = thread_id
        service.users().messages().send(userId="me", body=send_body).execute()

        sender_name = sender.split("<")[0].strip().strip('"') or sender
        print(f"[GOOGLE] Replied to {sender_name} about {subject}")
        return f"Replied to {sender_name} about '{subject}'."

    except Exception as e:
        print(f"[GOOGLE] gmail_draft_reply error: {e}")
        return f"Couldn't reply to email: {e}"


def gmail_weekly_digest(groq_client) -> str:
    """Get emails from last 7 days and create a summary digest."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        if not groq_client:
            return "I need Groq AI keys for the weekly digest. Add them in Settings."
        service = _build_service("gmail", "v1")
        if not service:
            return _NO_CREDS_MSG

        results = service.users().messages().list(
            userId="me", q="newer_than:7d", maxResults=20
        ).execute()
        messages = results.get("messages", [])

        if not messages:
            return "No emails from this week."

        entries = []
        for msg in messages:
            m = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in m.get("payload", {}).get("headers", [])}
            sender = headers.get("From", "Unknown").split("<")[0].strip().strip('"')
            subject = headers.get("Subject", "(no subject)")
            date = headers.get("Date", "")
            snippet = m.get("snippet", "")[:100]
            entries.append(f"{sender} | {subject} | {date} | {snippet}")

        listing = "\n".join(entries)
        resp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": (
                    "Give me a brief weekly email digest. "
                    "What were the main themes and important messages this week? "
                    "Be conversational, 3-4 sentences max."
                )},
                {"role": "user", "content": listing},
            ],
            max_tokens=250,
            temperature=0.3,
        )
        digest = resp.choices[0].message.content.strip()
        return f"Weekly digest from {len(messages)} emails: {digest}"

    except Exception as e:
        print(f"[GOOGLE] gmail_weekly_digest error: {e}")
        return f"Couldn't create weekly digest: {e}"


def gmail_mark_as_spam(sender_or_subject: str) -> str:
    """Find emails matching query and mark as spam."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("gmail", "v1")
        if not service:
            return _NO_CREDS_MSG

        results = service.users().messages().list(
            userId="me", q=sender_or_subject, maxResults=20
        ).execute()
        messages = results.get("messages", [])

        if not messages:
            return f"No emails found matching '{sender_or_subject}'."

        count = 0
        for msg in messages:
            service.users().messages().modify(
                userId="me", id=msg["id"],
                body={"addLabelIds": ["SPAM"], "removeLabelIds": ["INBOX"]}
            ).execute()
            count += 1

        print(f"[GOOGLE] Marked {count} emails as spam for '{sender_or_subject}'")
        return f"Marked {count} emails from '{sender_or_subject}' as spam."

    except Exception as e:
        print(f"[GOOGLE] gmail_mark_as_spam error: {e}")
        return f"Couldn't mark as spam: {e}"


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def _parse_datetime(date_str: str, time_str: str = "") -> Optional[datetime]:
    """Parse natural date/time strings into a datetime object."""
    from dateutil import parser as dateutil_parser

    combined = f"{date_str} {time_str}".strip()
    try:
        return dateutil_parser.parse(combined, fuzzy=True)
    except Exception:
        return None


def calendar_get_today() -> str:
    """Get today's calendar events."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("calendar", "v3")
        if not service:
            return _NO_CREDS_MSG

        now = datetime.utcnow()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat() + "Z"

        events_result = service.events().list(
            calendarId="primary",
            timeMin=start_of_day,
            timeMax=end_of_day,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = events_result.get("items", [])

        if not events:
            return "Nothing scheduled for today."

        lines = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date", ""))
            summary = event.get("summary", "(no title)")
            if "T" in start:
                time_part = start.split("T")[1][:5]
                lines.append(f"{time_part} {summary}")
            else:
                lines.append(f"All day: {summary}")

        return "Today you have: " + ", ".join(lines)

    except Exception as e:
        print(f"[GOOGLE] calendar_get_today error: {e}")
        return f"Couldn't check calendar: {e}"


def calendar_get_week() -> str:
    """Get events for the next 7 days, grouped by day."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("calendar", "v3")
        if not service:
            return _NO_CREDS_MSG

        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=7)).isoformat() + "Z"

        events_result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = events_result.get("items", [])

        if not events:
            return "Nothing scheduled for the next 7 days."

        days = {}
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date", ""))
            summary = event.get("summary", "(no title)")
            date_key = start[:10]
            if date_key not in days:
                days[date_key] = []
            if "T" in start:
                time_part = start.split("T")[1][:5]
                days[date_key].append(f"{time_part} {summary}")
            else:
                days[date_key].append(f"All day: {summary}")

        parts = []
        for date_key in sorted(days):
            day_label = date_key
            try:
                day_label = datetime.strptime(date_key, "%Y-%m-%d").strftime("%A %b %d")
            except ValueError:
                pass
            items = ", ".join(days[date_key])
            parts.append(f"{day_label}: {items}")

        return "This week: " + ". ".join(parts)

    except Exception as e:
        print(f"[GOOGLE] calendar_get_week error: {e}")
        return f"Couldn't check weekly calendar: {e}"


def calendar_create_event(
    title: str, date_str: str, time_str: str, duration_minutes: int = 60
) -> str:
    """Create a calendar event."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("calendar", "v3")
        if not service:
            return _NO_CREDS_MSG

        dt = _parse_datetime(date_str, time_str)
        if not dt:
            return f"Couldn't understand the date/time: {date_str} {time_str}"

        end_dt = dt + timedelta(minutes=duration_minutes)

        event = {
            "summary": title,
            "start": {"dateTime": dt.isoformat(), "timeZone": "local"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "local"},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()

        print(f"[GOOGLE] Created event: {title}")
        return (
            f"Created event '{title}' on {dt.strftime('%B %d')} "
            f"at {dt.strftime('%I:%M %p')} for {duration_minutes} minutes."
        )

    except Exception as e:
        print(f"[GOOGLE] calendar_create_event error: {e}")
        return f"Couldn't create event: {e}"


def calendar_check_free(date_str: str, time_str: str) -> str:
    """Check if user is free at a given date/time."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("calendar", "v3")
        if not service:
            return _NO_CREDS_MSG

        dt = _parse_datetime(date_str, time_str)
        if not dt:
            return f"Couldn't understand the date/time: {date_str} {time_str}"

        time_min = dt.isoformat() + "Z"
        time_max = (dt + timedelta(hours=1)).isoformat() + "Z"

        events_result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
        ).execute()
        events = events_result.get("items", [])

        time_label = dt.strftime("%I:%M %p on %B %d")
        if not events:
            return f"You are free at {time_label}."

        conflict = events[0].get("summary", "(no title)")
        return f"You have '{conflict}' at {time_label}."

    except Exception as e:
        print(f"[GOOGLE] calendar_check_free error: {e}")
        return f"Couldn't check availability: {e}"


# ---------------------------------------------------------------------------
# Drive
# ---------------------------------------------------------------------------

def drive_list_files(query: str = "", max_results: int = 10) -> str:
    """List files in Drive, optionally filtered by query."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("drive", "v3")
        if not service:
            return _NO_CREDS_MSG

        q = f"name contains '{query}'" if query else None
        results = service.files().list(
            q=q, pageSize=max_results,
            fields="files(id, name, mimeType, modifiedTime)"
        ).execute()
        files = results.get("files", [])

        if not files:
            return "No files found in Drive." if not query else f"No files matching '{query}'."

        entries = []
        for f in files:
            name = f["name"]
            mime = f.get("mimeType", "").split(".")[-1]
            entries.append(f"{name} ({mime})")

        return f"Found {len(entries)} files: " + ", ".join(entries)

    except Exception as e:
        print(f"[GOOGLE] drive_list_files error: {e}")
        return f"Couldn't list Drive files: {e}"


def drive_search_file(filename: str) -> str:
    """Search for a specific file by name."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("drive", "v3")
        if not service:
            return _NO_CREDS_MSG

        results = service.files().list(
            q=f"name contains '{filename}'",
            pageSize=5,
            fields="files(id, name, mimeType, modifiedTime, webViewLink)"
        ).execute()
        files = results.get("files", [])

        if not files:
            return f"No file named '{filename}' found in Drive."

        f = files[0]
        name = f["name"]
        mime = f.get("mimeType", "unknown").split(".")[-1]
        modified = f.get("modifiedTime", "unknown")[:10]
        link = f.get("webViewLink", "no link")
        return f"Found '{name}' ({mime}), last modified {modified}. Link: {link}"

    except Exception as e:
        print(f"[GOOGLE] drive_search_file error: {e}")
        return f"Couldn't search Drive: {e}"


# ---------------------------------------------------------------------------
# Docs
# ---------------------------------------------------------------------------

def docs_create(title: str, content: str) -> str:
    """Create a Google Doc with title and content."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        docs_service = _build_service("docs", "v1")
        drive_service = _build_service("drive", "v3")
        if not docs_service or not drive_service:
            return _NO_CREDS_MSG

        doc = docs_service.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]

        if content:
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={
                    "requests": [
                        {"insertText": {"location": {"index": 1}, "text": content}}
                    ]
                },
            ).execute()

        url = f"https://docs.google.com/document/d/{doc_id}/edit"
        print(f"[GOOGLE] Created doc: {title}")
        return f"Created document '{title}' in your Drive. Link: {url}"

    except Exception as e:
        print(f"[GOOGLE] docs_create error: {e}")
        return f"Couldn't create document: {e}"


def _find_doc_id(title_or_id: str) -> Optional[str]:
    """Resolve a title or ID to a Google Doc ID."""
    # If it looks like a doc ID already (long alphanumeric), use it directly
    if len(title_or_id) > 20 and " " not in title_or_id:
        return title_or_id

    try:
        drive_service = _build_service("drive", "v3")
        if not drive_service:
            return None
        results = drive_service.files().list(
            q=f"name='{title_or_id}' and mimeType='application/vnd.google-apps.document'",
            pageSize=1,
            fields="files(id)"
        ).execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None
    except Exception:
        return None


def docs_append(doc_id_or_title: str, content: str) -> str:
    """Append content to an existing Google Doc."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG

        doc_id = _find_doc_id(doc_id_or_title)
        if not doc_id:
            return f"Couldn't find document '{doc_id_or_title}'."

        docs_service = _build_service("docs", "v1")
        if not docs_service:
            return _NO_CREDS_MSG

        # Get document length to append at end
        doc = docs_service.documents().get(documentId=doc_id).execute()
        end_index = doc["body"]["content"][-1]["endIndex"] - 1

        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={
                "requests": [
                    {"insertText": {"location": {"index": end_index}, "text": "\n" + content}}
                ]
            },
        ).execute()

        print(f"[GOOGLE] Appended to doc: {doc_id_or_title}")
        return f"Appended content to '{doc_id_or_title}'."

    except Exception as e:
        print(f"[GOOGLE] docs_append error: {e}")
        return f"Couldn't append to document: {e}"


def docs_read(doc_id_or_title: str) -> str:
    """Read content from a Google Doc."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG

        doc_id = _find_doc_id(doc_id_or_title)
        if not doc_id:
            return f"Couldn't find document '{doc_id_or_title}'."

        docs_service = _build_service("docs", "v1")
        if not docs_service:
            return _NO_CREDS_MSG

        doc = docs_service.documents().get(documentId=doc_id).execute()
        title = doc.get("title", "Untitled")

        # Extract text from document body
        text_parts = []
        for element in doc.get("body", {}).get("content", []):
            if "paragraph" in element:
                for elem in element["paragraph"].get("elements", []):
                    run = elem.get("textRun")
                    if run:
                        text_parts.append(run.get("content", ""))

        full_text = "".join(text_parts).strip()

        if len(full_text) > 500:
            return f"Document '{title}': {full_text[:500]}..."
        return f"Document '{title}': {full_text}" if full_text else f"Document '{title}' is empty."

    except Exception as e:
        print(f"[GOOGLE] docs_read error: {e}")
        return f"Couldn't read document: {e}"


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------

def sheets_create(title: str, headers: list, rows: list) -> str:
    """Create a spreadsheet with headers and data rows."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("sheets", "v4")
        if not service:
            return _NO_CREDS_MSG

        spreadsheet = service.spreadsheets().create(
            body={"properties": {"title": title}}
        ).execute()
        sheet_id = spreadsheet["spreadsheetId"]

        # Write headers + rows
        values = [headers] + rows
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range="A1",
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()

        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
        print(f"[GOOGLE] Created spreadsheet: {title}")
        return f"Created spreadsheet '{title}'. Link: {url}"

    except Exception as e:
        print(f"[GOOGLE] sheets_create error: {e}")
        return f"Couldn't create spreadsheet: {e}"


def _find_sheet_id(title_or_id: str) -> Optional[str]:
    """Resolve a title or ID to a Google Sheet ID."""
    if len(title_or_id) > 20 and " " not in title_or_id:
        return title_or_id

    try:
        drive_service = _build_service("drive", "v3")
        if not drive_service:
            return None
        results = drive_service.files().list(
            q=f"name='{title_or_id}' and mimeType='application/vnd.google-apps.spreadsheet'",
            pageSize=1,
            fields="files(id)"
        ).execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None
    except Exception:
        return None


def sheets_read(sheet_id_or_title: str, range_str: str = "A1:Z100") -> str:
    """Read sheet data and return formatted table."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG

        sheet_id = _find_sheet_id(sheet_id_or_title)
        if not sheet_id:
            return f"Couldn't find spreadsheet '{sheet_id_or_title}'."

        service = _build_service("sheets", "v4")
        if not service:
            return _NO_CREDS_MSG

        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=range_str
        ).execute()
        values = result.get("values", [])

        if not values:
            return f"Spreadsheet '{sheet_id_or_title}' is empty."

        # Format as readable table
        lines = []
        for i, row in enumerate(values[:20]):  # Limit to 20 rows for speech
            lines.append(" | ".join(str(cell) for cell in row))

        total = len(values)
        text = ". ".join(lines)
        if total > 20:
            text += f". And {total - 20} more rows."

        return text

    except Exception as e:
        print(f"[GOOGLE] sheets_read error: {e}")
        return f"Couldn't read spreadsheet: {e}"


def sheets_append_row(sheet_id_or_title: str, row_data: list) -> str:
    """Append a row to a spreadsheet."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG

        sheet_id = _find_sheet_id(sheet_id_or_title)
        if not sheet_id:
            return f"Couldn't find spreadsheet '{sheet_id_or_title}'."

        service = _build_service("sheets", "v4")
        if not service:
            return _NO_CREDS_MSG

        service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range="A1",
            valueInputOption="USER_ENTERED",
            body={"values": [row_data]},
        ).execute()

        print(f"[GOOGLE] Appended row to {sheet_id_or_title}")
        return f"Added row to '{sheet_id_or_title}'."

    except Exception as e:
        print(f"[GOOGLE] sheets_append_row error: {e}")
        return f"Couldn't append to spreadsheet: {e}"


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def tasks_get_all() -> str:
    """Get all pending tasks from default task list."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("tasks", "v1")
        if not service:
            return _NO_CREDS_MSG

        # Get default task list
        tasklists = service.tasklists().list(maxResults=1).execute()
        lists = tasklists.get("items", [])
        if not lists:
            return "No task lists found."

        list_id = lists[0]["id"]
        results = service.tasks().list(
            tasklist=list_id, showCompleted=False, maxResults=50
        ).execute()
        tasks = results.get("items", [])

        if not tasks:
            return "No pending tasks."

        entries = []
        for i, task in enumerate(tasks, 1):
            title = task.get("title", "(untitled)")
            due = task.get("due", "")
            if due:
                due_date = due[:10]
                entries.append(f"{i}. {title} (due {due_date})")
            else:
                entries.append(f"{i}. {title}")

        return f"You have {len(entries)} tasks: " + ". ".join(entries)

    except Exception as e:
        print(f"[GOOGLE] tasks_get_all error: {e}")
        return f"Couldn't get tasks: {e}"


def tasks_add(title: str, due_date: str = "") -> str:
    """Add a task, optionally with a due date."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("tasks", "v1")
        if not service:
            return _NO_CREDS_MSG

        tasklists = service.tasklists().list(maxResults=1).execute()
        lists = tasklists.get("items", [])
        if not lists:
            return "No task lists found."

        list_id = lists[0]["id"]
        task_body = {"title": title}

        if due_date:
            dt = _parse_datetime(due_date)
            if dt:
                task_body["due"] = dt.strftime("%Y-%m-%dT00:00:00.000Z")

        service.tasks().insert(tasklist=list_id, body=task_body).execute()

        print(f"[GOOGLE] Added task: {title}")
        due_msg = f" due {due_date}" if due_date else ""
        return f"Added task '{title}'{due_msg}."

    except Exception as e:
        print(f"[GOOGLE] tasks_add error: {e}")
        return f"Couldn't add task: {e}"


def tasks_complete(title: str) -> str:
    """Mark a task as complete by title match."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("tasks", "v1")
        if not service:
            return _NO_CREDS_MSG

        tasklists = service.tasklists().list(maxResults=1).execute()
        lists = tasklists.get("items", [])
        if not lists:
            return "No task lists found."

        list_id = lists[0]["id"]
        results = service.tasks().list(
            tasklist=list_id, showCompleted=False, maxResults=100
        ).execute()
        tasks = results.get("items", [])

        title_lower = title.lower()
        for task in tasks:
            if title_lower in task.get("title", "").lower():
                task["status"] = "completed"
                service.tasks().update(
                    tasklist=list_id, task=task["id"], body=task
                ).execute()
                print(f"[GOOGLE] Completed task: {task['title']}")
                return f"Marked '{task['title']}' as complete."

        return f"No pending task matching '{title}'."

    except Exception as e:
        print(f"[GOOGLE] tasks_complete error: {e}")
        return f"Couldn't complete task: {e}"


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

def contacts_find(name: str) -> str:
    """Search contacts by name."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("people", "v1")
        if not service:
            return _NO_CREDS_MSG

        results = service.people().searchContacts(
            query=name,
            readMask="names,emailAddresses,phoneNumbers",
            pageSize=5,
        ).execute()
        contacts = results.get("results", [])

        if not contacts:
            return f"No contacts found matching '{name}'."

        entries = []
        for contact in contacts:
            person = contact.get("person", {})
            names = person.get("names", [])
            emails = person.get("emailAddresses", [])
            phones = person.get("phoneNumbers", [])

            display_name = names[0]["displayName"] if names else "Unknown"
            email = emails[0]["value"] if emails else "no email"
            phone = phones[0]["value"] if phones else "no phone"
            entries.append(f"{display_name}: {email}, {phone}")

        return "Found: " + ". ".join(entries)

    except Exception as e:
        print(f"[GOOGLE] contacts_find error: {e}")
        return f"Couldn't search contacts: {e}"


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------

def youtube_search(query: str, max_results: int = 5) -> str:
    """Search YouTube and return results."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("youtube", "v3")
        if not service:
            return _NO_CREDS_MSG

        results = service.search().list(
            q=query,
            part="snippet",
            type="video",
            maxResults=max_results,
        ).execute()
        items = results.get("items", [])

        if not items:
            return f"No YouTube results for '{query}'."

        entries = []
        for item in items:
            snippet = item["snippet"]
            title = snippet["title"]
            channel = snippet["channelTitle"]
            video_id = item["id"]["videoId"]
            url = f"https://youtube.com/watch?v={video_id}"
            entries.append(f"{title} by {channel}: {url}")

        return f"Found {len(entries)} videos. " + ". ".join(entries)

    except Exception as e:
        print(f"[GOOGLE] youtube_search error: {e}")
        return f"YouTube search failed: {e}"


def youtube_get_info(url: str) -> str:
    """Get video info from a YouTube URL."""
    try:
        if not CREDENTIALS_PATH.exists():
            return _NO_CREDS_MSG
        service = _build_service("youtube", "v3")
        if not service:
            return _NO_CREDS_MSG

        # Extract video ID from URL
        video_id = None
        patterns = [
            r"v=([a-zA-Z0-9_-]{11})",
            r"youtu\.be/([a-zA-Z0-9_-]{11})",
            r"embed/([a-zA-Z0-9_-]{11})",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                break

        if not video_id:
            return "Couldn't extract video ID from that URL."

        result = service.videos().list(
            part="snippet,contentDetails",
            id=video_id,
        ).execute()
        items = result.get("items", [])

        if not items:
            return "Video not found."

        video = items[0]
        snippet = video["snippet"]
        title = snippet["title"]
        channel = snippet["channelTitle"]
        description = snippet.get("description", "")[:200]
        duration = video.get("contentDetails", {}).get("duration", "")

        # Parse ISO 8601 duration (PT1H2M3S)
        dur_match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
        if dur_match:
            h = int(dur_match.group(1) or 0)
            m = int(dur_match.group(2) or 0)
            s = int(dur_match.group(3) or 0)
            parts = []
            if h:
                parts.append(f"{h}h")
            if m:
                parts.append(f"{m}m")
            if s:
                parts.append(f"{s}s")
            duration = " ".join(parts)

        return f"'{title}' by {channel}, {duration}. {description}"

    except Exception as e:
        print(f"[GOOGLE] youtube_get_info error: {e}")
        return f"Couldn't get video info: {e}"


# ---------------------------------------------------------------------------
# Connection status
# ---------------------------------------------------------------------------

def google_connection_status() -> dict:
    """Return connection status dict for launcher UI."""
    try:
        if not CREDENTIALS_PATH.exists():
            return {"connected": False, "email": "", "token_valid": False}

        from google.oauth2.credentials import Credentials

        if not TOKEN_PATH.exists():
            return {"connected": False, "email": "", "token_valid": False}

        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        valid = creds.valid and not creds.expired

        email = ""
        if valid:
            try:
                service = _build_service("gmail", "v1")
                if service:
                    profile = service.users().getProfile(userId="me").execute()
                    email = profile.get("emailAddress", "")
            except Exception:
                pass

        return {"connected": valid, "email": email, "token_valid": valid}

    except Exception as e:
        print(f"[GOOGLE] connection_status error: {e}")
        return {"connected": False, "email": "", "token_valid": False}
