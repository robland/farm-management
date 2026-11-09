"""Load test of the API (backend/loadtest/README.md, OPEN_QUESTIONS Q35).

Each virtual user is a farm manager of the fictitious load-test farm, using the mobile
flow (token in the body): profile, lists, synchronisation pull and push, expenses.
Prepare the data first with `manage.py prepare_load_test --confirm`.

    LOAD_TEST_PASSWORD=... uv run --group load locust -f loadtest/locustfile.py \
        --host https://localhost:8443 --users 20 --spawn-rate 0.3 --run-time 5m --headless
"""

import itertools
import os
import random
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from locust import HttpUser, between, events, task

PASSWORD = os.environ.get("LOAD_TEST_PASSWORD", "")
USERS = int(os.environ.get("LOAD_TEST_USERS", "20"))
EMAIL = "charge-{:03d}@example.invalid"
_numbers = itertools.cycle(range(1, USERS + 1))
_lock = threading.Lock()


@events.init.add_listener
def _check_configuration(environment: Any, **_kwargs: Any) -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("LOAD_TEST_PASSWORD is required (see loadtest/README.md).")


class FarmManager(HttpUser):
    wait_time = between(2, 6)  # a person reads and types between two actions

    def on_start(self) -> None:
        if self.host and self.host.startswith("https://localhost"):
            # Local pilot stack: certificate issued by Caddy's internal authority.
            self.client.verify = False
        with _lock:
            number = next(_numbers)
        response = self.client.post(
            "/api/v1/auth/login/",
            json={
                "identifier": EMAIL.format(number),
                "password": PASSWORD,
                "platform": "android",
                "device_label": f"locust-{number}",
            },
            name="auth/login",
        )
        response.raise_for_status()
        tokens = response.json()
        self.client.headers["Authorization"] = f"Bearer {tokens['access']}"
        self.device_id = tokens["device_id"]
        me = self.client.get("/api/v1/me/", name="me").json()
        farm = next(f for f in me["farms"] if f["name"].startswith("Exploitation de charge"))
        self.farm = farm["id"]
        self.base = f"/api/v1/farms/{self.farm}"
        self.cursor = 0
        self.parcels: list[dict[str, Any]] = []
        self.account = self.client.get(
            f"{self.base}/treasury-accounts/", name="farm/treasury-accounts"
        ).json()["results"][0]["id"]
        categories = self.client.get(
            f"/api/v1/organizations/{farm['organization_id']}/finance-categories/",
            name="org/finance-categories",
        ).json()["results"]
        self.category = next(c["id"] for c in categories if c["kind"] == "expense")
        self.list_parcels()
        self.pull()

    @task(5)
    def list_parcels(self) -> None:
        response = self.client.get(f"{self.base}/parcels/?page_size=50", name="farm/parcels")
        if response.ok:
            self.parcels = response.json()["results"]

    @task(3)
    def list_tasks(self) -> None:
        self.client.get(f"{self.base}/tasks/", name="farm/tasks")

    @task(4)
    def pull(self) -> None:
        response = self.client.get(
            f"/api/v1/sync/pull/?farm_id={self.farm}&cursor={self.cursor}&limit=500",
            name="sync/pull",
        )
        if response.ok:
            self.cursor = response.json()["next_cursor"]

    @task(2)
    def push_parcel_note(self) -> None:
        """Offline edit replayed by the queue: three-way merge, conflicts are legitimate."""
        if not self.parcels:
            return
        parcel = random.choice(self.parcels)
        note = f"Passage du {datetime.now(UTC):%d/%m %H:%M:%S}"
        operation = {
            "op_id": str(uuid.uuid4()),
            "farm_id": self.farm,
            "op_type": "update",
            "entity_type": "fields.parcel",
            "entity_id": parcel["id"],
            "payload": {"notes": note},
            "base_version": parcel["version"],
            "base_values": {"notes": parcel.get("notes", "")},
            "created_at": datetime.now(UTC).isoformat(),
        }
        with self.client.post(
            "/api/v1/sync/push/",
            json={"device_id": self.device_id, "protocol_version": 1, "operations": [operation]},
            name="sync/push",
            catch_response=True,
        ) as response:
            if response.ok and response.json()["results"][0]["status"] in {"applied", "conflict"}:
                response.success()
            else:
                response.failure(f"{response.status_code}: {response.text[:200]}")

    @task(1)
    def record_expense(self) -> None:
        self.client.post(
            f"{self.base}/transactions/",
            json={
                "kind": "expense",
                "business_date": datetime.now(UTC).date().isoformat(),
                "amount": str(random.randint(1, 500) * 100),
                "account": self.account,
                "category": self.category,
                "description": "Dépense fictive (test de charge)",
            },
            headers={"Idempotency-Key": str(uuid.uuid4())},
            name="farm/transactions:create",
        )

    @task(1)
    def balances(self) -> None:
        self.client.get(f"{self.base}/treasury-accounts/balances/", name="farm/balances")
