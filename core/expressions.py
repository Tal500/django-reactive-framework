from abc import abstractmethod
from typing import List, Optional, Tuple

from django import template

from ..core.base import ReactContext, ReactValType, ReactHook, ReactVar, value_to_expression

class Expression:
    """ An immutable structure for holding expressions. """

    @abstractmethod
    def reduce(self, template_context: template.Context):
        """ Return a reduced expression with template context variables subtituted. """
        pass

    @abstractmethod
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        """ Return the evaluated initial value """
        pass

    @abstractmethod
    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        """ Return a tupple of (js_expression, hooks) """
        pass
class SettableExpression(Expression):
    @abstractmethod
    def js_set(self, react_context: Optional[ReactContext], js_expression: str) -> str:
        """ Return the js expression for setting the self expression to the js_expression"""
        pass

class StringExpression(Expression):
    def __init__(self, val: str):
        self.val = val
    
    def reduce(self, template_context: template.Context):
        return self
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return self.val

    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        return f"'{self.val}'", []

class IntExpression(Expression):
    def __init__(self, val: int):
        self.val = val
    
    def reduce(self, template_context: template.Context):
        return self
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return self.val

    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        return str(self.val), []

class BoolExpression(Expression):
    def __init__(self, val: bool):
        self.val = val
    
    def reduce(self, template_context: template.Context):
        return self
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return self.val

    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        return 'true' if self.val else 'false', []
    
    @staticmethod
    def try_parse(expression: str) -> Optional[bool]:
        if expression == 'True' or expression == 'true':
            return BoolExpression(True)
        elif expression == 'False' or expression == 'false':
            return BoolExpression(False)
        else:
            return None

class ArrayExpression(Expression):
    def __init__(self, elements_expression: List[Expression]):
        self.elements_expression = elements_expression
    
    def reduce(self, template_context: template.Context):
        return ArrayExpression([expression.reduce(template_context) for expression in self.elements_expression])
    
    def eval_initial(self, react_context: Optional[ReactContext]) -> ReactValType:
        return [expression.eval_initial(react_context) for expression in self.elements_expression]

    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        js_expressions, all_hooks = [], []

        for expression in self.elements_expression:
            js_expression, hooks = expression.eval_js_and_hooks(react_context)

            js_expressions.append(js_expression)
            all_hooks.extend(hooks)
        
        return f'[{",".join((expression for expression in js_expressions))}]', all_hooks
    
    @staticmethod
    def try_parse(expression: str) -> Optional[List]:
        if not (len(expression) >= 2 and expression[0] == '[' and expression[-1]==']'):
            return None
        # otherwise

        expression = expression[1:-1]

        # TODO: Handle split by ',' inside string literal, etc.
        parts = expression.split(',')

        return ArrayExpression([parse_expression(part) for part in parts])

class VariableExpression(SettableExpression):
    def __init__(self, var_name):
        assert(" " not in var_name)
        self.var_name = var_name
    
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
            return var.expression.eval_initial(react_context)
        else:
            return ''

    def eval_js_and_hooks(self, react_context: Optional[ReactContext]) -> Tuple[str, List[ReactHook]]:
        var = self.var(react_context)

        if var:
            return var.js_get(), [var]
        else:
            return value_to_expression(''), []
    
    def js_set(self, react_context: Optional[ReactContext], js_expression: str):
        var = self.var(react_context)

        if var is None:
            raise template.TemplateSyntaxError('No reactive variable named %s was found' % self.var_name)

        return var.js_set(js_expression)

def remove_whitespaces_on_boundaries(s: str):
    for i in range(len(s)):
        if s[i] not in [' ', '\t', '\n']:
            break
    
    for j in reversed(range(i, len(s))):
        if s[j] not in [' ', '\t', '\n']:
            break
    
    return s[i:j+1]

def parse_expression(expression: str):
    expression = remove_whitespaces_on_boundaries(expression)

    # TODO: Support much more, and int expression (use regular expression?)
    
    if len(expression) >= 2 and expression[0] == expression[-1] and (expression[0] == "'" or expression[0] == "'"):
        return StringExpression(expression[1:-1])# TODO: escape characters!
    elif exp := BoolExpression.try_parse(expression):
        return exp
    elif exp := ArrayExpression.try_parse(expression):
        return exp
    else:
        return VariableExpression(expression)