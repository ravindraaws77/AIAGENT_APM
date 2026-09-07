"""Salesforce connector -- "APM Connector_Enterprise" system integration.

Read (SOQL query, read a single record) and write (create/update a record)
land together here rather than across separate phases, matching the shape
every other connector in this repo ended up at (Gmail/Calendar/Excel all
now have both). The non-negotiable rule still applies in full: write
methods default to dry_run=True, log every call (including a real one) via
require_dry_run_guard, and are only ever safe to call with dry_run=False
from inside the agent graph's execute_node, after an approved
human-approval interrupt (apm.agent.graph) -- see
.claude/skills/tool-integration/SKILL.md. This connector is not yet wired
into the agent graph or the /tools/* API surface (same "built, not yet
onboarded" state MS Excel is in -- see docs/capability-map.md); doing so
is additive, no changes needed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote

from apm.config import Settings
from apm.state.store import StateStore
from apm.tools._retry import with_retry
from apm.tools.base import ActionResult, BaseTool, Capability


class SalesforceClient(Protocol):
    """The minimal surface SalesforceTool needs from a Salesforce API
    client. Both the real client (`SalesforceRestClient`, below) and test
    fakes implement just this, so the connector's logic can be tested
    without live credentials.
    """

    def query(self, soql: str) -> list[dict[str, Any]]: ...

    def get_record(self, object_name: str, record_id: str) -> dict[str, Any]: ...

    def create_record(self, object_name: str, fields: dict[str, Any]) -> dict[str, Any]: ...

    def update_record(self, object_name: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SalesforceRecord:
    record_id: str
    object_type: str
    fields: dict[str, Any] = field(default_factory=dict)


class SalesforceTool(BaseTool):
    """Salesforce connector: SOQL query / read a record, and create/update
    a record -- the latter only ever reachable through the agent's
    approval interrupt (see apm.agent.graph), same pattern as
    ExcelTool.write_range.
    """

    name = "salesforce"
    capabilities = frozenset({Capability.READ, Capability.WRITE})

    def __init__(self, state: StateStore, client: SalesforceClient) -> None:
        super().__init__(state)
        self._client = client

    def health_check(self) -> bool:
        try:
            self._client.query("SELECT Id FROM Organization LIMIT 1")
            return True
        except Exception:
            return False

    def query_records(self, process_id: str, soql: str) -> list[SalesforceRecord]:
        """Run a read-only SOQL query (e.g.
        `"SELECT Id, Name, StageName FROM Opportunity WHERE AccountId = '001..' LIMIT 20"`)
        and return normalized records. Cap result size with SOQL's own
        LIMIT clause -- this connector does not paginate beyond the first
        page Salesforce returns.
        """
        raw_records = self._client.query(soql)
        records = [self._to_record(r) for r in raw_records]
        self._log(
            process_id,
            "read",
            f"Queried Salesforce ('{soql}'), found {len(records)} record(s)",
            {"soql": soql, "count": len(records)},
        )
        return records

    def get_record(self, process_id: str, object_name: str, record_id: str) -> SalesforceRecord:
        record = self._to_record(self._client.get_record(object_name, record_id), object_type=object_name)
        self._log(
            process_id,
            "read",
            f"Read Salesforce {object_name} record {record_id}",
            {"object_name": object_name, "record_id": record_id},
        )
        return record

    def create_record(
        self, process_id: str, object_name: str, fields: dict[str, Any], dry_run: bool = True
    ) -> ActionResult:
        """Create a new record (e.g. object_name="Lead", fields={"LastName":
        "Doe", "Company": "Acme"}). Only ever call this with dry_run=False
        from inside the agent graph, after the human-approval interrupt
        has returned an approval.
        """
        summary = f"Create Salesforce {object_name} record"
        self.require_dry_run_guard(dry_run, process_id, summary)

        if dry_run:
            return ActionResult(
                executed=False, description=summary, details={"object_name": object_name, "fields": fields}
            )

        created = self._client.create_record(object_name, fields)
        return ActionResult(
            executed=True,
            description=summary,
            details={"object_name": object_name, "fields": fields, "record_id": created.get("id")},
        )

    def update_record(
        self, process_id: str, object_name: str, record_id: str, fields: dict[str, Any], dry_run: bool = True
    ) -> ActionResult:
        """Update an existing record's fields (e.g. object_name="Opportunity",
        record_id="006...", fields={"StageName": "Closed Won"}). Only ever
        call this with dry_run=False from inside the agent graph, after
        the human-approval interrupt has returned an approval.
        """
        summary = f"Update Salesforce {object_name} record {record_id}"
        self.require_dry_run_guard(dry_run, process_id, summary)

        if dry_run:
            return ActionResult(
                executed=False,
                description=summary,
                details={"object_name": object_name, "record_id": record_id, "fields": fields},
            )

        self._client.update_record(object_name, record_id, fields)
        return ActionResult(
            executed=True,
            description=summary,
            details={"object_name": object_name, "record_id": record_id, "fields": fields},
        )

    @staticmethod
    def _to_record(raw: dict[str, Any], object_type: str | None = None) -> SalesforceRecord:
        attributes = raw.get("attributes", {}) if isinstance(raw.get("attributes"), dict) else {}
        fields = {k: v for k, v in raw.items() if k not in ("Id", "attributes")}
        return SalesforceRecord(
            record_id=raw.get("Id", ""),
            object_type=object_type or attributes.get("type", ""),
            fields=fields,
        )


class SalesforceRestClient:
    """Real Salesforce REST API client, built from an access token +
    instance URL obtained via apm.tools.salesforce_auth.acquire_access_token.
    Imports `requests` lazily so this module -- and SalesforceTool's unit
    tests, which use a fake client -- don't require that dependency at
    import time.
    """

    def __init__(self, access_token: str, instance_url: str, api_version: str) -> None:
        self._access_token = access_token
        self._base = f"{instance_url}/services/data/{api_version}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}

    @with_retry()
    def query(self, soql: str) -> list[dict[str, Any]]:
        import requests

        response = requests.get(
            f"{self._base}/query/", params={"q": soql}, headers=self._headers(), timeout=30
        )
        response.raise_for_status()
        return response.json().get("records", [])

    @with_retry()
    def get_record(self, object_name: str, record_id: str) -> dict[str, Any]:
        import requests

        response = requests.get(
            f"{self._base}/sobjects/{quote(object_name)}/{quote(record_id)}",
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    # Deliberately NOT retried -- see apm.tools._retry's module docstring:
    # a dropped connection after Salesforce already created the record
    # must not turn into an automatic duplicate.
    def create_record(self, object_name: str, fields: dict[str, Any]) -> dict[str, Any]:
        import requests

        response = requests.post(
            f"{self._base}/sobjects/{quote(object_name)}/",
            headers=self._headers(),
            json=fields,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    # Deliberately NOT retried, same reasoning as create_record.
    def update_record(self, object_name: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        import requests

        response = requests.patch(
            f"{self._base}/sobjects/{quote(object_name)}/{quote(record_id)}",
            headers=self._headers(),
            json=fields,
            timeout=30,
        )
        response.raise_for_status()
        return {"id": record_id} if response.status_code == 204 else response.json()


def build_salesforce_tool(state: StateStore, settings: Settings) -> SalesforceTool:
    """Convenience factory: runs the Client Credentials token exchange and
    returns a SalesforceTool backed by the real Salesforce REST API. Not
    called by unit tests, which construct SalesforceTool directly with a
    fake client instead.
    """
    from apm.tools.salesforce_auth import DEFAULT_API_VERSION, acquire_access_token

    access_token, instance_url = acquire_access_token(settings)
    api_version = settings.salesforce_api_version or DEFAULT_API_VERSION
    return SalesforceTool(state, SalesforceRestClient(access_token, instance_url, api_version))
