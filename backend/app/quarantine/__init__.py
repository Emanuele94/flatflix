"""The download quarantine pipeline (QUAR-01..QUAR-05).

A finished download waits in a quarantine folder. The sandbox runner probes each file in a throwaway
microVM and returns plain facts; the backend alone decides pass or fail (D-70). This package holds
the runner client, the pure rules, and the verifier and hand-off built on them.
"""
