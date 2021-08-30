from abc import abstractmethod
from typing import Dict

from .base import ReactContext, ReactValType

class ReactiveBinaryOperator:
    operators: Dict[str, 'ReactiveBinaryOperator'] = dict()

    def validate_args(self, lhs: 'Expression', rhs: 'Expression') -> None:
        pass

    @abstractmethod
    def eval_initial(self, reactive_context: ReactContext, lhs: 'Expression', rhs: 'Expression') -> ReactValType:
        pass

    @abstractmethod
    def eval_js(self, reactive_context: ReactContext, delimiter: str, lhs: 'Expression', rhs: 'Expression') -> str:
        pass

class StrictEqualityOperator(ReactiveBinaryOperator):
    def eval_initial(self, reactive_context: ReactContext, lhs: 'Expression', rhs: 'Expression') -> ReactValType:
        self.validate_args(lhs, rhs)
        
        lhs_val = lhs.eval_initial(reactive_context)
        rhs_val = rhs.eval_initial(reactive_context)

        result = lhs_val is rhs_val

        if not result and isinstance(lhs_val, str) and isinstance(rhs_val, str):
            result = (lhs_val == rhs_val)
        
        return result

    def eval_js(self, reactive_context: ReactContext, delimiter: str, lhs: 'Expression', rhs: 'Expression') -> str:
        self.validate_args(lhs, rhs)
        
        lhs_val = lhs.eval_js_and_hooks(reactive_context)[0]
        rhs_val = rhs.eval_js_and_hooks(reactive_context)[0]

        return f'({lhs_val}==={rhs_val})'

ReactiveBinaryOperator.operators['==='] = StrictEqualityOperator()

class StrictInequalityOperator(ReactiveBinaryOperator):
    def eval_initial(self, reactive_context: ReactContext, lhs: 'Expression', rhs: 'Expression') -> ReactValType:
        self.validate_args(lhs, rhs)
        
        lhs_val = lhs.eval_initial(reactive_context)
        rhs_val = rhs.eval_initial(reactive_context)

        result = lhs_val is not rhs_val

        if result and isinstance(lhs_val, str) and isinstance(rhs_val, str):
            result = (lhs_val != rhs_val)
        
        return result

    def eval_js(self, reactive_context: ReactContext, delimiter: str, lhs: 'Expression', rhs: 'Expression') -> str:
        self.validate_args(lhs, rhs)
        
        lhs_val = lhs.eval_js_and_hooks(reactive_context)[0]
        rhs_val = rhs.eval_js_and_hooks(reactive_context)[0]

        return f'({lhs_val}!=={rhs_val})'

ReactiveBinaryOperator.operators['!=='] = StrictInequalityOperator()

from .expressions import *