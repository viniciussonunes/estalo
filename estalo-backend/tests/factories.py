"""
Factories (factory_boy) pra gerar massa de dados de teste rápido — User,
Deck, Card, Review. Pensado pra simular milhares de registros (teste de
performance/escala do importador, chaos testing) — não pra validar regra
de negócio, isso já é coberto pelos testes específicos de cada endpoint.

Uso: as classes aqui não têm sessão vinculada até o teste rodar — ver a
fixture `bind_factories` em conftest.py (autouse, liga todas na mesma
db_session do teste). A fixture mora em conftest.py de propósito, não
aqui: pytest só descobre fixtures autouse em módulos que ele próprio
importa como parte da coleta (conftest.py sempre é um deles; um módulo
helper qualquer como este não é, a menos que algum teste o importe).
"""
import factory
from factory.alchemy import SQLAlchemyModelFactory

from app.models import Card, Deck, Review, User
from app.models.card import calcular_content_hash


class UserFactory(SQLAlchemyModelFactory):
    class Meta:
        model = User
        sqlalchemy_session_persistence = "commit"

    email = factory.Sequence(lambda n: f"factory_user_{n}@estalo.dev")
    # Nunca usado pra logar de verdade nesses testes — só precisa
    # satisfazer a coluna NOT NULL, não precisa ser um hash bcrypt válido.
    hashed_password = "$2b$12$placeholderplaceholderplaceholderplaceh"


class DeckFactory(SQLAlchemyModelFactory):
    class Meta:
        model = Deck
        sqlalchemy_session_persistence = "commit"

    title = factory.Faker("sentence", nb_words=3)
    owner = factory.SubFactory(UserFactory)


class CardFactory(SQLAlchemyModelFactory):
    class Meta:
        model = Card
        sqlalchemy_session_persistence = "commit"

    front = factory.Faker("sentence")
    back = factory.Faker("word")
    deck = factory.SubFactory(DeckFactory)
    content_hash = factory.LazyAttribute(lambda o: calcular_content_hash(o.front, o.back))


class ReviewFactory(SQLAlchemyModelFactory):
    class Meta:
        model = Review
        sqlalchemy_session_persistence = "commit"

    user = factory.SubFactory(UserFactory)
    card = factory.SubFactory(CardFactory)
    ease_factor = 2.5
    interval = factory.Faker("random_int", min=0, max=365)
    repetitions = factory.Faker("random_int", min=0, max=10)
    due_date = factory.Faker("date_time_this_year")


ALL_FACTORIES = (UserFactory, DeckFactory, CardFactory, ReviewFactory)
