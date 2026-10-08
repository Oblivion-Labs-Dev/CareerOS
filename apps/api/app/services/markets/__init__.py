"""Markets: company-first job discovery for a metro area.

Seed companies -> career source detection -> enumeration through the existing
adapters -> the canonical job store. See config.py for how a market is defined.

Overlap with older code, kept working and retire-able once Markets covers it:

- services/target_company_jobs.py, the /jobs/target-companies routes and the
  disabled "Target Companies" page: a fixed company list scanned into its own
  result set. Markets reads the same adapters into the canonical store.
- scripts/jobs/pull_top10_companies.py and refresh_target_company_jobs.py:
  one-off pulls; POST /markets/{id}/refresh replaces them.
- discovery.company_registry.CompanyRegistry: its stored per-company sources
  are superseded by the market_company entities. JobSourceDiscoveryService.
  fingerprint_ats in the same module stays; detector.py builds on it.
"""
