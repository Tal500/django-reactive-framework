from abc import abstractmethod
from typing import Callable, List, Dict

from itertools import chain

from django import template

from .base import ReactContext, ReactValType

class ReactiveFunction:
    functions: Dict[str, 'ReactiveFunction'] = dict()

    def validate_args(self, args: List['Expression']) -> None:
        pass

    @abstractmethod
    def eval_initial(self, reactive_context: ReactContext, args: List['Expression']) -> ReactValType:
        pass

    def eval_js_and_hooks(self, reactive_context: ReactContext, delimiter: str, args: List['Expression']) -> str:
        js_expression = self.eval_js(reactive_context, delimiter, args)
        all_hooks = self.eval_hooks(reactive_context, args)

        return js_expression, all_hooks

    def eval_js(self, reactive_context: ReactContext, delimiter: str, args: List['Expression']) -> str:
        pass

    def eval_hooks(self, reactive_context: ReactContext, args: List['Expression']) -> str:
        return chain.from_iterable((arg.eval_js_and_hooks(reactive_context)[1] for arg in args))

class CustomReactiveFunction(ReactiveFunction):
    def __init__(self,
        eval_initial_func: Callable[[ReactContext, List['Expression']], ReactValType],
        eval_js_func: Callable[[ReactContext, str, List['Expression']], str],
        validate_args_func: Callable[[List['Expression']], None] = lambda args: None):

        self.validate_args_func = validate_args_func
        self.eval_initial_func = eval_initial_func
        self.eval_js_func = eval_js_func

        super().__init__()

    def validate_args(self, args: List['Expression']) -> None:
        self.validate_args_func(args)

    def eval_initial(self, reactive_context: ReactContext, args: List['Expression']) -> ReactValType:
        return self.eval_initial_func(reactive_context, args)
    
    def eval_js(self, reactive_context: ReactContext, delimiter: str, args: List['Expression']) -> str:
        return self.eval_js_func(reactive_context, delimiter, args)

class PresentFunction(ReactiveFunction):
    def validate_args(self, args: List['Expression']) -> None:
        if (len(args) != 1):
            raise template.TemplateSyntaxError(f'Error while evaluating present function: ' + \
                f'there must be exactly one argument! args: ({args})')

    def eval_initial(self, reactive_context: ReactContext, args: List['Expression']) -> ReactValType:
        self.validate_args(args)
        
        val = args[0].eval_initial(reactive_context)

        return val

    def eval_js(self, reactive_context: ReactContext, delimiter: str, args: List['Expression']) -> str:
        self.validate_args(args)
        
        js, hooks = args[0].eval_js_and_hooks(reactive_context)

        return js

    def eval_hooks(self, reactive_context: ReactContext, args: List['Expression']) -> str:
        self.validate_args(args)

        return []

ReactiveFunction.functions['present'] = PresentFunction()

class LengthFunction(ReactiveFunction):
    def validate_args(self, args: List['Expression']) -> None:
        if (len(args) != 1):
            raise template.TemplateSyntaxError(f'Error while evaluating length function: ' + \
                f'there must be exactly one argument! args: ({args})')

    def eval_initial(self, reactive_context: ReactContext, args: List['Expression']) -> ReactValType:
        self.validate_args(args)
        
        array = args[0]

        return len(array.eval_initial(reactive_context))

    def eval_js(self, reactive_context: ReactContext, delimiter: str, args: List['Expression']) -> str:
        self.validate_args(args)
        
        array = args[0]

        return f'({array.eval_js_and_hooks(reactive_context, delimiter)[0]}).length'

ReactiveFunction.functions['len'] = LengthFunction()

class MatchKeyValFunction(ReactiveFunction):
    def validate_args(self, args: List['Expression']) -> None:
        if (len(args) != 2):
            raise template.TemplateSyntaxError(f'Error while evaluating length function: ' + \
                f'there must be exactly two argument! args: ({args})')

    def eval_initial(self, reactive_context: ReactContext, args: List['Expression']) -> ReactValType:
        self.validate_args(args)
        
        key_expression = args[0]
        array_expression = args[1]

        key = key_expression.eval_initial(reactive_context)
        array = array_expression.eval_initial(reactive_context)

        if not isinstance(array, List):
            raise Exception('Error in initial calc of MatchKeyValFunction: the second aurgument value isn\'t an array! ' + \
                f'Expression: {{ {array_expression} }}, Value: {{ {array} }}')
        
        match = None
        for element in array:
            # TODO: Make this equation testing more strict.
            if element['key'] == key:
                match = element
                break

        if match is None:
            raise Exception('Error in initial calc of MatchKeyValFunction:' + \
                'the second aurgument has no element with key equals to the first aurgument! ' + \
                f'aurgument expressions: {{( {key_expression} , {array_expression} )}}, aurgument value: {{( {key} , {array} )}}')

        return match['value']

    def eval_js(self, reactive_context: ReactContext, delimiter: str, args: List['Expression']) -> str:
        self.validate_args(args)

        key_expression = args[0]
        array_expression = args[1]

        key_js = key_expression.eval_js_and_hooks(reactive_context, delimiter)[0]
        array_js = array_expression.eval_js_and_hooks(reactive_context, delimiter)[0]

        return f'__reactive_match({key_js}, {array_js})'

ReactiveFunction.functions['matchKeyVal'] = MatchKeyValFunction()

from .expressions import *