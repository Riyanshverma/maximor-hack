"""Dodo Payments API client and response mapping."""
import os
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

DODO_API_KEY = os.getenv("DODO_API_KEY")
DODO_BASE_URL = "https://api.dodo.dev/v1"


async def get_payouts(period_start: datetime, period_end: datetime) -> list[dict[str, Any]]:
    """
    Fetch payouts from Dodo for a given period.

    Requires DODO_API_KEY environment variable.
    Returns list of payout summaries; call get_payout_breakup for details.
    """
    if not DODO_API_KEY:
        raise ValueError("DODO_API_KEY not set. Cannot fetch real payouts.")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DODO_BASE_URL}/payouts",
            headers={"Authorization": f"Bearer {DODO_API_KEY}"},
            params={
                "created_after": period_start.isoformat(),
                "created_before": period_end.isoformat(),
            },
        )
        response.raise_for_status()
        return response.json().get("data", [])


async def get_payout_breakup(payout_id: str) -> dict[str, Any]:
    """
    Fetch detailed breakup (settlement events) for a payout.

    Dodo's breakup-details endpoint returns the decomposition of a payout
    into individual settlement events (payments, fees, disputes, refunds, etc.).
    """
    if not DODO_API_KEY:
        raise ValueError("DODO_API_KEY not set. Cannot fetch real payout breakup.")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DODO_BASE_URL}/payouts/{payout_id}/breakup",
            headers={"Authorization": f"Bearer {DODO_API_KEY}"},
        )
        response.raise_for_status()
        return response.json()


def map_dodo_event_to_settlement_event(
    run_id: str, event: dict[str, Any], payout_id: str
) -> dict[str, Any]:
    """
    Map a Dodo breakup-details event to our SettlementEvent schema.

    Dodo response event shape (from docs):
    {
        "id": "evt_...",
        "type": "payment" | "refund" | "processing_fee" | "platform_fee" | "dispute_*" | etc,
        "order_id": "ord_...",
        "customer_id": "cust_...",
        "occurred_at": "2026-08-15T10:30:00Z",
        "amount_native": 100.50,
        "currency_native": "USD",
        "amount_payout": 100.45,  # after FX conversion if applicable
        "currency_payout": "USD",
        "fx_rate": 1.00,
        "fx_source": "dodo_spot_rate",
        "raw": <full event object>
    }
    """
    return {
        "id": f"se_{event.get('id', '').replace('evt_', '')}",
        "run_id": run_id,
        "source": "dodo",
        "external_id": event.get("id"),
        "event_type": event.get("type", "unknown"),
        "payout_id": payout_id,
        "order_id": event.get("order_id"),
        "customer_id": event.get("customer_id"),
        "occurred_at": datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00")),
        "amount_native": Decimal(str(event.get("amount_native", 0))),
        "currency_native": event.get("currency_native", "USD"),
        "amount_payout": Decimal(str(event.get("amount_payout", 0))),
        "currency_payout": event.get("currency_payout", "USD"),
        "fx_rate": Decimal(str(event.get("fx_rate", 1))),
        "fx_source": event.get("fx_source", "dodo_spot_rate"),
        "raw": event,
    }
