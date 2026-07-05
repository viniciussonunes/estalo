"""
Helpers de estudo que atravessam a hierarquia de pastas — hoje só
get_all_deck_ids_in_folder(), usada pelo "Estudo por Pasta" em
GET /study/global-reviews (ver app/routers/study.py).

Não existe uma classe StudyService neste projeto — study.py é um router
baseado em funções (mesmo padrão de cards.py/decks.py/folders.py), sem
camada de serviço em classe. Esta função mora aqui como um módulo comum
(não dentro do router) só porque é reaproveitável e não depende de nada
do FastAPI.
"""
from sqlalchemy.orm import Session

from app.models import Deck, Folder


def get_all_deck_ids_in_folder(folder_id: int, user_id: int, db: Session) -> list[int]:
    """IDs de todos os decks dentro da pasta `folder_id` E de todas as
    suas subpastas, recursivamente (profundidade real do projeto é ≤4,
    ver MAX_FOLDER_DEPTH, mas a busca aqui é iterativa em largura — não
    recursão Python — então não depende dessa garantia pra ser segura).

    Escopado por user_id em toda consulta: uma pasta de outro usuário (ou
    suas subpastas/decks) nunca aparece no resultado, mesmo que o
    folder_id exista de verdade no banco.
    """
    ids_pastas = [folder_id]
    fronteira = [folder_id]
    while fronteira:
        subpastas = (
            db.query(Folder.id)
            .filter(Folder.parent_id.in_(fronteira), Folder.owner_id == user_id)
            .all()
        )
        novos_ids = [f.id for f in subpastas]
        ids_pastas.extend(novos_ids)
        fronteira = novos_ids

    return [
        d.id for d in db.query(Deck.id)
        .filter(Deck.folder_id.in_(ids_pastas), Deck.owner_id == user_id)
        .all()
    ]
