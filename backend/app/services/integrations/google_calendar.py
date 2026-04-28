import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.utils.kms import decrypt


@dataclass
class GCalEventInput:
    summary: str
    starts_at: datetime
    ends_at: datetime
    description: str = ""
    location: str = ""
    color_id: str = "1"


@dataclass
class GCalEventResult:
    gcal_event_id: str
    gcal_html_link: str
    gcal_updated: str


class GCalClientProtocol(Protocol):
    async def insert_event(
        self, calendar_id: str, event: GCalEventInput
    ) -> GCalEventResult: ...

    async def update_event(
        self, calendar_id: str, gcal_event_id: str, event: GCalEventInput
    ) -> GCalEventResult: ...

    async def delete_event(
        self, calendar_id: str, gcal_event_id: str
    ) -> None: ...


class GoogleCalendarClient:
    """真實 GCal API client，每個 user 一個 instance。"""

    def __init__(
        self,
        refresh_token_enc: bytes,
        client_id: str,
        client_secret: str,
    ):
        self._refresh_token_enc = refresh_token_enc
        self._client_id = client_id
        self._client_secret = client_secret
        self._credentials = None

    def _get_credentials(self):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GoogleRequest

        if self._credentials and self._credentials.valid:
            return self._credentials

        refresh_token = decrypt(self._refresh_token_enc).decode("utf-8")
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=self._client_id,
            client_secret=self._client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )
        creds.refresh(GoogleRequest())
        self._credentials = creds
        return creds

    def _build_service(self):
        from googleapiclient.discovery import build
        return build("calendar", "v3", credentials=self._get_credentials())

    def _format_event(self, event: GCalEventInput) -> dict:
        return {
            "summary": event.summary,
            "description": event.description,
            "location": event.location,
            "colorId": event.color_id,
            "start": {
                "dateTime": event.starts_at.isoformat(),
                "timeZone": str(event.starts_at.tzinfo),
            },
            "end": {
                "dateTime": event.ends_at.isoformat(),
                "timeZone": str(event.ends_at.tzinfo),
            },
        }

    async def insert_event(
        self, calendar_id: str, event: GCalEventInput
    ) -> GCalEventResult:
        def _insert():
            service = self._build_service()
            return service.events().insert(
                calendarId=calendar_id,
                body=self._format_event(event),
            ).execute()

        result = await asyncio.get_event_loop().run_in_executor(None, _insert)
        return GCalEventResult(
            gcal_event_id=result["id"],
            gcal_html_link=result.get("htmlLink", ""),
            gcal_updated=result.get("updated", ""),
        )

    async def update_event(
        self, calendar_id: str, gcal_event_id: str, event: GCalEventInput
    ) -> GCalEventResult:
        def _update():
            service = self._build_service()
            return service.events().update(
                calendarId=calendar_id,
                eventId=gcal_event_id,
                body=self._format_event(event),
            ).execute()

        result = await asyncio.get_event_loop().run_in_executor(None, _update)
        return GCalEventResult(
            gcal_event_id=result["id"],
            gcal_html_link=result.get("htmlLink", ""),
            gcal_updated=result.get("updated", ""),
        )

    async def delete_event(
        self, calendar_id: str, gcal_event_id: str
    ) -> None:
        def _delete():
            service = self._build_service()
            service.events().delete(
                calendarId=calendar_id,
                eventId=gcal_event_id,
            ).execute()

        await asyncio.get_event_loop().run_in_executor(None, _delete)


def build_gcal_client(refresh_token_enc: bytes) -> GoogleCalendarClient:
    from app.config import settings
    return GoogleCalendarClient(
        refresh_token_enc=refresh_token_enc,
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
    )


class MockGCalClient:
    """測試用 mock，記錄所有呼叫，不發 HTTP。"""

    def __init__(self):
        self.inserted: list[tuple[str, GCalEventInput]] = []
        self.updated: list[tuple[str, str, GCalEventInput]] = []
        self.deleted: list[tuple[str, str]] = []
        self._event_counter = 0

    async def insert_event(
        self, calendar_id: str, event: GCalEventInput
    ) -> GCalEventResult:
        self.inserted.append((calendar_id, event))
        self._event_counter += 1
        return GCalEventResult(
            gcal_event_id=f"mock_gcal_id_{self._event_counter}",
            gcal_html_link=f"https://calendar.google.com/mock/{self._event_counter}",
            gcal_updated="2026-04-21T00:00:00Z",
        )

    async def update_event(
        self, calendar_id: str, gcal_event_id: str, event: GCalEventInput
    ) -> GCalEventResult:
        self.updated.append((calendar_id, gcal_event_id, event))
        return GCalEventResult(
            gcal_event_id=gcal_event_id,
            gcal_html_link=f"https://calendar.google.com/mock/{gcal_event_id}",
            gcal_updated="2026-04-21T00:00:00Z",
        )

    async def delete_event(self, calendar_id: str, gcal_event_id: str) -> None:
        self.deleted.append((calendar_id, gcal_event_id))
