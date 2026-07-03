# Estalo — Estado atual (pós sessão de escalabilidade e performance)

> Gerado em 2026-07-03 como "fonte da verdade" pra encerrar a sessão de
> performance/escalabilidade. Uma conversa nova pode partir só deste
> arquivo, sem precisar carregar o histórico completo.

---

## 1. Resumo da arquitetura — 6 pontos críticos resolvidos

Levantados em `docs/pontos_criticos_performance.md` (não versionado no
git, fica só localmente) e resolvidos nesta ordem:

1. **N+1 explosivo em `_memorization_pct`** — `GET /decks` fazia uma query
   de `Review` por card (~200 queries num deck real). Trocado por bulk
   query com `outerjoin` + `IN()`, igual ao padrão que já existia em
   `/study/decks/{id}/stats`.
2. **Frontend: 1 request de stats por deck** — `statsMultiplos()` disparava
   um `GET /study/decks/{id}/stats` por deck em paralelo (27 decks = 27
   requests). Endpoint novo `GET /study/decks/stats?ids=...` calcula tudo
   em queries de quantidade fixa, numa chamada só.
3. **Zero índices nas colunas mais consultadas** — `Card.deck_id`,
   `Deck.owner_id` e `ReviewHistory(user_id, avaliado_em)` sem índice.
   Adicionados via `index=True` nos models + `CREATE INDEX IF NOT EXISTS`
   em `_migrar()` (`main.py`), pra cobrir bancos que já existem (sem
   Alembic no projeto).
4. **`get_current_user` com SELECT em toda request** — o JWT já carrega o
   `user_id` validado por assinatura; nova dependência leve
   `get_current_user_id` decodifica o token sem tocar o banco. Usada em
   quase todos os endpoints; `get_current_user` (com o SELECT completo)
   ficou só em `GET /auth/me`.
5. **Cold start pesado (`create_all` + `_migrar` em todo boot)** — na
   Vercel, essas duas chamadas rodavam em TODO cold start, não só na
   primeira vez. Agora só rodam incondicionalmente em dev local (sem a
   env var `VERCEL`); em produção só rodam se `RUN_MIGRATIONS=1` for
   setado explicitamente — escape hatch pra quando um schema novo
   precisar ser aplicado.
6. **Dashboard recarregava tudo após qualquer ação** — renomear/mover/
   excluir pasta ou deck refazia `listarPastas` + `listarDecks` + todos os
   stats. Agora cada mutação atualiza só o pedaço do estado local que
   mudou, usando a resposta da própria chamada.

Depois desses 6, mais duas rodadas de trabalho:

- **Skeletons de carregamento no Dashboard** — loading states genéricos
  trocados por skeletons que reproduzem a estrutura real (grid/lista de
  pastas, linhas de deck, células do heatmap), evitando pulo de layout.
  De brinde, corrigiu um bug em `.barra-seg-skeleton` que referenciava uma
  animação CSS inexistente (renderizava estático em vez de brilhar).
- **Pool de conexões + timeout do Gemini** (detalhes na seção 4) —
  identificados numa análise de arquitetura pra cenário de alta escala.
- **Investigação de infra (Neon pooler + `maxDuration`)** — as duas
  maiores dúvidas em aberto da análise de escalabilidade foram fechadas
  por investigação direta, sem precisar mudar nada em produção. Detalhes
  na seção 4.

---

## 2. Estado dos testes

**Suíte backend (5 arquivos, scripts standalone em `estalo-backend/`,
rodados com `uv run python3 <arquivo>.py`):**

| Arquivo | Status |
|---|---|
| `test_auth.py` | ✅ passa |
| `test_folders.py` | ✅ passa |
| `test_decks_cards.py` | ✅ passa |
| `test_study.py` | ✅ passa |
| `test_ai.py` | ✅ passa |

Não são testes `pytest` formais — são scripts com `assert` que rodam
contra o SQLite local real (`estalo.db`), criando usuários de teste tipo
`vini@estalo.dev`. **Sempre faça backup do `estalo.db` antes de rodar
(`cp estalo.db /tmp/backup.db`) e restaure depois** — eles escrevem dados
de verdade no banco de dev.

`test_ai.py` e `test_study.py` estavam quebrados havia um tempo (referência
a uma função renomeada e uma asserção de schema desatualizada) — corrigidos
nesta sessão sem alterar nenhuma lógica de aplicação, só as expectativas
dos testes. Um achado real no caminho: `test_study.py` assumia "errar um
card manda pra amanhã", mas o comportamento real e intencional (confirmado
com o usuário) é **Crítico Imediato** — `study.py:238-245` põe
`due_date = agora` quando `quality <= 2`, fazendo o card reaparecer na
mesma sessão. Os testes agora validam isso diretamente.

**Suíte frontend (Playwright, `estalo-frontend/e2e/navegacao.spec.js`,
rodada com `npm run test:e2e`):** ✅ 2/2 passa. Não depende de backend
rodando (só testa comportamento client-side sem sessão).

---

## 3. Dívidas técnicas pendentes

Não bloqueiam nada, mas ficaram de fora do escopo desta sessão:

- **`datetime.utcnow()` deprecated** — `test_study.py` (e o próprio
  `study.py`, que usa o mesmo padrão) emite `DeprecationWarning` no
  Python 3.12+. Não é urgente, mas a migração pra
  `datetime.now(datetime.UTC)` deveria ser feita em todo o codebase de
  uma vez, não arquivo a arquivo.
- **`gerar_cards` morto em `services/ai.py`** — função legada (gera só
  front/back) não é mais chamada por nenhum router desde que
  `gerar_cards_completos` assumiu o endpoint de geração. Ninguém apagou
  ainda.
- **Sem log drain / analytics configurado** — `vercel logs` não retorna
  histórico (retenção curta do plano atual). Sentry cobre exceptions no
  frontend, mas não há Sentry no backend nem Vercel Analytics/Speed
  Insights habilitado.
- **UI/Skeleton — só o Dashboard foi coberto.** As outras telas (Cards,
  Aprender, Estudo, Revelar, CriarDeck) não passaram por essa revisão de
  loading state.
- **`docs/pontos_criticos_performance.md`, `docs/log_operacao.txt`,
  `spec.md`** continuam intencionalmente fora do controle de versão (não
  aparecem no git), por convenção já estabelecida ao longo da sessão.

---

## 3.1. Backlog de melhorias futuras

Ideias discutidas mas não implementadas — não são dívida técnica (nada
está quebrado ou pendente), são escopo novo pra quando fizer sentido:

- **Personalização de cores nas pastas (identidade visual)** — capacidade
  de atualizar a cor de cada pasta, pra facilitar organização visual e
  identificação rápida no Dashboard. Requer migração de banco/schema no
  backend (nova coluna em `Folder`) e um color picker na modal de
  criação/edição no frontend.

---

## 4. Configuração de infra — pool de conexões, retry do Gemini, pooler e maxDuration

**Pool de conexões (`estalo-backend/app/core/database.py`):**
```python
pool_size=3, max_overflow=2, pool_pre_ping=True, pool_recycle=300
```
Só se aplica a Postgres (produção); SQLite local não é afetado. Motivo:
o `QueuePool` padrão do SQLAlchemy abre até 15 conexões por instância, e
cada cold start na Vercel recria o engine do zero — sob carga, várias
instâncias simultâneas multiplicavam isso contra o limite de conexões do
Neon. `pool_pre_ping` evita usar uma conexão que o Neon já fechou por trás
(comum após idle); `pool_recycle=300` descarta conexões com mais de 5min
antes que isso aconteça.

**Retry/timeout do Gemini (`estalo-backend/app/services/ai.py`):**
- Antes: 3 tentativas × até 90s, backoff 2s/4s → pior caso ~276s.
- Agora: 2 tentativas × até 25-30s (varia por endpoint), backoff fixo de
  2s → pior caso ~62s no endpoint mais pesado
  (`gerar_cards_completos`, timeout=30; `gerar_cards` legado, timeout=20;
  `gerar_quiz`/`gerar_explicacoes` usam o default de 25).
- Corrigido também um bug de código morto: na última tentativa, um status
  retryable (503 etc.) sempre caía no `raise_for_status()` e mascarava a
  mensagem de exaustão — a mensagem final "indisponível após N tentativas"
  era inalcançável. Agora a última tentativa falhando cai corretamente
  nessa mensagem.
- Erros não-transitórios (4xx que não estão em `_RETRY_STATUS`) continuam
  falhando na hora, sem retry.

**Neon pooler — já confirmado ativo, sem precisar mudar nada.**
`estalo-backend/app/core/database.py` prioriza uma variável
`DATABASE_URL_POOL` sobre `DATABASE_URL`, se estiver setada (código
mantido como porta de emergência de custo zero). Mas a investigação real
mostrou que isso não é necessário: criamos temporariamente um endpoint
`GET /admin/debug/db` (protegido por token, respondia 404 sem ele, nunca
retornava usuário/senha) só pra confirmar de fora qual host a
`DATABASE_URL` de produção realmente usa. Resultado:
`ep-mute-mode-at7338cu-pooler.c-9.us-east-1.aws.neon.tech` — **já tem
`-pooler` no nome**. A integração Neon×Vercel provisiona a `DATABASE_URL`
padrão como pooled desde o início; a variável `DATABASE_URL_UNPOOLED`
(separada, nunca usada pela app) é que guarda a conexão direta. Confirmada
a resposta, o endpoint de diagnóstico foi removido do código e do ar
(commit `687ec03`) — cumpriu o propósito e não teria mais valor
operacional mantido ligado.

**`maxDuration` — já confirmado em 300s, sem precisar mexer no
`vercel.json`.** A dúvida original era se o timeout do Gemini (reduzido
nesta sessão, ver acima) cabia dentro do limite real da função, já que o
`vercel.json` do backend nunca configurou isso explicitamente. Investigação
via `vercel inspect <deployment> --json` mostrou a config real da Lambda
em produção:
```json
"lambda": { "runtime": "python3.12", "memorySize": 2048, "timeout": 300 }
```
Com Fluid Compute (ativo por padrão em projetos novos — este tem poucos
dias), o `maxDuration` **padrão já é 300s tanto no Hobby quanto no Pro**,
bem acima do pior caso atual do Gemini (~62s, folga enorme) e até do pior
caso *antigo* antes da redução (~276s, cabia por pouco). Ou seja: mesmo
antes da redução do timeout do Gemini, a plataforma nunca esteve matando
essas requests no meio do caminho — a suposição inicial de que isso era
um risco ativo estava errada. A redução do timeout continua valendo (falha
mais rápido, gasta menos compute-time à toa, mensagem de erro mais clara),
mas não era, e não é, uma correção de timeout de plataforma. Decisão:
**não adicionar `maxDuration` manual ao `vercel.json`** — o default já
atende com folga, e mexer nesse arquivo (formato `services.web`, pouco
documentado) sem necessidade real só adicionaria risco.

**Deploy:** processo documentado em `checklist_de_deploy.md` (raiz do
repo, versionado). Ponto mais importante de lá: o alias
`estalo-api.vercel.app` (o que o frontend realmente chama) **não se
atualiza sozinho** quando o backend é deployado — só
`estalo-backend.vercel.app` é realiasado automaticamente. Sempre confirmar
e reatribuir manualmente se necessário.
