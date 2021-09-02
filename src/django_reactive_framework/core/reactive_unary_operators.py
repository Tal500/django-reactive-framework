from typing import Dict

from .base import ReactContext, ReactValType

class ReactiveUnaryOperator:
    operators: Dict[str, 'ReactiveUnaryOperator'] = dict()

    def validate_arg(self, arg: 'Expression') -> None:
        pass
    
    def eval_initial_from_value(self, val: ReactValType) -> ReactValType:
        pass

    def eval_js_from_js(self, js_expressions: str, delimiter: str) -> str:
        pass

    def eval_initial(self, reactive_context: ReactContext, arg: 'Expression') -> ReactValType:
        self.validate_arg(arg)
        
        val = arg.eval_initial(reactive_context)

        return self.eval_initial_from_value(val)

    def eval_js(self, reactive_context: ReactContext, arg: 'Expression', delimiter: str) -> str:
        self.validate_arg(arg)
        
        js_expression = arg.eval_js_and_hooks(reactive_context, delimiter)[0]

        return self.eval_js_from_js(js_expression, delimiter)

class LogicalNotOperator(ReactiveUnaryOperator):
    def eval_initial_from_value(self, val: ReactValType) -> ReactValType:
        if not isinstance(val, bool):
            raise template.TemplateSyntaxError('Cannot do logical not for non-bool value. ' + \
                f'value: {val}')
        # otherwise

        return not val

    def eval_js_from_js(self, js_expressions: str, delimiter: str) -> str:
        return f'!{js_expressions}'

ReactiveUnaryOperator.operators['!'] = LogicalNotOperator()

from .expressions import *