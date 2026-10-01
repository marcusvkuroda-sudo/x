"""Fixed category set shared by the extractor, the API and the dashboard.

The order matters: it is the order the dashboard stacks and colors series in,
so each category keeps the same color everywhere.
"""

CATEGORIES = [
    {
        "key": "mercado",
        "label": "Mercado",
        "icon": "🛒",
        "hint": "supermercado, hortifruti, padaria, açougue, atacarejo, itens de casa comprados no mercado",
    },
    {
        "key": "restaurantes",
        "label": "Restaurantes & delivery",
        "icon": "🍽️",
        "hint": "restaurantes, bares, cafés, lanchonetes, iFood, Rappi, Zé Delivery",
    },
    {
        "key": "transporte",
        "label": "Transporte",
        "icon": "🚗",
        "hint": "Uber, 99, combustível, estacionamento, pedágio, Sem Parar, transporte público, manutenção do carro, IPVA",
    },
    {
        "key": "casa",
        "label": "Casa & contas",
        "icon": "🏠",
        "hint": "aluguel, condomínio, luz, água, gás, internet, celular, IPTU, móveis, reformas, utensílios",
    },
    {
        "key": "lazer",
        "label": "Lazer & viagens",
        "icon": "🎉",
        "hint": "cinema, shows, ingressos, passeios, hotéis, Airbnb, passagens aéreas, viagens",
    },
    {
        "key": "saude",
        "label": "Saúde & bem-estar",
        "icon": "💊",
        "hint": "farmácia, consultas, exames, plano de saúde, academia, terapia, cuidados pessoais, salão",
    },
    {
        "key": "compras",
        "label": "Compras",
        "icon": "🛍️",
        "hint": "roupas, eletrônicos, Amazon, Mercado Livre, Shopee, lojas em geral, presentes",
    },
    {
        "key": "assinaturas",
        "label": "Assinaturas & serviços",
        "icon": "📺",
        "hint": "Netflix, Spotify, streaming, apps, software, cursos, educação, serviços recorrentes",
    },
    {
        "key": "outros",
        "label": "Outros",
        "icon": "📦",
        "hint": "pets, tarifas, anuidade, IOF, juros, encargos e tudo o que não se encaixar nas demais",
    },
]

CATEGORY_KEYS = [c["key"] for c in CATEGORIES]
DEFAULT_CATEGORY = "outros"
