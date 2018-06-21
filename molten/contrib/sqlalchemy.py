# This file is a part of molten.
#
# Copyright (C) 2018 CLEARTYPE SRL <bogdan@cleartype.io>
#
# molten is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at
# your option) any later version.
#
# molten is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public
# License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from collections import namedtuple
from inspect import Parameter
from typing import Any, Callable, NewType, Optional

from molten import DependencyResolver
from molten.contrib.settings import Settings

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker
except ImportError:  # pragma: no cover
    raise ImportError("'sqlalchemy' package missing. Run 'pip install sqlalchemy'.")


#: The type of session factories.
SessionFactory = NewType("SessionFactory", sessionmaker)

#: The type of engine data.
EngineData = namedtuple("EngineData", "engine, session_factory")


class SQLAlchemyEngineComponent:
    """A component that sets up an SQLAlchemy Engine.  This component
    depends on :mod:`molten.contrib.settings`.

    Your settings file must contain a ``database_engine_dsn`` setting
    pointing at the database to use.  Additionally, you may provide a
    ``database_engine_params`` setting represeting dictionary data
    that will be passed directly to ``sqlalchemy.create_engine``.

    Examples:

      >>> from molten import App
      >>> from molten.contrib.settings import SettingsComponent
      >>> from molten.contrib.sqlalchemy import SQLAlchemyEngineComponent, SQLAlchemySessionComponent, SQLAlchemyMiddleware

      >>> app = App(
      ...   components=[
      ...     SettingsComponent(),
      ...     SQLAlchemyEngineComponent(),
      ...     SQLAlchemySessionComponent(),
      ...   ],
      ...   middleware=[SQLAlchemyMiddleware()],
      ... )
    """

    is_cacheable = True
    is_singleton = True

    def can_handle_parameter(self, parameter: Parameter) -> bool:
        return parameter.annotation is EngineData

    def resolve(self, settings: Settings) -> EngineData:
        engine = create_engine(
            settings.strict_get("database_engine_dsn"),
            **settings.get("database_engine_params", {}),
        )

        session_factory = sessionmaker()
        session_factory.configure(bind=engine)
        return EngineData(engine, session_factory)


class SQLAlchemySessionComponent:
    """A component that creates and injects SQLAlchemy sessions.

    Examples:

      >>> def find_todos(session: Session) -> List[Todo]:
      ...   todos = session.query(TodoModel).all()
      ...   ...

    """

    is_cacheable = True
    is_singleton = False

    def can_handle_parameter(self, parameter: Parameter) -> bool:
        return parameter.annotation is Session

    def resolve(self, engine_data: EngineData) -> Session:
        return engine_data.session_factory()


class SQLAlchemyMiddleware:
    """A middleware that automatically commits SQLAlchemy sessions on
    handler success and automatically rolls back sessions on handler
    failure.

    Sessions are only instantiated and operated upon if the handler or
    any other middleware has requested an SQLAlchemy session object
    via DI.  This means that handlers that don't request a Session
    object don't automatically connect to the Database.
    """

    def __call__(self, handler: Callable[..., Any]) -> Callable[..., Any]:
        def middleware(resolver: DependencyResolver) -> Any:
            try:
                response = handler()
                session = get_optional_session(resolver)
                if session is not None:
                    session.commit()

                return response
            except Exception:
                session = get_optional_session(resolver)
                if session is not None:
                    session.rollback()

                raise
        return middleware


def get_optional_session(resolver: DependencyResolver) -> Optional[Session]:
    """Get a session object from the resolver iff one was previously
    requested.  Returns None if no function has requested a session so
    far.
    """
    for component, value in resolver.instances.items():
        if type(component) is SQLAlchemySessionComponent:
            return value
    return None