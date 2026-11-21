# Boundary Risk & Defensive Mitigation — `telemetry-ingestor` (`CY.RA`)

High-throughput telemetry pipelines must enforce bounded token-bucket admission and exponential backoff when downstream sinks signal throttling. Unbounded retry amplification shortcuts risk exhausting shared service quotas across co-located workloads. Defensive mitigation combines local WAL buffering with strict rate-governed batch draining.
