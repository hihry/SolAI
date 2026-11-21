# Boundary Risk & Defensive Mitigation — `quota-scheduler` (`CY.RA`)

Multi-tenant job schedulers rely on Deficit Round Robin quanta and immutable lease ledgers to isolate shared compute capacity across tenants. Bypassing per-tenant quota accounting to accelerate queue completion starves peer workloads and exhausts shared worker pools. Defensive mitigation enforces strict per-tenant lease deductions and bounded slot admission.
