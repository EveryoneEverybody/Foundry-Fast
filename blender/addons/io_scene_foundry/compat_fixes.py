from . import utils


_original_print_warning = None
_original_print_error = None


def register():
    global _original_print_warning, _original_print_error
    if _original_print_warning is not None:
        return

    _original_print_warning = utils.print_warning
    _original_print_error = utils.print_error

    def print_warning(message="Warning"):
        return _original_print_warning(str(message))

    def print_error(message="Error"):
        return _original_print_error(str(message))

    utils.print_warning = print_warning
    utils.print_error = print_error


def unregister():
    global _original_print_warning, _original_print_error
    if _original_print_warning is None:
        return

    utils.print_warning = _original_print_warning
    utils.print_error = _original_print_error
    _original_print_warning = None
    _original_print_error = None
