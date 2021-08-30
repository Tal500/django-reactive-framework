from abc import abstractmethod
from typing import List

from django import template

from .base import ReactContext, ReactValType

class ReactiveFunction:
    functions = dict()

    def validate_args(self, args: List['Expression']) -> None:
        pass

    @abstractmethod
    def eval_initial(self, reactive_context: ReactContext, args: List['Expression']) -> ReactValType:
        pass

    @abstractmethod
    def eval_js(self, reactive_context: ReactContext, delimiter: str, args: List['Expression']) -> str:
        pass

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

from .expressions import *