from __future__ import annotations

import requests

BASE_URL = "https://friskissvettis.brpsystems.com/brponline/api/ver3"
TIMEOUT = 15


class BRPClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"
        self.auth = None

    def login(self, username: str, password: str) -> dict:
        resp = self.session.post(
            f"{BASE_URL}/auth/login",
            json={"username": username, "password": password},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        self.auth = resp.json()
        self.session.headers["Authorization"] = (
            f"{self.auth['token_type']} {self.auth['access_token']}"
        )
        return self.auth

    def get_business_units(self) -> list[dict]:
        resp = self.session.get(f"{BASE_URL}/businessunits", timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def get_business_unit_id(self, name: str) -> int | None:
        for unit in self.get_business_units():
            if name.lower() in unit.get("name", "").lower():
                return unit["id"]
        return None

    def get_group_activities(
        self, business_unit_id: int, start: str, end: str
    ) -> list[dict]:
        # API kräver fullständiga ISO-datetimes med .000Z
        if len(start) == 10:
            start = f"{start}T00:00:00.000Z"
        if len(end) == 10:
            end = f"{end}T23:59:59.000Z"
        resp = self.session.get(
            f"{BASE_URL}/businessunits/{business_unit_id}/groupactivities",
            params={"period.start": start, "period.end": end},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def get_bookings(self) -> list[dict]:
        if not self.auth:
            raise RuntimeError("Not logged in")
        username = self.auth["username"]
        resp = self.session.get(
            f"{BASE_URL}/customers/{username}/bookings/groupactivities",
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def book_activity(self, activity_id: int) -> dict:
        if not self.auth:
            raise RuntimeError("Not logged in")
        username = self.auth["username"]
        resp = self.session.post(
            f"{BASE_URL}/customers/{username}/bookings/groupactivities",
            json={"groupActivity": activity_id, "allowWaitingList": True},
            timeout=TIMEOUT,
        )
        if not resp.ok:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise RuntimeError(f"{resp.status_code}: {detail}")
        return resp.json()
