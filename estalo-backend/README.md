# Estalo — Backend

App de flashcards com IA, repetição espaçada (SM-2) e hierarquia de até 4 níveis.

## Como rodar (local, sem instalar PostgreSQL)

```bash
# 1. Crie e ative um ambiente virtual
python -m venv .venv
source .venv/bin/activate        # Linux/Mac
# .venv\Scripts\activate         # Windows

# 2. Instale as dependências
pip install -r requirements.txt

# 3. (Opcional) Veja o esqueleto funcionando — monta a árvore e roda o SM-2
python sanity_check.py

# 4. Suba a API
uvicorn app.main:app --reload
```

Abra http://localhost:8000/docs — é a documentação interativa que o FastAPI gera sozinho.

## Estrutura

```
app/
├── core/
│   ├── config.py      # configurações (URL do banco, chave secreta, profundidade máx.)
│   └── database.py    # conexão e sessão do banco
├── models/            # as tabelas
│   ├── user.py        # usuários (multi-usuário desde o começo)
│   ├── folder.py      # pastas em árvore (4 níveis) ← dor #3
│   ├── deck.py        # conjuntos de cards
│   ├── card.py        # frente/verso + origem (manual ou IA) ← dor #1
│   └── review.py      # progresso SM-2, separado por usuário ← dor #2
├── services/
│   └── sm2.py         # algoritmo de repetição espaçada
└── main.py            # ponto de entrada da API
```

## Próximos passos
1. Endpoints de cadastro/login (auth com JWT)
2. CRUD de pastas, decks e cards
3. Rota de estudo (puxa cards vencidos e aplica o SM-2)
4. Camada de IA pra gerar cards a partir de texto
```
