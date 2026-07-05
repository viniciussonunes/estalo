"""
Motor de Importação Anki — endpoints HTTP.

O fluxo é ASSÍNCRONO e CLIENT-DRIVEN, sem worker nem fila (decisão do PMA
original: Vercel serverless não tem onde rodar um worker persistente, e
adicionar um exigiria uma peça de infra nova). POST /import/anki só faz o
parse do .apkg e grava os cards crus em staging — devolve o job_id na
hora, rápido, sem criar nenhum Card/Review de verdade ainda. Quem avança o
processamento é o FRONTEND, chamando
POST /import/anki/{job_id}/process-batch repetidamente (cada chamada
promove até `batch_size` cards) até a resposta mostrar
processed == total. Não existe nada rodando sozinho em background entre
as chamadas — se o cliente parar de chamar, a importação simplesmente
para de progredir, e retoma de onde ficou na próxima chamada (o estado
todo vive em import_staging, não em memória).
"""
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user_id
from app.models import Deck, ImportStagingCard
from app.schemas.import_anki import ImportJobOut, ImportProgressOut
from app.services.importer.anki_parser import AnkiImportError
from app.services.importer.orchestrator import DeckNaoAutorizadoError, ImportOrchestrator

router = APIRouter(prefix="/import", tags=["Importação Anki"])


def _deck_id_do_job(job_id: str, db: Session) -> int | None:
    """Descobre o deck_id de um job olhando a primeira linha de staging
    dele — import_staging não tem coluna própria pra deck_id/user_id, ele
    vive dentro de anki_payload (ver ImportOrchestrator.initiate_import)."""
    linha = (
        db.query(ImportStagingCard)
        .filter(ImportStagingCard.job_id == job_id)
        .first()
    )
    if linha is None:
        return None
    return linha.anki_payload.get("deck_id")


def _validar_dono_do_job(job_id: str, user_id: int, db: Session) -> None:
    """404 se o job não existir OU não pertencer (via deck) ao usuário
    logado — nunca diferencia os dois casos pro cliente, mesmo padrão já
    usado em _deck_do_usuario/_card_do_usuario (não vaza a existência de
    jobs de outros usuários)."""
    deck_id = _deck_id_do_job(job_id, db)
    if deck_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job de importação não encontrado")
    deck = db.query(Deck).filter(Deck.id == deck_id, Deck.owner_id == user_id).first()
    if deck is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job de importação não encontrado")


@router.post("/anki", response_model=ImportJobOut, status_code=status.HTTP_201_CREATED)
def iniciar_importacao_anki(
    deck_id: int = Form(...),
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Recebe um .apkg e inicia uma importação assíncrona pro deck indicado.

    Esta chamada é DELIBERADAMENTE rápida: só extrai e valida o .apkg
    (anki_parser.parse_apkg) e grava os cards crus em import_staging —
    nenhum Card/Review de verdade é criado aqui. Devolve o job_id; o
    cliente avança o processamento de verdade chamando
    POST /import/anki/{job_id}/process-batch repetidamente depois (ver
    docstring do módulo).

    400 se o arquivo não for um .apkg válido ou estiver corrompido — nada
    é gravado no banco nesse caso (initiate_import só grava staging depois
    que o parse já deu certo). 404 se deck_id não existir ou não
    pertencer ao usuário logado.
    """
    if not arquivo.filename or not arquivo.filename.lower().endswith(".apkg"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Envie um arquivo .apkg")

    with tempfile.NamedTemporaryFile(suffix=".apkg", delete=False) as tmp:
        tmp.write(arquivo.file.read())
        caminho_tmp = Path(tmp.name)

    try:
        orchestrator = ImportOrchestrator(db)
        try:
            job_id = orchestrator.initiate_import(
                user_id=user_id, deck_id=deck_id, file_path=str(caminho_tmp)
            )
        except DeckNaoAutorizadoError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Deck não encontrado")
        except AnkiImportError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    finally:
        # O arquivo só existe pra durar o parse desta requisição — depois
        # que initiate_import volta (com sucesso ou erro), os dados já
        # estão em staging ou nada foi gravado; o tmp não serve mais.
        caminho_tmp.unlink(missing_ok=True)

    return ImportJobOut(job_id=job_id)


@router.post("/anki/{job_id}/process-batch", response_model=ImportProgressOut)
def processar_lote_importacao(
    job_id: str,
    batch_size: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Promove até `batch_size` cards pendentes deste job pra Card/Review
    de verdade. Chame repetidamente até a resposta mostrar
    processed == total — é assim que o cliente avança uma importação
    assíncrona sem worker/fila: cada chamada faz uma fatia do trabalho, e
    dá pra parar/retomar a qualquer momento (o progresso vive no banco).

    Sempre 200, mesmo se `errors` > 0 na resposta — erro num card
    individual não é falha da REQUISIÇÃO (o batch rodou e devolveu um
    resultado válido), é informação pro cliente exibir na barra de
    progresso. Só 404 se o job não existir ou não pertencer ao usuário logado.
    """
    _validar_dono_do_job(job_id, user_id, db)

    orchestrator = ImportOrchestrator(db)
    progresso = orchestrator.process_batch(job_id, batch_size=batch_size)
    return ImportProgressOut(**progresso)
