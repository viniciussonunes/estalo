#!/usr/bin/env bash
# pre_deploy.sh — gate de deploy do backend do Estalo.
#
# 1. Roda a suíte pytest isolada (estalo-backend/tests/) -- mockada, sem
#    rede, sem chave de IA real, banco em memória (ver tests/conftest.py).
#    Só essa suíte: os scripts test_*.py soltos na raiz de estalo-backend/
#    são legado (print+assert, rodam contra o estalo.db local de
#    verdade) e o próprio pytest.ini já os ignora (testpaths = tests) --
#    este script não tenta rodá-los.
# 2. Se, e só se, os testes passarem: deploy de produção do backend na
#    Vercel (`vercel --prod --yes`, dentro de estalo-backend/).
# 3. Se o deploy for bem-sucedido: reatribui o alias estalo-api.vercel.app
#    pro deployment novo -- a Vercel NUNCA faz isso sozinha (o alias
#    automático só atualiza estalo-backend.vercel.app, não o domínio que
#    o frontend de fato chama). Esse é o passo mais fácil de esquecer no
#    processo manual (ver checklist_de_deploy.md) e o motivo deste script
#    existir.
#
# Escopo deliberado: só o BACKEND. O frontend (projeto `estalo`) está
# conectado ao GitHub e already faz deploy automático a cada push -- não
# tem alias manual pra reatribuir, não precisa desse gate aqui.
#
# Uso:
#   ./scripts/pre_deploy.sh              # roda tudo (testes -> deploy -> alias)
#   ./scripts/pre_deploy.sh --testes-so  # só a etapa 1, não deploya nada
#
# Pode ser chamado de qualquer diretório -- os caminhos são resolvidos a
# partir da localização do próprio script, não do cwd de quem chama.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/estalo-backend"
ALIAS_PROD="estalo-api.vercel.app"
SOMENTE_TESTES=false

if [[ "${1:-}" == "--testes-so" ]]; then
    SOMENTE_TESTES=true
fi

verde()     { printf '\033[32m%s\033[0m\n' "$1"; }
vermelho()  { printf '\033[31m%s\033[0m\n' "$1"; }
azul()      { printf '\033[34m%s\033[0m\n' "$1"; }

cd "$BACKEND_DIR"

# --- 1. Testes ---------------------------------------------------------- #

azul "==> [1/3] Rodando a suíte de testes (tests/, isolada, sem rede)..."

# Usa o Python do venv do projeto se existir (é onde pytest está
# instalado hoje) -- cai pro python3 do sistema como fallback, útil em
# CI/containers onde o ambiente já vem com as dependências instaladas
# globalmente em vez de num .venv local.
if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
    PYTHON="$BACKEND_DIR/.venv/bin/python"
else
    PYTHON="python3"
fi

if ! "$PYTHON" -m pytest; then
    vermelho "==> Testes FALHARAM. Deploy CANCELADO -- nada foi enviado pra Vercel."
    exit 1
fi
verde "==> Testes passaram."

if [[ "$SOMENTE_TESTES" == true ]]; then
    verde "==> --testes-so: parando aqui, sem deploy."
    exit 0
fi

# --- 2. Deploy ------------------------------------------------------------ #

azul "==> [2/3] Testes OK. Iniciando deploy de produção (vercel --prod)..."

# Log persistido em $REPO_ROOT (não /tmp, não apagado no EXIT) -- uma
# falha real já aconteceu aqui uma vez (extração de URL/alias) e o log
# tinha sumido no momento de investigar, porque a versão anterior deste
# script apagava via `trap ... EXIT` incondicionalmente. Agora só é
# apagado explicitamente no caminho de SUCESSO (fim do script); em
# qualquer falha, fica no disco pra inspecionar.
DEPLOY_LOG="$REPO_ROOT/.pre_deploy_last.log"

if ! vercel --prod --yes 2>&1 | tee "$DEPLOY_LOG"; then
    vermelho "==> Deploy FALHOU. Alias não foi tocado (continua apontando pro deployment anterior)."
    vermelho "    Log completo em: $DEPLOY_LOG"
    exit 1
fi

# `vercel --prod --yes` imprime a URL do deployment na linha "Production"
# do próprio output (com ou sem ":", já visto nos dois formatos entre
# versões do CLI) -- é isso que extraímos pra realiasar. Fallback: pega a
# última URL *.vercel.app de qualquer linha do log (cobre inclusive o
# bloco JSON de resumo que o plugin da Vercel imprime no final).
# tr -d remove qualquer \r/espaço perdido -- um "vercel alias set" com
# argumento sujo falha silenciosamente e é exatamente o tipo de coisa
# difícil de notar sem o log persistido acima.
DEPLOY_URL="$(grep -E 'Production' "$DEPLOY_LOG" | grep -Eo 'https://[a-zA-Z0-9.-]+\.vercel\.app' | tail -1 | tr -d '[:space:]')"
if [[ -z "$DEPLOY_URL" ]]; then
    DEPLOY_URL="$(grep -Eo 'https://[a-zA-Z0-9.-]+\.vercel\.app' "$DEPLOY_LOG" | tail -1 | tr -d '[:space:]')"
fi

if [[ -z "$DEPLOY_URL" ]]; then
    vermelho "==> Deploy parece ter funcionado, mas não consegui extrair a URL do output acima."
    vermelho "    Log completo em: $DEPLOY_LOG"
    vermelho "    Reatribua o alias manualmente: vercel alias set <deployment-novo> $ALIAS_PROD"
    exit 1
fi
verde "==> Deploy concluído: $DEPLOY_URL"

# --- 3. Alias --------------------------------------------------------------- #

azul "==> [3/3] Reatribuindo alias $ALIAS_PROD -> $DEPLOY_URL..."
azul "    Comando: vercel alias set $DEPLOY_URL $ALIAS_PROD"

if ! vercel alias set "$DEPLOY_URL" "$ALIAS_PROD"; then
    vermelho "==> Deploy foi feito, mas o ALIAS FALHOU. $ALIAS_PROD ainda aponta pro deployment antigo."
    vermelho "    Log completo em: $DEPLOY_LOG"
    vermelho "    Rode manualmente: vercel alias set $DEPLOY_URL $ALIAS_PROD"
    exit 1
fi
verde "==> Alias atualizado: $ALIAS_PROD agora aponta pro deployment novo."
rm -f "$DEPLOY_LOG"

# --- Health check ------------------------------------------------------- #

azul "==> Health check em https://$ALIAS_PROD/ ..."
if curl -sf "https://$ALIAS_PROD/" | grep -q '"status":"ok"'; then
    verde "==> OK -- https://$ALIAS_PROD respondeu status: ok."
else
    vermelho "==> Health check não confirmou 'status: ok' -- confira manualmente antes de considerar o deploy encerrado."
fi

verde "==> Deploy completo."
