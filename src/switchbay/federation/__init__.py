"""Mounted graphs, external sources, and the audit around them.

The local wiki stays mount ``local``. Other graphs are read from a
pinned snapshot or from a live ce-graph/1 server. External systems
such as Work IQ are sources, not mounts: a call is captured, and only
a snapshot the user keeps becomes something a page can cite.
"""
