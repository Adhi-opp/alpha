"""Alpha Live Desk — bounded real-time observation layer (docs/LIVE_DESK.md).

FIREWALL: nothing in alpha.data, alpha.study, or the ledger machinery may
import from this package. Live capture reaches studies only after a normal
PIT ingest + census of the captured dataset. Everything this layer ever
shows is an instrument reading; verdicts come only from the ledger.
"""
