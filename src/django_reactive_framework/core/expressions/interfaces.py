from abc import abstractmethod
from typing import Iterable, List, Optional, Tuple

from django import template

from ..base import ReactContext, ReactValType, ReactHook, ReactVar
from ..utils import sq

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
    def eval_initial(self, react_context: Optional['ReactContext']) -> ReactValType:
        """ Return the evaluated initial value """
        pass

    @abstractmethod
    def eval_js_and_hooks(self, react_context: Optional['ReactContext'], delimiter: str = sq) -> Tuple[str, List['ReactHook']]:
        """ Return a tupple of (js_expression, hooks) """
        pass

    def eval_js_html_output_and_hooks(self, react_context: Optional['ReactContext'], delimiter: str = sq) -> Tuple[str, List['ReactHook']]:
        """ Return a tupple of (js_html_output_expression, hooks) """
        val_js, hooks = self.eval_js_and_hooks(react_context, delimiter)
        
        return f'__reactive_print_html_unsafe({val_js})', hooks

class SettableExpression(Expression):
    @abstractmethod
    def js_set(self, react_context: Optional['ReactContext'], js_expression: str,
        expression_hooks: Iterable['ReactVar'] = []) -> str:

        """ Return the js expression for setting the self expression to the js_expression"""
        pass

    @abstractmethod
    def js_notify(self, react_context: Optional['ReactContext']) -> str:
        """ Return the js expression for notifying the self expression"""
        pass