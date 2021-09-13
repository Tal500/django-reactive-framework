from abc import abstractmethod
from itertools import chain
from typing import Any, Dict, Iterable, List, Optional, Tuple

from django import template

from .base import ReactContext, ReactData, ReactValType, ReactHook, ReactVar, value_js_representation, value_to_expression
from .reactive_function import ReactiveFunction
from .reactive_binary_operators import ReactiveBinaryOperator
from .reactive_unary_operators import ReactiveUnaryOperator
from .utils import manual_non_empty_sum, remove_whitespaces_on_boundaries, str_repr, str_repr_s, parse_string, smart_split, common_delimiters, sq

class Expression:
    """ An immutable structure for holding expressions. """

    def __repr__(self) -> str:
        return f'{super().__repr__()}({str(self)})'
    
    def __str__(self) -> str:
        return 'Expression'
    
    @property
    def constant(self) -> bool:
        return False

    @abstractmethod
    def reduce(self, template_context: template.Context) -> 'Expression':
        """ Return a reduced expression with template context variables subtituted. """
        pass

    @abstractmethod
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        """ Return the evaluated initial value """
        pass

    @abstractmethod
    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        """ Return a tupple of (js_expression, hooks) """
        pass

    def eval_js_html_output_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        """ Return a tupple of (js_html_output_expression, hooks) """
        val_js, hooks = self.eval_js_and_hooks(react_context, delimiter)
        
        # TODO: HTML escaping in this JS method?
        return f'__reactive_print_html({val_js})', hooks

class SettableExpression(Expression):
    @abstractmethod
    def js_set(self, react_context: Optional[ReactContext], js_expression: str,
        expression_hooks: Iterable[ReactVar] = []) -> str:

        """ Return the js expression for setting the self expression to the js_expression"""
        pass

    @abstractmethod
    def js_notify(self, react_context: Optional[ReactContext]) -> str:
        """ Return the js expression for notifying the self expression"""
        pass

class StringExpression(Expression):
    def __init__(self, val: str):
        self.val = val
    
    def __str__(self) -> str:
        return str_repr_s(self.val)
    
    @property
    def constant(self) -> bool:
        return True
    
    def reduce(self, template_context: template.Context):
        return self
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return self.val

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        return str_repr(self.val, delimiter), []

    def eval_js_html_output_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        # TODO: HTML escaping?
        return str_repr(self.val, delimiter), []
    
    @staticmethod
    def try_parse(expression: str) -> Optional['StringExpression']:
        if len(expression) >= 2 and expression[0] == expression[-1]:
            delimiter = expression[0]
            if (delimiter == "'" or delimiter == '"') and (result_str := parse_string(expression, delimiter)):
                return StringExpression(result_str)
        # otherwise
        
        return None

class IntExpression(Expression):
    def __init__(self, val: int):
        self.val = val
    
    def __str__(self) -> str:
        return f'{self.val}'
    
    @property
    def constant(self) -> bool:
        return True
    
    def reduce(self, template_context: template.Context):
        return self
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return self.val

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        return str(self.val), []

    def eval_js_html_output_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        return f'{delimiter}{self.val}{delimiter}', []
    
    @staticmethod
    def try_parse(expression: str) -> Optional['IntExpression']:
        if expression.isnumeric():
            return IntExpression(int(expression))
        else:
            return None

class BoolExpression(Expression):
    def __init__(self, val: bool):
        self.val = val
    
    def __str__(self) -> str:
        return f'{self.val}'
    
    @property
    def constant(self) -> bool:
        return True
    
    def reduce(self, template_context: template.Context):
        return self
    
    def eval_initial(self, react_context: Optional[ReactContext], delimiter: str = sq) -> ReactValType:
        return self.val

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        return 'true' if self.val else 'false', []

    def eval_js_html_output_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        return f"'{str(self.val)}'"
    
    @staticmethod
    def try_parse(expression: str) -> Optional['BoolExpression']:
        if expression == 'True' or expression == 'true':
            return BoolExpression(True)
        elif expression == 'False' or expression == 'false':
            return BoolExpression(False)
        else:
            return None

class NoneExpression(Expression):
    def __init__(self):
        pass
    
    def __str__(self) -> str:
        return f'None'
    
    @property
    def constant(self) -> bool:
        return True
    
    def reduce(self, template_context: template.Context):
        return self
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return None

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        return 'null', []

    def eval_js_html_output_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        return f"'None'"
    
    @staticmethod
    def try_parse(expression: str) -> Optional['NoneExpression']:
        if expression == 'None' or expression == 'null':
            return NoneExpression()
        else:
            return None

class ArrayExpression(Expression):
    def __init__(self, elements_expression: List[Expression]):
        self.elements_expression: List[Expression] = elements_expression
    
    def __str__(self) -> str:
        return f'[{", ".join(str(expression) for expression in self.elements_expression)}]'
    
    @property
    def constant(self) -> bool:
        for element in self.elements_expression:
            if not element.constant:
                return False
        # otherwise

        return True
    
    def reduce(self, template_context: template.Context):
        return ArrayExpression([expression.reduce(template_context) for expression in self.elements_expression])
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return [expression.eval_initial(react_context) for expression in self.elements_expression]

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        js_expressions, all_hooks = [], []

        for expression in self.elements_expression:
            js_expression, hooks = expression.eval_js_and_hooks(react_context, delimiter)

            js_expressions.append(js_expression)
            all_hooks.extend(hooks)
        
        return f'[{",".join((expression for expression in js_expressions))}]', all_hooks
    
    @staticmethod
    def try_parse(expression: str) -> Optional['ArrayExpression']:
        if not (len(expression) >= 2 and expression[0] == '[' and expression[-1]==']'):
            return None
        # otherwise

        expression = expression[1:-1]

        parts = smart_split(expression, [','], common_delimiters, skip_blank=False)

        return ArrayExpression([parse_expression(part) for part in parts])

class DictExpression(Expression):
    def __init__(self, dict_expression: Dict[str, Expression]):
        self.dict_expression = dict_expression
        self.has_react_data = False

        for key, expression in self.dict_expression.items():
            if isinstance(expression, NewReactDataExpression):
                self.has_react_data = True
                break
    
    def __str__(self) -> str:
        return f'{{{",".join((f"{key}:{str(expression)}" for key, expression in self.dict_expression.items()))}}}'
    
    @property
    def constant(self) -> bool:
        for key, expression in self.dict_expression.items():
            if not expression.constant:
                return False
        # otherwise

        return True
    
    def reduce(self, template_context: template.Context):
        return DictExpression({key: expression.reduce(template_context) for key, expression in self.dict_expression.items()})
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return {key: expression.eval_initial(react_context) for key, expression in self.dict_expression.items()}

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        key_js_expressions, all_hooks = [], []

        for key, expression in self.dict_expression.items():
            js_expression, hooks = expression.eval_js_and_hooks(react_context, delimiter)

            key_js_expressions.append((key, js_expression))
            all_hooks.extend(hooks)
        
        if self.has_react_data:
            js_result = \
                '( () => {\n'+ \
                    ''.join(f'const {key}={js_expression};\n' for key, js_expression in key_js_expressions) + \
                    'return {' + \
                        ','.join((f'{key}:{key}' for key, js_expression in key_js_expressions)) + \
                    '};\n' + \
                '} )()'
        else:
            js_result = f'{{{",".join((f"{key}:{js_expression}" for key, js_expression in key_js_expressions))}}}'
        
        return js_result, all_hooks
    
    @staticmethod
    def try_parse(expression: str) -> Optional['DictExpression']:
        if not (len(expression) >= 2 and expression[0] == '{' and expression[-1]=='}'):
            return None
        # otherwise

        expression = expression[1:-1]

        parts = smart_split(expression, [','], common_delimiters, skip_blank=False)

        def split_part(part: str) -> Tuple[str, Expression]:
            seperator = part.find(':')
            if seperator == -1:
                raise template.TemplateSyntaxError("Can't find key-value seperator ':'")

            key = remove_whitespaces_on_boundaries(part[:seperator])
            val_str = part[seperator+1:]

            if key_expression := StringExpression.try_parse(key):
                key = key_expression.val

            return key, parse_expression(val_str)

        try:
            return DictExpression(dict(split_part(part) for part in parts))
        except:
            return None

class VariableExpression(SettableExpression):
    def __init__(self, var_name: str):
        assert(" " not in var_name)
        self.var_name = var_name
    
    def __str__(self):
        return self.var_name
    
    def reduce(self, template_context: template.Context):
        if self.var_name in template_context:
            val = template_context[self.var_name]
            return value_to_expression(val)
        else:
            return self
    
    def var(self, react_context: Optional[ReactContext]) -> Optional[ReactVar]:
        if react_context is None:
            raise Exception("Can't evaluate a VariableExpression if react_context=None")
        # otherwise

        # Notice: Might return none which means that the variable isn't registered as reactive variable.
        return react_context.search_var(self.var_name)
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        var = self.var(react_context)

        if var:
            return var.eval_initial(react_context)
        else:
            return ''

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        var = self.var(react_context)
        parent_vars = [var for var in react_context.parent.vars]

        if var:
            return var.js_get(), [var]
        else:
            return value_to_expression('').eval_js_and_hooks(react_context, delimiter)
    
    def js_set(self, react_context: Optional[ReactContext], js_expression: str,
        expression_hooks: Iterable[ReactVar] = []) -> str:

        var = self.var(react_context)

        if var is None:
            raise template.TemplateSyntaxError('No reactive variable named %s was found' % self.var_name)

        return var.js_set(js_expression, expression_hooks=expression_hooks)
    
    def js_notify(self, react_context: Optional[ReactContext]) -> str:
        var = self.var(react_context)

        if var is None:
            raise template.TemplateSyntaxError('No reactive variable named %s was found' % self.var_name)

        return var.js_notify()
    
    @staticmethod
    def try_parse(expression: str) -> Optional['VariableExpression']:
        if expression.isidentifier():
            return VariableExpression(expression)
        else:
            return None

class NativeVariableExpression(SettableExpression):
    def __init__(self, var_name: str, initial_value: Any = None):
        assert(" " not in var_name)
        self.var_name = var_name
        self.initial_value = initial_value
    
    def __str__(self):
        return self.var_name
    
    def reduce(self, template_context: template.Context):
        return self
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return self.initial_value

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        return self.var_name, []
    
    def js_set(self, react_context: Optional[ReactContext], js_expression: str,
        expression_hooks: Iterable[ReactVar] = []) -> str:

        return f'{self.var_name}={js_expression};'
    
    def js_notify(self, react_context: Optional[ReactContext]) -> str:
        return ''

class PropertyExpression(Expression):
    def __init__(self, root_expression: Expression, key_path: List[str]):
        # TODO: Support also "[]" and not only "."

        assert(key_path)

        self.root_expression: Expression = root_expression
        self.key_path: List[str] = key_path
    
    def __str__(self):
        return '(' + str(self.root_expression) + ').' + '.'.join(self.key_path)
    
    @property
    def constant(self) -> bool:
        return self.root_expression.constant
    
    def reduce(self, template_context: template.Context):
        root_expression_reduced = self.root_expression.reduce(template_context)
        
        return PropertyExpression(root_expression_reduced, self.key_path)
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        root_val = self.root_expression.eval_initial(react_context)

        current: ReactValType = root_val

        for key in self.key_path:
            if key in current:
                current = current[key]
            else:
                raise template.TemplateSyntaxError(f"Error while evaluating expression initial value of {self}: " +\
                    f"There is no key named '{key}' in {{{current}}}. " + \
                    f"Root expression: {{{self.root_expression}}} val: {{{root_val}}}.")
        
        return current

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        root_var_js, hooks = self.root_expression.eval_js_and_hooks(react_context, delimiter)

        return '(' + root_var_js + ').' + '.'.join(self.key_path), hooks
    
    @staticmethod
    def try_parse(expression: str) -> Optional['PropertyExpression']:
        parts = list(smart_split(expression, ['.'], common_delimiters, skip_blank=False))

        if len(parts) <= 1:
            return None
        # otherwise

        root_expression = parse_expression(parts[0])
        if root_expression is None:
            return None
        # otherwise

        key_path = parts[1:]
        for key in key_path:
            if key is None or (not key.isidentifier()):
                return None
        # otherwise
        
        if isinstance(root_expression, SettableExpression):
            return SettablePropertyExpression(root_expression, key_path)
        else:
            return PropertyExpression(root_expression, key_path)

class SettablePropertyExpression(PropertyExpression, SettableExpression):
    def __init__(self, root_expression: SettableExpression, key_path: List[str]):
        super().__init__(root_expression, key_path)
    
    def __str__(self):
        return str(self.root_expression) + '.' + '.'.join(self.key_path)
    
    def reduce(self, template_context: template.Context):
        root_expression_reduced = self.root_expression.reduce(template_context)
        
        return SettablePropertyExpression(root_expression_reduced, self.key_path)
    
    def js_set(self, react_context: Optional[ReactContext], js_expression: str,
        expression_hooks: Iterable[ReactVar] = []) -> str:

        js_path_expression = self.eval_js_and_hooks(react_context)[0]

        return f'{js_path_expression} = {js_expression}; ' + self.js_notify(react_context)
    
    def js_notify(self, react_context: Optional[ReactContext]) -> str:
        settable_expression: SettableExpression = self.root_expression
        return settable_expression.js_notify(react_context)

class TernaryOperatorExpression(Expression):
    def __init__(self, condition: Expression, expression_if_true: Expression, expression_if_false: Expression):
        self.condition = condition
        self.expression_if_true = expression_if_true
        self.expression_if_false = expression_if_false
    
    def __str__(self) -> str:
        return f'({self.condition}?{self.expression_if_true}:{self.expression_if_false})'
    
    def eval_condition_initial(self, react_context: Optional[ReactContext]) -> bool:
        condition_val = self.condition.eval_initial(react_context)

        if not isinstance(condition_val, bool):
            raise template.TemplateSyntaxError('The initial value of a condition is not boolean!')
        # otherwise

        return condition_val
    
    @property
    def constant(self) -> bool:
        if not self.condition.constant:
            return False
        # otherwise

        if self.eval_condition_initial(None):
            return self.expression_if_true.constant
        else:
            return self.expression_if_false.constant
    
    def reduce(self, template_context: template.Context):
        return TernaryOperatorExpression(self.condition, self.expression_if_true, self.expression_if_false)
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        if self.eval_condition_initial(react_context):
            return self.expression_if_true.eval_initial(react_context)
        else:
            return self.expression_if_false.eval_initial(react_context)

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        if self.condition.constant:
            if self.eval_condition_initial(None):
                return self.expression_if_true.eval_js_and_hooks(react_context, delimiter)
            else:
                return self.expression_if_false.eval_js_and_hooks(react_context, delimiter)
        # otherwise

        condition_js, condition_hooks = self.condition.eval_js_and_hooks(react_context, delimiter)

        true_js, true_hooks = self.expression_if_true.eval_js_and_hooks(react_context, delimiter)

        false_js, false_hooks = self.expression_if_false.eval_js_and_hooks(react_context, delimiter)

        all_hooks = list(chain(condition_hooks, true_hooks, false_hooks))
        
        return f'({condition_js}?{true_js}:{false_js})', all_hooks
    
    @staticmethod
    def try_parse(expression: str) -> Optional['TernaryOperatorExpression']:
        parts1 = list(smart_split(expression, ('?',)))
        if len(parts1) < 2:
            return None
        elif len(parts1) > 2:
            raise template.TemplateSyntaxError(
                f'Error when parsing ternary expression: too many \'?\'. Expression: ({expression})')
        # otherwise (len(parts1) == 2)

        condition_str, rest_str = parts1

        parts2 = list(smart_split(rest_str, (':',)))
        if len(parts2) < 2:
            raise template.TemplateSyntaxError(
                f'Error when parsing ternary expression: found \'?\' but no \':\'. Expression: ({expression})')
        elif len(parts2) > 2:
            raise template.TemplateSyntaxError(
                f'Error when parsing ternary expression: too many \':\' after \'?\'. Expression: ({expression})')
        # otherwise (len(parts2) == 2)
        
        true_str, false_str = parts2

        condition = parse_expression(condition_str)
        if condition is None:
            raise template.TemplateSyntaxError(
                f'Error when parsing ternary expression: fail to parse the condition expression: ({condition_str})')

        expression_if_true = parse_expression(true_str)
        if expression_if_true is None:
            raise template.TemplateSyntaxError(
                f'Error when parsing ternary expression: fail to parse the if true expression: ({true_str})')

        expression_if_false = parse_expression(false_str)
        if expression_if_false is None:
            raise template.TemplateSyntaxError(
                f'Error when parsing ternary expression: fail to parse the if false expression: ({false_str})')

        return TernaryOperatorExpression(condition, expression_if_true, expression_if_false)

class FunctionCallExpression(Expression):
    def __init__(self, name: str, function: ReactiveFunction, args: List[Expression]):
        self.name = name
        self.function = function
        self.args = args

        function.validate_args(args)
    
    def __str__(self) -> str:
        return f'{self.name}({",".join(str(arg) for arg in self.args)})'
    
    def reduce(self, template_context: template.Context):
        args_reduced = [arg.reduce(template_context) for arg in self.args]
        return FunctionCallExpression(self.name, self.function, args_reduced)

    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return self.function.eval_initial(react_context, self.args)

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        return self.function.eval_js_and_hooks(react_context, delimiter, self.args)
    
    @staticmethod
    def try_parse(expression: str) -> Optional['FunctionCallExpression']:
        parts = list(smart_split(expression, ('(',), skip_blank=False))
        if len(parts) < 2:
            return None
        elif len(parts) > 2:
            raise template.TemplateSyntaxError(
                f'Error when parsing function call expression: too many \'(\' without enough closing \')\'. ' + \
                f'Expression: ({expression})')
        # otherwise (len(parts1) == 2)

        function_name, rest_str = parts

        function_name = remove_whitespaces_on_boundaries(function_name)

        if not function_name:
            return None# It might be just a regular parentheses expression
        
        if not rest_str or rest_str[-1] != ')':
            return None# might be another expression

        if not function_name.isidentifier():
            return None# might be another expression
        
        function = ReactiveFunction.functions.get(function_name)

        if function is None:
            raise template.TemplateSyntaxError(
                f'Error when parsing function call expression: the reactive function \'{function_name}\' doesn\'t exist! ' + \
                f'Expression: ({expression})')
        
        
        args_str = rest_str[:-1]
        args = [parse_expression(arg_str) for arg_str in smart_split(args_str, (',',), skip_blank=True)]

        return FunctionCallExpression(function_name, function, args)

class BinaryOperatorExpression(Expression):
    def __init__(self, operator_symbol: str, operator: ReactiveBinaryOperator, args: List[Expression]):
        self.operator_symbol = operator_symbol
        self.operator = operator
        self.args = args

        operator.validate_args(args)
    
    def __str__(self) -> str:
        return self.operator_symbol.join(str(arg) for arg in self.args)
    
    @property
    def constant(self) -> bool:
        for arg in self.args:
            if not arg.constant:
                return False
        # otherwise

        return True
    
    def reduce(self, template_context: template.Context):
        args_reduced = [arg.reduce(template_context) for arg in self.args]
        return BinaryOperatorExpression(self.operator_symbol, self.operator, args_reduced)

    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return self.operator.eval_initial(react_context, self.args)
    
    def optimized_args(self):
        # Optimize it to what is needed

        def calc_args_initial_expression(args: List[Expression]) -> Expression:
            if len(args) == 0:
                raise Exception('Internal reactive error: Locally optimized args for binary expression is 0')
            elif len(args) == 1:
                return args[0]
            else:
                return value_to_expression(self.operator.eval_initial(None, args))

        optimized_arg_list = []
        current_args = []
        
        for arg in self.args:
            if arg.constant:
                current_args.append(arg)
            else:
                if current_args:
                    optimized_arg_list.append(calc_args_initial_expression(current_args))
                    current_args = []
                
                optimized_arg_list.append(arg)
        
        # Add the last part (if any)
        if current_args:
            optimized_arg_list.append(calc_args_initial_expression(current_args))
        
        return optimized_arg_list

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        optimized_args = self.optimized_args()

        if len(optimized_args) == 0:
            raise Exception('Internal reactive error: Optimized args for binary expression is 0')
        elif len(optimized_args) == 1:
            return optimized_args[0].eval_js_and_hooks(react_context, delimiter)
        # otherwise

        js_expression = self.operator.eval_js(react_context, optimized_args, delimiter)

        all_hooks = list(chain.from_iterable(arg.eval_js_and_hooks(react_context)[1] for arg in optimized_args))
        
        return js_expression, all_hooks
    
    @staticmethod
    def try_parse(expression: str) -> Optional['BinaryOperatorExpression']:
        operator_found = None
        for symbol, operator in ReactiveBinaryOperator.operators.items():
            parts = list(smart_split(expression, (symbol,), skip_blank=False))
            if len(parts) >= 2:
                operator_found = operator
                break

        if operator_found is None:
            return None
        # otherwise

        arg_strings = [remove_whitespaces_on_boundaries(arg_str) for arg_str in parts]

        for i, arg_str in enumerate(arg_strings):
            if not arg_str:
                raise template.TemplateSyntaxError(
                    f'Error while parsing binary operator expression: Argument {i} is empty. ' + \
                    f'Expression: ({expression})')
        
        args = [parse_expression(arg) for arg in arg_strings]

        return BinaryOperatorExpression(symbol, operator, args)

# An alias for BinaryOperatorExpression with operator SumOperator
class SumExpression(BinaryOperatorExpression):
    def __init__(self, args: List[Expression]):
        super().__init__('+', ReactiveBinaryOperator.operators['+'], args)
    
    @staticmethod
    def sum_expressions(args: List[Expression]) -> Expression:
        if len(args) == 1:
            return args[0]
        else:
            return SumExpression(args)

class UnaryOperatorExpression(Expression):
    def __init__(self, operator_symbol: str, operator: ReactiveUnaryOperator, arg: Expression):
        self.operator_symbol = operator_symbol
        self.operator = operator
        self.arg = arg

        operator.validate_arg(arg)
    
    def __str__(self) -> str:
        return f'{self.operator_symbol}{self.arg}'
    
    @property
    def constant(self) -> bool:
        return self.arg.constant
    
    def reduce(self, template_context: template.Context):
        arg_reduced = self.arg.reduce(template_context)
        return UnaryOperatorExpression(self.operator_symbol, self.operator, arg_reduced)

    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return self.operator.eval_initial(react_context, self.arg)

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        if self.constant:
            return value_js_representation(self.eval_initial(react_context), react_context, delimiter=delimiter), []
        # otherwise

        js_expression = self.operator.eval_js(react_context, self.arg, delimiter)

        hooks = self.arg.eval_js_and_hooks(react_context)[1]
        
        return js_expression, hooks
    
    @staticmethod
    def try_parse(expression: str) -> Optional['UnaryOperatorExpression']:
        operator_found = None
        for symbol, operator in ReactiveUnaryOperator.operators.items():
            if expression.startswith(symbol):
                operator_found = operator
                expression = expression[len(symbol):]
                break

        if operator_found is None:
            return None
        # otherwise

        arg = parse_expression(expression)

        return UnaryOperatorExpression(symbol, operator, arg)

# This expression type is used only internally, and the user can't create it manually.
class NewReactDataExpression(Expression):
    def __init__(self, data: ReactData):
        self.data: ReactData = data
    
    def __str__(self):
        return f'NewReactDataExpression(data={self.data})'
    
    def reduce(self, template_context: template.Context):
        return self
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactData:
        return self.data

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        return self.data.initial_val_js(react_context, delimiter=delimiter), []

# TODO: Support also escaping '/' (if needed)
class EscapingContainerExpression(Expression):
    def __init__(self, inner_expression: Expression, delimiter: str):
        self.inner_expression: Expression = inner_expression
        self.delimiter: str = delimiter
    
    @property
    def constant(self) -> bool:
        return self.inner_expression.constant
    
    def __str__(self) -> str:
        return f'Escaping-{self.delimiter}({self.inner_expression})'
    
    def reduce(self, template_context: template.Context):
        return EscapingContainerExpression(self.inner_expression.reduce(template_context), self.delimiter)
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> str:
        return str(self.inner_expression.eval_initial(react_context)) \
            .translate(str.maketrans({self.delimiter: '\\' + self.delimiter}))

    def eval_js_and_hooks(self, react_context: Optional[ReactContext], delimiter: str = sq) -> Tuple[str, List[ReactHook]]:
        inner_js_expression, hooks = self.inner_expression.eval_js_and_hooks(react_context)

        delimiter_escaped = self.delimiter if self.delimiter!=delimiter else ("\\"+delimiter)

        js_expression = f'({inner_js_expression}).toString().replace(/{delimiter_escaped}/g, {str_repr(delimiter_escaped, delimiter)})'
        
        return js_expression, hooks

def parse_expression(expression: str):
    expression = remove_whitespaces_on_boundaries(expression)

    is_parentheses = False
    if expression[0] == '(' and expression[-1] == ')':
        parts = list(smart_split(expression[1:], [')'], skip_blank=False))
        if len(parts) == 2 and not parts[1]:
            is_parentheses = True
    
    if is_parentheses:
        return parse_expression(expression[1:-1])
    elif exp := TernaryOperatorExpression.try_parse(expression):
        return exp
    elif exp := StringExpression.try_parse(expression):
        return exp
    elif exp := BoolExpression.try_parse(expression):
        return exp
    elif exp := IntExpression.try_parse(expression):
        return exp
    elif exp := NoneExpression.try_parse(expression):
        return exp
    elif exp := ArrayExpression.try_parse(expression):
        return exp
    elif exp := DictExpression.try_parse(expression):
        return exp
    elif exp := VariableExpression.try_parse(expression):
        return exp
    elif exp := PropertyExpression.try_parse(expression):
        return exp
    elif exp := UnaryOperatorExpression.try_parse(expression):
        return exp
    elif exp := BinaryOperatorExpression.try_parse(expression):
        return exp
    elif exp := FunctionCallExpression.try_parse(expression):
        return exp
    else:
        raise template.TemplateSyntaxError(f"Can't parse expression: ({expression})")