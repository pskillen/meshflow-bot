from abc import ABC

import requests


class BaseAPIWrapper(ABC):
    base_url: str
    auth_token: str | None

    def __init__(self, base_url: str, auth_token: str = None):
        self.base_url = base_url.rstrip('/')
        self.auth_token = auth_token

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
        response = requests.get(full_url, headers=self._get_headers())
        response.raise_for_status()

        return response

    def _post(self, url: str, json: dict) -> requests.Response:
        full_url = f"{self.base_url}/{url.lstrip('/')}"
        response = requests.post(full_url, json=json, headers=self._get_headers())
        response.raise_for_status()
        return response

    def _put(self, url: str, json: dict) -> requests.Response:
        full_url = f"{self.base_url}/{url.lstrip('/')}"
        response = requests.put(full_url, json=json, headers=self._get_headers())
        response.raise_for_status()
        return response
