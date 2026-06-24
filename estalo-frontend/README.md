# Estalo — Frontend

Interface web (React + Vite) que consome a API do Estalo.

## Pré-requisitos
- Node.js instalado (você já tem)
- O **backend rodando** em http://localhost:8000 (`uvicorn app.main:app --reload`)

## Como rodar

```bash
npm install        # só na primeira vez (baixa as dependências)
npm run dev        # sobe o frontend em http://localhost:5173
```

Abra http://localhost:5173 no navegador.

## Importante: backend e frontend rodam JUNTOS
São dois "motores" ligados ao mesmo tempo, em dois terminais:
- Terminal 1: o backend (`uvicorn ...`) na porta 8000
- Terminal 2: o frontend (`npm run dev`) na porta 5173

Se o backend estiver desligado, o login não funciona (o frontend não tem com quem falar).

## Estrutura
```
src/
├── main.jsx          # ponto de entrada do React
├── App.jsx           # o "porteiro": decide login ou painel
├── api.js            # único ponto de contato com o backend (anexa o crachá)
├── styles.css        # identidade visual
└── pages/
    ├── Auth.jsx      # login e cadastro
    └── Dashboard.jsx # lista de decks
```

## Próximos blocos
- Tela de árvore de pastas (os 4 níveis)
- Tela de estudo (o card vira, você dá a nota, o SM-2 roda)
- Geração de cards por IA na interface
