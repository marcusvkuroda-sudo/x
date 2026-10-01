"""Starts the app and prints the addresses to open on the computer and on the phones."""

import sys

# Checked before anything else: older Pythons (macOS ships 3.9) can't even import the app.
if sys.version_info < (3, 10):
    sys.exit(
        f"O Nossos Gastos precisa do Python 3.10 ou mais novo (este é o {sys.version.split()[0]}).\n"
        "Instale a versão mais recente em https://www.python.org/downloads/ e rode de novo."
    )

import os  # noqa: E402
import socket  # noqa: E402

try:
    import uvicorn

    from app import config
except ImportError as exc:
    sys.exit(
        f"Falta instalar dependências ({exc.name}). Rode o iniciar.sh / iniciar.bat "
        "ou: pip install -r requirements.txt"
    )


def lan_ip():
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
    print(f"  Neste computador:            http://localhost:{port}")
    if ip:
        print(f"  Nos celulares (mesma Wi-Fi): http://{ip}:{port}")
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("\n  Aviso: ANTHROPIC_API_KEY não configurada no .env; a leitura de faturas não vai funcionar.")
    if not config.APP_PASSWORD:
        print("  Dica: defina APP_PASSWORD no .env para pedir senha a quem abrir o app na rede.")
    print("  Para parar, feche esta janela ou aperte Ctrl+C.\n")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, log_level="warning")
