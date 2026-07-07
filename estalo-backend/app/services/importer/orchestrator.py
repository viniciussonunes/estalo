"""
Orquestrador do Motor de Importação Anki — liga anki_parser + anki_mapping
à persistência real (staging → Card/Review). Sem nenhuma dependência de
FastAPI: recebe uma Session do SQLAlchemy "pura" e devolve dicts/exceptions
simples — quem for expor isso como endpoint (ainda não implementado)
decide como traduzir DeckNaoAutorizadoError/AnkiImportError em HTTP.

Duas decisões de design que a especificação original deixava em aberto:

1. `initiate_import` recebe `deck_id` (a assinatura original só listava
   `user_id, file_path`, mas o requisito de segurança pede validar
   permissão "pro deck_id" — sem o parâmetro isso não existe pra validar).

2. `ImportStagingCard` (schema de uma etapa anterior) não tem coluna
   própria pra `deck_id`/`user_id` — só job_id, front/back/tags/anki_payload.
   Em vez de migrar o schema de novo, o deck_id é guardado DENTRO do
   anki_payload (que já é JSON livre) em initiate_import, e o user_id é
   derivado de Deck.owner_id em process_batch (um deck só tem um dono,
   então redundante guardar os dois). mapear_para_estalo() ignora essa
   chave extra sem problema (só lê as que conhece via .get()).

3. Review.repetitions/due_date do card importado usam uma heurística
   simples baseada só no que o parser realmente extrai (ease/interval) —
   não em reps/queue/type do Anki, que o parser não captura hoje:
   interval > 0 → repetitions=1 ("Validando"), due_date = agora + interval
   dias; interval == 0 → repetitions=0 ("Novo"), due_date = agora. Isso é
   uma aproximação deliberada, não uma leitura fiel do estado real do
   Anki — sinalizar se precisar de algo mais preciso.

4. resultado.pulados/motivos_pulados (do parser) não são persistidos hoje
   — não existe uma tabela ImportJob pra guardar metadados agregados por
   job, e o parser só devolve CONTAGENS de pulados, não os dados de cada
   nota pulada (não dá pra virar linha de staging). initiate_import
   descarta essa informação após devolver o job_id. Se o relatório final
   ao usuário precisar mostrar "X pulados por Y motivo", isso precisa de
   um lugar pra morar — meta-informação de job (tabela nova) é o caminho
   mais direto.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Card, Deck, ImportStagingCard, Review
from app.services.importer.anki_mapping import mapear_para_estalo
from app.services.importer.anki_parser import parse_apkg


class DeckNaoAutorizadoError(Exception):
    """Deck não existe ou não pertence ao usuário que iniciou o import."""


class ImportOrchestrator:
    def __init__(self, db: Session):
        self.db = db

    def initiate_import(self, user_id: int, deck_id: int, file_path: str) -> str:
        """Valida o deck, faz o parse do .apkg e popula import_staging com
        os dados CRUS do parser (a conversão pra Card/Review só acontece em
        process_batch). Levanta DeckNaoAutorizadoError ou AnkiImportError
        (de parse_apkg) — nunca grava nada no staging se qualquer um dos
        dois falhar.
        """
        deck = (
            self.db.query(Deck)
            .filter(Deck.id == deck_id, Deck.owner_id == user_id)
            .first()
        )
        if deck is None:
            raise DeckNaoAutorizadoError(
                f"Deck {deck_id} não encontrado ou não pertence ao usuário {user_id}."
            )

        resultado = parse_apkg(file_path)  # propaga AnkiImportError como está

        job_id = str(uuid.uuid4())
        linhas = [
            ImportStagingCard(
                job_id=job_id,
                front=card["front"],
                back=card["back"],
                tags=" ".join(card.get("tags", [])),
                # deck_id embutido aqui de propósito — ver decisão de design
                # (2) no docstring do módulo.
                anki_payload={**card, "deck_id": deck_id},
                status="pending",
            )
            for card in resultado.cards
        ]
        self.db.add_all(linhas)
        self.db.commit()
        return job_id

    def process_batch(self, job_id: str, batch_size: int = 200) -> dict:
        """Promove até `batch_size` linhas pendentes de staging pra
        Card/Review de verdade. Devolve o progresso ACUMULADO do job
        inteiro (não só deste lote): {"processed": N, "total": T, "errors": M}.

        Tenta o lote inteiro como UMA transação (caminho feliz, rápido).
        Se qualquer linha falhar, desfaz o lote inteiro e cai pra um
        caminho de recuperação linha-a-linha (cada uma na sua própria
        transação) — isso é o que garante progresso mesmo com uma linha
        "veneno" no meio do lote: só ELA vira "error", as boas se promovem
        normalmente na segunda passada.
        """
        pendentes = (
            self.db.query(ImportStagingCard)
            .filter(ImportStagingCard.job_id == job_id, ImportStagingCard.status == "pending")
            .order_by(ImportStagingCard.id)
            .limit(batch_size)
            .all()
        )

        if pendentes:
            try:
                self._promover_lote(pendentes)
            except Exception:
                self.db.rollback()
                self._promover_um_a_um(pendentes)

        return self._progresso(job_id)

    # ---------------------------------------------------------------- #

    def _promover_lote(self, linhas: list[ImportStagingCard]) -> None:
        for linha in linhas:
            self._promover_uma_linha(linha)
        self.db.commit()

    def _promover_um_a_um(self, linhas: list[ImportStagingCard]) -> None:
        for linha_original in linhas:
            linha = (
                self.db.query(ImportStagingCard)
                .filter(ImportStagingCard.id == linha_original.id)
                .first()
            )
            try:
                self._promover_uma_linha(linha)
                self.db.commit()
            except Exception as e:
                self.db.rollback()
                linha_erro = (
                    self.db.query(ImportStagingCard)
                    .filter(ImportStagingCard.id == linha_original.id)
                    .first()
                )
                linha_erro.status = "error"
                linha_erro.error_message = str(e)[:500]
                self.db.commit()

    def _promover_uma_linha(self, linha: ImportStagingCard) -> None:
        """Mapeia + persiste UMA linha de staging. Não faz commit (quem
        chama decide o agrupamento transacional) — só levanta se algo
        estiver errado o bastante pra não poder continuar."""
        payload = mapear_para_estalo(linha.anki_payload)
        deck_id = linha.anki_payload.get("deck_id")

        deck = self.db.query(Deck).filter(Deck.id == deck_id).first()
        if deck is None:
            raise ValueError(
                f"Deck {deck_id} não existe mais (provavelmente excluído durante a importação)."
            )

        duplicado = (
            self.db.query(Card)
            .filter(Card.deck_id == deck_id, Card.content_hash == payload.content_hash)
            .first()
        )
        if duplicado is not None:
            linha.status = "duplicate"
            return

        card = Card(
            front=payload.front,
            back=payload.back,
            deck_id=deck_id,
            source="anki_import",
            content_hash=payload.content_hash,
        )
        self.db.add(card)
        self.db.flush()  # precisa do card.id antes de criar o Review

        # .replace(tzinfo=None): equivalente não-deprecated de
        # datetime.utcnow() que preserva naive-UTC (ver comentário igual em
        # app/core/security.py) -- due_date é uma coluna DateTime naive.
        agora = datetime.now(timezone.utc).replace(tzinfo=None)
        if payload.interval > 0:
            repetitions, due_date = 1, agora + timedelta(days=payload.interval)
        else:
            repetitions, due_date = 0, agora

        self.db.add(Review(
            user_id=deck.owner_id,
            card_id=card.id,
            ease_factor=payload.ease_factor,
            interval=payload.interval,
            repetitions=repetitions,
            due_date=due_date,
        ))
        linha.status = "processed"

    def _progresso(self, job_id: str) -> dict:
        linhas = (
            self.db.query(ImportStagingCard.status)
            .filter(ImportStagingCard.job_id == job_id)
            .all()
        )
        total = len(linhas)
        # "processed" e "duplicate" contam como concluídos pro progresso —
        # os dois são resultados finais válidos, só "pending"/"error" não são.
        processados = sum(1 for (status,) in linhas if status in ("processed", "duplicate"))
        erros = sum(1 for (status,) in linhas if status == "error")
        return {"processed": processados, "total": total, "errors": erros}
