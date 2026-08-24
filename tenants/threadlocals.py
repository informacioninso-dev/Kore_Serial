from threading import local


_state = local()


def set_current_tenant(tenant):
    _state.tenant = tenant


def get_current_tenant():
    return getattr(_state, "tenant", None)


def clear_current_tenant():
    if hasattr(_state, "tenant"):
        del _state.tenant
