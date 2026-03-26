from abc import ABC

import requests


class BaseAPIWrapper(ABC):
    base_url: str
    auth_token: str | None
    session: requests.Session

    def __init__(self, base_url: str, auth_token: str = None):
        self.base_url = base_url.rstrip('/')
        self.auth_token = auth_token
        self.session = requests.Session()

    def _get_headers(self) -> dict:
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        if self.auth_token:
            headers['Authorization'] = f'Token {self.auth_token}'

        return headers

    def _get(self, url: str) -> requests.Response:
        full_url = f"{self.base_url}/{url.lstrip('/')}"
        response = self.session.get(full_url, headers=self._get_headers())
        response.raise_for_status()

        return response

    def _post(self, url: str, json: dict) -> requests.Response:
        full_url = f"{self.base_url}/{url.lstrip('/')}"
        response = self.session.post(full_url, json=json, headers=self._get_headers())
        response.raise_for_status()
        return response
