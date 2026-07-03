# Checklist de deploy — Estalo

> Roteiro pra rodar antes/durante/depois de QUALQUER deploy pra produção,
> back ou frontend. Reflete o processo que já vem sendo seguido nas últimas
> entregas — não é teoria, é o que já provou pegar problema real (ex: o
> alias `estalo-api.vercel.app` que não se atualiza sozinho, ver passo 6).

## 1. Pré-deploy local

- [ ] `git status` — confirmar que só os arquivos pretendidos estão
      staged. Nunca `git add -A`/`git add .` às cegas.
- [ ] Backend: `python3 -m py_compile app/main.py` (ou o arquivo alterado)
      pra pegar erro de sintaxe antes de subir.
- [ ] Frontend: `npm run build` — o build de produção usa código minificado
      e às vezes pega erro que o dev server não pega.
- [ ] Rodar a suíte E2E local: `npm run test:e2e` (dentro de
      `estalo-frontend`). Zero teste vermelho antes de prosseguir.
- [ ] Se a mudança envolveu schema de banco (nova coluna/índice), testar a
      migração contra uma **cópia** do SQLite local, nunca o banco real —
      ver o padrão usado pra validar o guard de `RUN_MIGRATIONS` como
      referência.
- [ ] Checar processos zumbis antes de testar localmente:
      `ps aux | grep -iE "vite|uvicorn" | grep -v grep` — um `vite` velho
      apontando pra API errada (local vs. produção) já causou teste "local"
      batendo sem querer em produção nesta sessão.

## 2. Revisão da mudança

- [ ] Reler o diff (`git diff` / `git diff --stat`) uma última vez —
      confirmar que não sobrou nenhum `console.log`/`print` de debug,
      nenhuma URL/segredo hardcoded.
- [ ] Se a mudança toca autenticação, isolamento de dados entre usuários,
      ou exclusão em cascata: testar explicitamente com um segundo usuário
      de teste que uma conta não acessa/apaga dado de outra.
- [ ] Confirmar que `docs/pontos_criticos_performance.md` (se existir na
      sua cópia local) está atualizado, caso a mudança seja de performance.

## 3. Commit

- [ ] Mensagem de commit focada no *porquê*, não no *o quê* (o diff já
      mostra o quê).
- [ ] Preferir um commit por mudança logicamente independente, mesmo que
      todos vão pro ar juntos depois — facilita reverter só uma parte se
      precisar.

## 4. Deploy do frontend

- [ ] `git push origin main` — o projeto `estalo` (frontend) está
      integrado ao GitHub e faz deploy automático. **Não precisa** rodar
      `vercel --prod` manualmente pra frontend.
- [ ] Confirmar que o deploy novo ficou `Ready`:
      `vercel ls estalo` (olhar a idade/status da entrada mais recente).
- [ ] Confirmar que o alias de produção (`estalo-sigma.vercel.app`) já
      aponta pro deployment novo: `vercel alias ls | grep estalo-sigma`.

## 5. Deploy do backend (só se algo em `estalo-backend/` mudou)

- [ ] `cd estalo-backend && vercel --prod --yes`
- [ ] **Passo que mais falha se pulado:** o alias automático da Vercel só
      atualiza `estalo-backend.vercel.app` — o domínio que o frontend
      realmente chama é `estalo-api.vercel.app`, e ele **não** se
      realiasa sozinho. Sempre confirmar com
      `vercel alias ls | grep estalo-api` e, se ainda apontar pro
      deployment antigo, rodar:
      `vercel alias set <deployment-novo> estalo-api.vercel.app`
- [ ] Health check: `curl -s https://estalo-api.vercel.app/` — esperar
      `{"status":"ok", ...}`.

## 6. Verificação pós-deploy em produção

- [ ] Health check dos dois domínios (frontend 200, backend `status: ok`).
- [ ] Rodar um fluxo real contra produção com uma **conta de teste
      descartável** (nunca a conta real do usuário nem dados reais):
      registrar → login → criar pasta/deck → exercitar a funcionalidade
      que mudou → **apagar tudo que foi criado no teste** (confirmar a
      limpeza via API, não só pela tela — a UI pode "parecer" limpa e o
      dado continuar no banco).
- [ ] Conferir o console do navegador durante esse teste — zero erros.
- [ ] Checar o Sentry (projeto `estalo-frontend`, org `stalo-3e`) por
      issues novos não-resolvidos desde o deploy:
      `is:unresolved` ordenado por `firstSeen` — ignorar o
      "[teste] erro simulado" do botão de dev, olhar qualquer coisa nova
      além dele.

## 7. Se algo quebrar

- [ ] Rollback do frontend: `vercel rollback <deployment-anterior-ou-url>`
      dentro de `estalo-frontend` (ou `vercel alias set` apontando de
      volta pro deployment anterior, que aparece em `vercel ls estalo`).
- [ ] Rollback do backend: mesma lógica dentro de `estalo-backend`, mas
      **lembrar de reatribuir o alias `estalo-api.vercel.app`** de novo
      pro deployment antigo — o rollback também não mexe nesse alias
      sozinho.
- [ ] Se o problema for de schema (migração aplicada que não devia),
      qualquer correção de dado é feita com muito cuidado e, se possível,
      revertendo a alteração via nova migração — nunca editando produção
      na mão sem plano de rollback.

## 8. Depois que está tudo estável

- [ ] Atualizar `docs/log_operacao.txt` (se o projeto estiver mantendo
      esse log) com o resumo do que foi feito.
- [ ] Se o item resolvia algo listado em
      `docs/pontos_criticos_performance.md`, marcar como corrigido lá.
