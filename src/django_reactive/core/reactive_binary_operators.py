from abc import abstractmethod
from typing import Dict

from .base import ReactContext, ReactValType

class ReactiveBinaryOperator:
    operators: Dict[str, 'ReactiveBinaryOperator'] = dict()

    def validate_args(self, lhs: 'Expression', rhs: 'Expression') -> None:
        pass
    
    def eval_initial_from_value(self, lhs_val: ReactValType, rhs_val: ReactValType) -> ReactValType:
        pass

    def eval_js_from_js(self, lhs_js: str, rhs_js: str, delimiter: str) -> str:
        pass

    def eval_initial(self, reactive_context: ReactContext, lhs: 'Expression', rhs: 'Expression') -> ReactValType:
        self.validate_args(lhs, rhs)
        
        lhs_val = lhs.eval_initial(reactive_context)
        rhs_val = rhs.eval_initial(reactive_context)

        return self.eval_initial_from_value(lhs_val, rhs_val)

    def eval_js(self, reactive_context: ReactContext, delimiter: str, lhs: 'Expression', rhs: 'Expression') -> str:
        self.validate_args(lhs, rhs)
        
        lhs_val = lhs.eval_js_and_hooks(reactive_context, delimiter)[0]
        rhs_val = rhs.eval_js_and_hooks(reactive_context, delimiter)[0]

        return self.eval_js_from_js(lhs_val, rhs_val, delimiter)

class StrictEqualityOperator(ReactiveBinaryOperator):
    def eval_initial_from_value(self, lhs_val: ReactValType, rhs_val: ReactValType) -> ReactValType:
        result = lhs_val is rhs_val

        if not result and isinstance(lhs_val, str) and isinstance(rhs_val, str):
            result = (lhs_val == rhs_val)
        
        return result

    def eval_js_from_js(self, lhs_js: str, rhs_js: str, delimiter: str) -> str:
        return f'({lhs_js}==={rhs_js})'

ReactiveBinaryOperator.operators['==='] = StrictEqualityOperator()

class StrictInequalityOperator(ReactiveBinaryOperator):
    def eval_initial_from_value(self, lhs_val: ReactValType, rhs_val: ReactValType) -> ReactValType:
        result = lhs_val is not rhs_val

        if result and isinstance(lhs_val, str) and isinstance(rhs_val, str):
            result = (lhs_val != rhs_val)
        
        return result

    def eval_js_from_js(self, lhs_js: str, rhs_js: str, delimiter: str) -> str:
        return f'({lhs_js}!=={rhs_js})'

ReactiveBinaryOperator.operators['!=='] = StrictInequalityOperator()

class BoolComparingOperator(ReactiveBinaryOperator):
    @abstractmethod
    def eval_initial_from_value(self, lhs_val: bool, rhs_val: bool) -> bool:
        pass

    def eval_initial(self, reactive_context: ReactContext, lhs: 'Expression', rhs: 'Expression') -> bool:
        self.validate_args(lhs, rhs)
        
        lhs_val = lhs.eval_initial(reactive_context)
        rhs_val = rhs.eval_initial(reactive_context)

        if not isinstance(lhs_val, bool):
            raise template.TemplateSyntaxError('Error: lhs value isn\'t bool in bool comparing operator')

        if not isinstance(rhs_val, bool):
            raise template.TemplateSyntaxError('Error: rhs value isn\'t bool in bool comparing operator')

        return self.eval_initial_from_value(lhs_val, rhs_val)

class AndOperator(BoolComparingOperator):
    def eval_initial_from_value(self, lhs_val: ReactValType, rhs_val: ReactValType) -> bool:
        return lhs_val and rhs_val

    def eval_js_from_js(self, lhs_js: str, rhs_js: str, delimiter: str) -> str:
        return f'{lhs_js}&&{rhs_js}'

ReactiveBinaryOperator.operators['&&'] = AndOperator()

class OrOperator(BoolComparingOperator):
    def eval_initial_from_value(self, lhs_val: ReactValType, rhs_val: ReactValType) -> bool:
        return lhs_val or rhs_val

    def eval_js_from_js(self, lhs_js: str, rhs_js: str, delimiter: str) -> str:
        return f'{lhs_js}||{rhs_js}'

ReactiveBinaryOperator.operators['||'] = OrOperator()

class NumberInequalityOperator(ReactiveBinaryOperator):
    @abstractmethod
    def eval_initial_from_value(self, lhs_val: int, rhs_val: int) -> bool:
        pass

    def eval_initial(self, reactive_context: ReactContext, lhs: 'Expression', rhs: 'Expression') -> bool:
        self.validate_args(lhs, rhs)
        
        lhs_val = lhs.eval_initial(reactive_context)
        rhs_val = rhs.eval_initial(reactive_context)

        if not isinstance(lhs_val, int):
            raise template.TemplateSyntaxError('Error: lhs value isn\'t number in number inequality operator')

        if not isinstance(rhs_val, int):
            raise template.TemplateSyntaxError('Error: rhs value isn\'t number in number inequality operator')

        return self.eval_initial_from_value(lhs_val, rhs_val)

class GreaterOperator(NumberInequalityOperator):
    def eval_initial_from_value(self, lhs_val: ReactValType, rhs_val: ReactValType) -> bool:
        return lhs_val > rhs_val

    def eval_js_from_js(self, lhs_js: str, rhs_js: str, delimiter: str) -> str:
        return f'{lhs_js}>{rhs_js}'

ReactiveBinaryOperator.operators['>'] = GreaterOperator()

class LessOperator(NumberInequalityOperator):
    def eval_initial_from_value(self, lhs_val: ReactValType, rhs_val: ReactValType) -> bool:
        return lhs_val < rhs_val

    def eval_js_from_js(self, lhs_js: str, rhs_js: str, delimiter: str) -> str:
        return f'{lhs_js}<{rhs_js}'

ReactiveBinaryOperator.operators['<'] = LessOperator()

class GreaterOrEqualOperator(NumberInequalityOperator):
    def eval_initial_from_value(self, lhs_val: ReactValType, rhs_val: ReactValType) -> bool:
        return lhs_val >= rhs_val

    def eval_js_from_js(self, lhs_js: str, rhs_js: str, delimiter: str) -> str:
        return f'{lhs_js}>={rhs_js}'

ReactiveBinaryOperator.operators['>='] = GreaterOrEqualOperator()

class LessOrEqualOperator(NumberInequalityOperator):
    def eval_initial_from_value(self, lhs_val: ReactValType, rhs_val: ReactValType) -> bool:
        return lhs_val <= rhs_val

    def eval_js_from_js(self, lhs_js: str, rhs_js: str, delimiter: str) -> str:
        return f'{lhs_js}<={rhs_js}'

ReactiveBinaryOperator.operators['<='] = LessOrEqualOperator()

from .expressions import *