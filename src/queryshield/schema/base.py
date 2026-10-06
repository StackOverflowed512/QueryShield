"""The :class:`SchemaRetriever` abstraction.

A retriever turns a live database into an immutable
:class:`~queryshield.schema.models.SchemaCatalog` snapshot. The interface is
deliberately tiny — one method — because Phase 3 has exactly one real
implementation (PostgreSQL). It exists as an interface, rather than a bare
function, so later phases can introduce alternative backends (or a caching
decorator) without the orchestrator depending on PostgreSQL directly, matching
the "extensible by interface" principle in ``CLAUDE.md``.

What a retriever must guarantee (the contract every implementation upholds):

* **Snapshot semantics.** Each :meth:`SchemaRetriever.retrieve` call performs a
  fresh introspection and returns a new, self-consistent snapshot. There is no
  implicit caching and therefore no stale result; a caching layer, if added
  later, would be an explicit decorator with explicit refresh.
* **Fail closed.** On any failure the retriever *raises*. It must never return an
  empty or partial catalog to paper over an error, because an empty database and
  a failed introspection must be distinguishable (see the error contract below).
* **Operate as the configured identity.** Introspection runs as whatever
  database principal the underlying adapter is configured with and honours that
  principal's privileges; it never claims access to an object the principal
  cannot actually read.
* **Not an authorization layer.** A retriever reports structure. It does not
  decide whether a given caller may see or query an object — that is the job of
  later policy layers. "Schema visibility" here is only about what to look at,
  which is not the same thing as database authorization.

Error contract:

* :class:`~queryshield.errors.DatabaseConnectionError` — the database could not
  be reached (unopened/exhausted pool, auth failure, timeout). Raised by the
  database layer and allowed to propagate unchanged.
* :class:`~queryshield.errors.SchemaRetrievalError` — the database was reachable
  but a catalog query failed.
* :class:`~queryshield.errors.SchemaMetadataError` — the catalog returned
  malformed or internally inconsistent metadata.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from queryshield.schema.models import SchemaCatalog


class SchemaRetriever(ABC):
    """Produces an immutable snapshot of a database's structure."""

    @abstractmethod
    async def retrieve(self) -> SchemaCatalog:
        """Introspect the database and return a fresh :class:`SchemaCatalog`.

        Implementations must honour the contract documented at module level:
        snapshot semantics, fail-closed error handling (never an empty catalog
        on failure), operating as the configured principal, and raising the
        typed errors above rather than leaking driver exceptions.
        """
        raise NotImplementedError
