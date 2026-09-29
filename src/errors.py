class StoreUnavailable(Exception):
    """
    The backend could not be read at all. The run must stop: carrying on
    without knowing what is stored would create every fixture again.
    """
