from __future__ import annotations

import requests

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from integrations.base import IntegrationBase

import pandas as pd
import requests


@dataclass
class AlvoAlert:
    timestamp: str
    message: str
    type: str
    data: dict | None = None

    def to_public(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "type": self.type,
            "message": self.message,
            "data": self.data or {},
        }


class AlvoPusher(IntegrationBase):
    name = "alvo_push"

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret

    def client(self) -> tuple[str, str]:
        return self.app_id, self.app_secret

    def publish(self, alert: AlvoAlert) -> str:
        app_id, app_secret = self.client()
        token_url = f"https://graph.facebook.com/v21.0/oauth/access_token?client_id={app_id}&client_secret={app_secret}&grant_type=client_credentials"
        token_resp = requests.get(token_url, timeout=20)
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]
        payload = alert.to_public()
        send_url = "https://graph.facebook.com/v21.0/me/messages"
        result = requests.post(
            send_url,
            params={"access_token": access_token},
            json={"message": payload},
            timeout=20,
        )
        result.raise_for_status()
        body = result.json()
        return str(body.get("message_id") or body.get("id") or body)
