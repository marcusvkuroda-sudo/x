"""Guesses a category and a clean merchant name from the text printed on a statement.

Used by the free local reader (no AI). The category memory in rules.py still wins:
whatever the couple corrects is remembered and applied on top of these guesses.
"""

import re

from .rules import normalize

KEYWORDS = {
    "outros": ["iof", "anuidade", "tarifa", "juros", "multa", "encargos", "encargo", "seguro fatura", "petz", "cobasi", "petshop",
               "pet shop", "veterinaria", "veterinario"],
    "assinaturas": ["netflix", "spotify", "disney", "hbo", "hbomax", "prime video", "amazon prime", "amazonprime", "globoplay", "deezer",
                    "youtube", "google one", "google storage", "icloud", "apple com bill", "microsoft", "xbox", "playstation", "steam",
                    "chatgpt", "openai", "claude ai", "anthropic", "adobe", "canva", "dropbox", "paramount", "crunchyroll", "audible",
                    "kindle", "udemy", "coursera", "alura", "duolingo", "mubi", "twitch", "patreon", "linkedin", "tinder"],
    "restaurantes": ["ifood", "ifd", "rappi", "ze delivery", "zedelivery", "restaurante", "lanchonete", "pizzaria", "pizza", "burger",
                     "hamburgueria", "mcdonalds", "mc donalds", "burger king", "subway", "outback", "starbucks", "cafe", "cafeteria",
                     "padoca", "bar", "boteco", "choperia", "churrascaria", "sushi", "temaki", "habibs", "giraffas", "madero",
                     "coco bambu", "spoleto", "china in box", "doceria", "sorveteria", "acai", "bobs", "kfc", "popeyes", "pastelaria"],
    "mercado": ["supermercado", "supermercados", "mercado", "mercadinho", "carrefour", "pao de acucar", "extra", "assai", "atacadao",
                "atacadista", "sams club", "hortifruti", "hortifrut", "sacolao", "acougue", "padaria", "panificadora", "oba hortifruti",
                "st marche", "mambo", "zaffari", "angeloni", "savegnago", "guanabara", "prezunic", "condor", "muffato", "bretas", "comper",
                "nordestao", "makro", "fort atacadista", "dia supermercado", "minuto pa", "hirota", "emporio"],
    "transporte": ["uber", "cabify", "indrive", "taxi", "posto", "shell", "ipiranga", "petrobras", "br mania", "combustivel",
                   "combustiveis", "auto posto", "estacionamento", "estapar", "zona azul", "sem parar", "semparar", "conectcar", "veloe",
                   "pedagio", "metro", "cptm", "bilhete unico", "sptrans", "riocard", "localiza", "movida", "unidas", "detran", "ipva",
                   "auto pecas", "autopecas", "oficina", "pneus", "lava rapido", "buser", "clickbus"],
    "saude": ["drogasil", "droga raia", "drogaraia", "raia", "drogaria", "drogarias", "farmacia", "pague menos", "panvel", "ultrafarma",
              "pacheco", "hospital", "clinica", "laboratorio", "fleury", "lavoisier", "unimed", "amil", "sulamerica", "hapvida", "odonto",
              "odontologia", "dentista", "smart fit", "smartfit", "bluefit", "academia", "gympass", "wellhub", "totalpass", "psicologia",
              "terapia", "salao", "barbearia", "estetica", "natura", "boticario", "sephora", "otica"],
    "casa": ["aluguel", "condominio", "enel", "eletropaulo", "light", "cemig", "copel", "celesc", "coelba", "cpfl", "energisa",
             "equatorial", "sabesp", "cedae", "copasa", "sanepar", "comgas", "naturgy", "ultragaz", "liquigas", "vivo", "claro", "tim",
             "oi", "net", "internet", "iptu", "leroy merlin", "telhanorte", "tok stok", "tokstok", "etna", "camicado", "mobly",
             "madeiramadeira", "casas bahia", "ponto frio", "magazine luiza", "magalu", "eletrodomesticos"],
    "lazer": ["cinema", "cinemark", "kinoplex", "ingresso", "ingressos", "sympla", "eventim", "ticketmaster", "teatro", "show", "parque",
              "airbnb", "booking", "hotel", "hoteis", "pousada", "decolar", "latam", "gol", "azul", "voegol", "voeazul", "hurb", "cvc",
              "viagem", "viagens", "turismo", "museu", "clube", "bilheteria", "livraria", "saraiva", "hostel", "resort"],
    "compras": ["amazon", "amzn", "mercado livre", "mercadolivre", "mercado pago", "mercadopago", "shopee", "aliexpress", "shein",
                "renner", "riachuelo", "cea", "zara", "hering", "centauro", "netshoes", "decathlon", "americanas", "submarino",
                "fast shop", "kabum", "apple store", "samsung", "loja", "lojas", "shopping", "havaianas", "arezzo", "nike", "adidas",
                "marisa", "pernambucanas", "temu"],
}

# Words this short only count as whole words ("dia" must not match "diaria").
_SHORT = 4
_PREPARED = [(category, normalize(w)) for category, words in KEYWORDS.items() for w in words if normalize(w)]

# The 99 ride app is mostly digits, which normalization drops.
_RAW_RULES = [(re.compile(r"\b99\s*(app|pop|taxi|tecnologia|food)", re.IGNORECASE), "transporte")]

# Payment processors print a prefix before the real merchant name.
_PREFIXES = re.compile(r"^(ifd|pg|pag|mp|ec|ppro|pagseguro|pagbank|ebanx|dl|sumup|iz|pp|ame|picpay)\s*\*\s*", re.IGNORECASE)

_CONNECTORS = {"de", "da", "do", "das", "dos", "e", "em", "na", "no"}

_BRANDS = [
    ("ifd", "iFood"), ("ifood", "iFood"), ("uber", "Uber"), ("netflix", "Netflix"), ("spotify", "Spotify"),
    ("amazon prime", "Amazon Prime"), ("amazonprime", "Amazon Prime"), ("amazon", "Amazon"), ("amzn", "Amazon"),
    ("mercadolivre", "Mercado Livre"), ("mercado livre", "Mercado Livre"), ("shopee", "Shopee"), ("rappi", "Rappi"),
    ("airbnb", "Airbnb"), ("apple com bill", "Apple"), ("google", "Google"),
]


def guess_category(text: str) -> str:
    for pattern, category in _RAW_RULES:
        if pattern.search(text or ""):
            return category
    words = normalize(text).split()
    padded = " " + " ".join(words) + " "
    best, best_len = "outros", 0
    for category, word in _PREPARED:
        needle = f" {word} " if len(word) <= _SHORT else f" {word}"
        if needle in padded and len(word) > best_len:
            best, best_len = category, len(word)
    return best


def clean_merchant(description: str) -> str:
    """'IFD*PIZZARIA BELLA' -> 'iFood - Pizzaria Bella', 'UBER *TRIP' -> 'Uber'."""
    text = re.sub(r"\s+", " ", description).strip()
    text = re.sub(r"\s*(parc(ela)?\.?\s*)?\d{1,2}\s*(/|de)\s*\d{1,2}\s*$", "", text, flags=re.IGNORECASE).strip()
    key = normalize(text)
    for brand_key, brand in _BRANDS:
        if key == brand_key or key.startswith(brand_key + " "):
            if brand == "iFood":
                rest = re.sub(r"^(ifd|ifood)\s*\*?\s*", "", text, flags=re.IGNORECASE).strip(" *-")
                return f"iFood - {rest.title()}" if rest else "iFood"
            return brand
    text = _PREFIXES.sub("", text).strip(" *-")
    text = re.sub(r"(\s+[\d\-/.]+)+$", "", text) or text  # store codes: "DROGASIL 0451"
    if not (text.isupper() or text.islower()):
        return text
    words = text.title().split(" ")
    # "PAO DE ACUCAR" -> "Pao de Acucar"
    return " ".join(w.lower() if i and w.lower() in _CONNECTORS else w for i, w in enumerate(words))
