# GCP smoke-test record

On November 24, 2026, the initial archive smoke test passed on Ubuntu 24.04
with Python 3.12.3. All eight archive regression tests passed, and the
focused matrix dry run printed all 24 planned trials with zero agent launches.
This verified the archive tooling and matrix parsing on Ubuntu.

The run used private VM `ece117-smoke-20261124-213627` in `us-central1-a`.
The VM log was saved as `~/ece117-smoke.log`. The smoke-test record does not
confirm that the log was retrieved or the VM was deleted.

For the current setup and live calibration procedure, use the
[GCP runbook](gcp_vm_experiment.md).
