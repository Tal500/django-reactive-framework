from typing import Callable

from .base import ReactValType
from .reactive_function import ReactiveFunction, CustomReactiveFunction

def register_function(function_name: str,
    python_calc_function: Callable[..., ReactValType], js_expression_function: Callable[..., str],
    validate_arg_count: Callable[[int], bool] = lambda args: True):

    """
    Register a fucntion that can be used in Django templates.

    Parameters
    ----------
    function_name : str
        The function name
    python_calc_function : ((...) -> ReactValType)
        A function that get a list of python ReactValType arguments, and returns a python ReactValType value
    js_expression_function : ((str, ...) -> str)
        A function that get a delimiter and then a list of js ReactValType arguments as strings, and returns a js ReactValType value as a string
    validate_arg_count : ((int) -> bool)
    """

    def count_validate_func(args):
        if not validate_arg_count(len(args)):
            raise Exception(f'Bad argument count for custom registered function named {{{function_name}}}. Args: {{{args}}}.')

    custom_function = CustomReactiveFunction(
        eval_initial_func=lambda reactive_context, args:
            python_calc_function(*[arg.eval_initial(reactive_context) for arg in args]),
        eval_js_func=lambda reactive_context, delimiter, args:
            js_expression_function(delimiter, *[arg.eval_js_and_hooks(reactive_context, delimiter)[0] for arg in args]),
        validate_args_func=count_validate_func,
    )

    ReactiveFunction.functions[function_name] = custom_function