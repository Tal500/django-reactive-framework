from abc import abstractmethod
from typing import Dict, List

from .base import ReactContext, ReactValType
from .utils import manual_non_empty_sum

class ReactiveBinaryOperator:
    operators: Dict[str, 'ReactiveBinaryOperator'] = dict()

    def validate_args(self, args: List['Expression']) -> None:
        if len(args) < 2:
            raise Exception(f'Internal Reactive Error: Not enough args for binary operator! Args: {args}')
    
    def eval_initial_from_values(self, vals: List[ReactValType]) -> ReactValType:
        pass

    def eval_js_from_js(self, js_expressions: List[str], delimiter: str) -> str:
        pass

    def eval_initial(self, reactive_context: ReactContext, args: List['Expression']) -> ReactValType:
        self.validate_args(args)
        
        vals = [arg.eval_initial(reactive_context) for arg in args]

        return self.eval_initial_from_values(vals)

    def eval_js(self, reactive_context: ReactContext, args: List['Expression'], delimiter: str) -> str:
        self.validate_args(args)
        
        vals = [arg.eval_js_and_hooks(reactive_context, delimiter)[0] for arg in args]

        return self.eval_js_from_js(vals, delimiter)

class StrictEqualityOperator(ReactiveBinaryOperator):
    def validate_args(self, args: List['Expression']) -> None:
        if len(args) != 2:
            raise template.TemplateSyntaxError(f'Strict equality operator must have exactly two args! Args: {args}')
    
    def eval_initial_from_values(self, vals: List[ReactValType]) -> ReactValType:
        lhs_val, rhs_val = vals

        result = lhs_val is rhs_val

        if not result and isinstance(lhs_val, str) and isinstance(rhs_val, str):
            result = (lhs_val == rhs_val)
        
        return result

    def eval_js_from_js(self, js_expressions: List[str], delimiter: str) -> str:
        lhs_js, rhs_js = js_expressions
        
        return f'({lhs_js}==={rhs_js})'

ReactiveBinaryOperator.operators['==='] = StrictEqualityOperator()

class StrictInequalityOperator(ReactiveBinaryOperator):
    def validate_args(self, args: List['Expression']) -> None:
        if len(args) != 2:
            raise template.TemplateSyntaxError(f'Strict inequality operator must have exactly two args! Args: {args}')
    
    def eval_initial_from_values(self, vals: List[ReactValType]) -> ReactValType:
        lhs_val, rhs_val = vals
        
        result = lhs_val is not rhs_val

        if result and isinstance(lhs_val, str) and isinstance(rhs_val, str):
            result = (lhs_val != rhs_val)
        
        return result

    def eval_js_from_js(self, js_expressions: List[str], delimiter: str) -> str:
        lhs_js, rhs_js = js_expressions
        return f'({lhs_js}!=={rhs_js})'

ReactiveBinaryOperator.operators['!=='] = StrictInequalityOperator()

class BoolComparingOperator(ReactiveBinaryOperator):
    @abstractmethod
    def eval_initial_from_values(self, vals: List[bool]) -> bool:
        pass

    def eval_initial(self, reactive_context: ReactContext, args: List['Expression']) -> bool:
        return super().eval_initial(reactive_context, args)

class AndOperator(BoolComparingOperator):
    def eval_initial_from_values(self, vals: List[bool]) -> bool:
        for val in vals:
            if val is False:
                return False
        # otherwise

        return True

    def eval_js_from_js(self, js_expressions: List[str], delimiter: str) -> str:
        return '&&'.join(js_expressions)

ReactiveBinaryOperator.operators['&&'] = AndOperator()

class OrOperator(BoolComparingOperator):
    def eval_initial_from_values(self, vals: List[bool]) -> bool:
        for val in vals:
            if val is True:
                return True
        # otherwise

        return False

    def eval_js_from_js(self, js_expressions: List[str], delimiter: str) -> str:
        return '||'.join(js_expressions)

ReactiveBinaryOperator.operators['||'] = OrOperator()

class NumberInequalityOperator(ReactiveBinaryOperator):
    @abstractmethod
    def eval_initial_from_two_values(self, lhs_val: int, rhs_val: int) -> bool:
        pass

    @abstractmethod
    def eval_js_from_two_js(self, lhs_js: List[str], rhs_js: List[str], delimiter: str) -> str:
        pass

    def validate_args(self, args: List['Expression']):
        super().validate_args(args)
        if len(args) != 2:
            raise template.TemplateSyntaxError(f'Number inequality operators must have exactly two args! Args: {args}')
        
    def eval_initial_from_values(self, vals: List[int]) -> bool:
        return self.eval_initial_from_two_values(vals[0], vals[1])
    
    def eval_js_from_js(self, js_expressions: List[str], delimiter: str) -> str:
        return self.eval_js_from_two_js(js_expressions[0], js_expressions[1], delimiter)

    def eval_initial(self, reactive_context: ReactContext, args: List['Expression']) -> bool:
        self.validate_args(args)
        
        vals = [arg.eval_initial(reactive_context) for arg in args]

        for i, val in enumerate(vals):
            if not isinstance(val, int):
                raise template.TemplateSyntaxError(f'Error: Argument {i} value isn\'t int in number inequality operator. ' + \
                    f'argument value: {val}, ' + f'argument expression: {args[i]}')

        return self.eval_initial_from_values(vals)

class GreaterOrEqualOperator(NumberInequalityOperator):
    def eval_initial_from_two_values(self, lhs_val: ReactValType, rhs_val: ReactValType) -> bool:
        return lhs_val >= rhs_val

    def eval_js_from_two_js(self, lhs_js: str, rhs_js: str, delimiter: str) -> str:
        return f'{lhs_js}>={rhs_js}'

ReactiveBinaryOperator.operators['>='] = GreaterOrEqualOperator()

class LessOrEqualOperator(NumberInequalityOperator):
    def eval_initial_from_two_values(self, lhs_val: ReactValType, rhs_val: ReactValType) -> bool:
        return lhs_val <= rhs_val

    def eval_js_from_two_js(self, lhs_js: str, rhs_js: str, delimiter: str) -> str:
        return f'{lhs_js}<={rhs_js}'

ReactiveBinaryOperator.operators['<='] = LessOrEqualOperator()

# Notice that >= and <= must be registered before > and <, for best matching

class GreaterOperator(NumberInequalityOperator):
    def eval_initial_from_two_values(self, lhs_val: int, rhs_val: int) -> bool:
        return lhs_val > rhs_val

    def eval_js_from_two_js(self, lhs_js: str, rhs_js: str, delimiter: str) -> str:
        return f'{lhs_js}>{rhs_js}'

ReactiveBinaryOperator.operators['>'] = GreaterOperator()

class LessOperator(NumberInequalityOperator):
    def eval_initial_from_value(self, lhs_val: ReactValType, rhs_val: ReactValType) -> bool:
        return lhs_val < rhs_val

    def eval_js_from_two_js(self, lhs_js: str, rhs_js: str, delimiter: str) -> str:
        return f'{lhs_js}<{rhs_js}'

ReactiveBinaryOperator.operators['<'] = LessOperator()

class SumOperator(ReactiveBinaryOperator):
    def eval_initial_from_values(self, vals: List[ReactValType]) -> ReactValType:
        return manual_non_empty_sum(vals)

    def eval_js_from_js(self, js_expressions: List[str], delimiter: str) -> str:
        return '+'.join(js_expressions)

ReactiveBinaryOperator.operators['+'] = SumOperator()

from .expressions import *