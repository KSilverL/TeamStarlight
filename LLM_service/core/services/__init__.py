"""
Service layer: backend-agnostic contracts plus mock and Azure implementations,
selected at runtime by the factory according to the feature toggle in core.config.

Nodes depend only on the ABCs in `base` and the getters in `factory`; they never
import a concrete implementation directly.
"""
