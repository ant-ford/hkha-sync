import requests
from src.config.settings import LOGIN_URL


def login(username: str, password: str):
    session = requests.Session()

    response = session.post(
        LOGIN_URL,
        data={
            'username': username,
            'password': password,
            'login': 'login'
        },
        timeout=30
    )

    response.raise_for_status()
    return session
