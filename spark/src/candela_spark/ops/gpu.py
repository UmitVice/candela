import time
from collections.abc import Iterator
from contextlib import contextmanager

from candela_spark import log
from candela_spark.ops import resources
from candela_spark.ops.lease import GpuLease

_log = log.get("gpu")


@contextmanager
def gpu_job(holder: str, priority: int, purpose: str, budget_gb: float = 4.0) -> Iterator[GpuLease]:
    """Admission for one-off GPU jobs (eval, export, sampling): wait for foreign training, higher leases and
    memory headroom, then hold a lease for the duration."""
    lease = GpuLease(holder, priority, purpose)
    guard = resources.ResourceGuard(budget_gb)
    waited = 0.0
    # Rule 7: announce the reservation before waiting, so lower priorities free the memory we wait for.
    lease.acquire(state="waiting")
    try:
        while True:
            foreign = resources.foreign_training()
            higher = lease.higher()
            decision = guard.start()
            if not foreign and not higher and decision.ok:
                break
            reason = foreign[0] if foreign else (higher[0].holder if higher else decision.reason)
            if waited % 60 == 0:
                _log.info("gpu job waiting", holder=holder, reason=reason, waited_sec=round(waited))
            time.sleep(5)
            waited += 5
        resources.apply_mlx_limits(budget_gb, 0.5)
        lease.set_state("active")
        yield lease
    finally:
        lease.release()
