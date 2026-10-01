"""Starts the app and prints the addresses to open on the computer and on the phones."""

import os
import socket

import uvicorn

from app import config  # noqa: F401  (loads .env)


def lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    ip = lan_ip()
    print("\n  Nossos Gastos está rodando!")
    print(f"  Neste computador:   http://localhost:{port}")
    if ip:
        print(f"  Nos celulares (mesma Wi-Fi): http://{ip}:{port}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\n  Aviso: ANTHROPIC_API_KEY não configurada; a leitura de faturas não vai funcionar.")
    print()
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, log_level="warning")
