from abc import abstractmethod
from typing import Dict, Iterable, List, Optional, Set, Union, Tuple

from itertools import chain
import uuid

from pathlib import Path

from django import template
from django.utils.html import escapejs
from django.utils.safestring import mark_safe

from .utils import sq

count_str = 'react_currect_count'
count_reactcontent_str = 'currect_reactcontent_count'

def next_id_by_context(context: template.Context, type_identifier: str) -> int:
    if not context.get(type_identifier):
        context[type_identifier] = 0
    
    currect = context[type_identifier]
    context[type_identifier] = currect + 1

    return currect

def value_to_expression(val):
    if isinstance(val, ReactData):
        return NewReactDataExpression(val)
    elif isinstance(val, str):
        return StringExpression(val)
    elif isinstance(val, bool):
        return BoolExpression(val)
    elif isinstance(val, int):
        return IntExpression(val)
    elif isinstance(val, float):
        return FloatExpression(val)
    elif val is None:
        return NoneExpression()
    elif isinstance(val, list):
        return ArrayExpression([value_to_expression(element) for element in val])
    elif isinstance(val, dict):
        return DictExpression({str(key): value_to_expression(_val) for key, _val in val.items()})
    else:
        raise template.TemplateSyntaxError(
            "Currently the only types supported are string, bool, int, float, none, arrays and dictionaries for reactive variables values.")

# One may be attempt to think that react_context is useless, but it's not since ReactData is a valid value.
def value_js_representation(val: 'ReactValType', react_context: 'ReactContext', delimiter: str = sq):
    expression: Expression = value_to_expression(val)

    js, hooks = expression.eval_js_and_hooks(react_context, delimiter=delimiter)

    return js

class ReactHook:
    @abstractmethod
    def get_name(self) -> str:
        pass

    @abstractmethod
    def js_attach(self, js_callable: str, invoke_if_changed_from_initial: Union[bool, str]) -> str:
        pass

    @abstractmethod
    def js_detach(self, js_attachment: str) -> str:
        pass

ReactValType = Union[str, bool, int, float, None, List['ReactValType'], Dict[str, 'ReactValType'], 'ReactData']
class ReactData(ReactHook):
    def __init__(self, expression: 'Expression'):
        self.expression = expression

    def __str__(self) -> str:
        return f'ReactData(name={self.get_name()},expression={self.expression}' + \
            (f', saved_initial={self.saved_initial}' if hasattr(self, 'saved_initial') else '') + \
            ')'
    
    def __repr__(self) -> str:
        return f'{super().__repr__()}({str(self)})'

    def get_name(self) -> str:
        return ''
    
    @staticmethod
    def convert_hooks_to_js(hooks: Iterable[ReactHook]):
        hooks = set(hooks)# Avoid repeated hooks

        if len(hooks) > 0:
            return f'[{",".join(hook.js() for hook in hooks)}]'
        else:
            return '__reactive_empty_array'
    
    def eval_initial(self, react_context: 'ReactContext'):
        if hasattr(self, 'saved_initial'):
            return self.saved_initial
        else:
            return self.expression.eval_initial(react_context)
    
    def eval_js_and_hooks(self, react_context: 'ReactContext'):
        return self.expression.eval_js_and_hooks(react_context)
    
    def initial_val_js(self, react_context: 'ReactContext', clear_hooks: bool = False, delimiter: str = sq):
        var_val_expr = value_js_representation(self.eval_initial(react_context), react_context, delimiter)
        js, hooks = self.eval_js_and_hooks(react_context)

        if clear_hooks:
            hooks = []

        hooks_js = ReactData.convert_hooks_to_js(hooks)

        recalc_js_function = (f'function(){{return {js};}}' if hooks else 'undefined')
        
        return f'__reactive_data({var_val_expr},{hooks_js},{recalc_js_function})'
    
    def reactive_val_js(self, react_context: 'ReactContext', other_expression: str = None,
        clear_hooks: bool = False, delimiter: str = sq):

        js, hooks = self.eval_js_and_hooks(react_context, delimiter) \
            if other_expression is None else (other_expression, [])
        
        if clear_hooks:
            hooks = []

        if hooks:
            recalc_js_function = f'function(){{return {js};}}'
            js = 'undefined'
        else:
            recalc_js_function = f'undefined'

        hooks_js = ReactData.convert_hooks_to_js(hooks)
        
        return f'__reactive_data({js},{hooks_js},{recalc_js_function})'

class ReactVar(ReactData):
    def __init__(self, name: str, react_expression: 'Expression'):
        super().__init__(react_expression)
        self.name: str = name
        self.context: Optional[ReactContext] = None

    def __str__(self) -> str:
        return f'ReactVar(name: {repr(self.name)}, expression: {repr(self.expression)}, context: {repr(self.context)}' + \
            (f', saved_initial={self.saved_initial}' if hasattr(self, 'saved_initial') else '') + \
            ')'

    def get_name(self) -> str:
        return self.name
    
    def eval_initial(self, react_context: 'ReactContext'):
        if hasattr(self, 'saved_initial'):
            return self.saved_initial
        else:
            context = react_context if self.context is None else self.context
            return self.expression.eval_initial(context)
    
    def eval_js_and_hooks(self, react_context: 'ReactContext', delimiter: str = sq):
        context = react_context if self.context is None else self.context
        return self.expression.eval_js_and_hooks(context)

    def js(self) -> str:
        return self.context.var_js(self)
    
    def js_get(self) -> str:
        return "(" + self.js() + ".val)"
    
    def js_set(self, js_expression: str, alt_js_name: Optional[str] = None, expression_hooks: Iterable['ReactVar'] = []) -> str:
        if expression_hooks:
            recalc_js_function = f'function(){{return {js_expression};}}'
            js_expression = 'undefined'
        else:
            recalc_js_function = f'undefined'

        expression_hooks_js = ReactData.convert_hooks_to_js(expression_hooks)

        return f'__reactive_data_set({self.js() if alt_js_name is None else alt_js_name},' + \
            f'{js_expression},{expression_hooks_js},{recalc_js_function});'
    
    def js_attach(self, js_callable: str, invoke_if_changed_from_initial: Union[bool, str]):
        if isinstance(invoke_if_changed_from_initial, str):
            invoke_if_js = invoke_if_changed_from_initial
        else:
            invoke_if_js = value_js_representation(invoke_if_changed_from_initial, self.context)
        
        return f'__reactive_data_attach({self.js()},{js_callable},{invoke_if_js})'

    def js_detach(self, js_attachment: str):
        return f'__reactive_data_detach({self.js()},{js_attachment});'
    
    def js_notify(self, alt_js_name: Optional[str] = None):
        return f'__reactive_data_notify({self.js() if alt_js_name is None else alt_js_name});'

class ResorceScript:
    def __init__(self, initial_pre_calc: str = '', initial_post_calc: str = '', destructor: str = ''):
        self.initial_pre_calc: str = initial_pre_calc
        self.initial_post_calc: str = initial_post_calc
        self.destructor: str = destructor
    
    def surround(self, pre: str, post: str) -> 'ResorceScript':
        return ResorceScript(
            initial_pre_calc = pre + self.initial_pre_calc + post if self.initial_pre_calc else '',
            initial_post_calc = pre + self.initial_post_calc + post if self.initial_post_calc else '',
            destructor = pre + self.destructor + post if self.destructor else '',
        )

reactcontext_str = 'reactcontext'
reacttrack_uuid_str: str = uuid.uuid4().hex
reacttrack_str = "react_track"
class ReactTracker:
    def __init__(self):
        self.children: List[ReactNode] = []
class ReactContext:
    def __init__(self, id: str, parent: 'ReactContext' = None, fully_reactive: bool = False):
        self.id: str = id
        self.parent: ReactContext = parent
        self.child_contexts: List[ReactContext] = []
        self.fully_reactive: bool = fully_reactive
        self.vars: Dict[str, ReactVar] = {}
        self.compute_initial: bool = False

        if parent:
            parent.child_contexts.append(self)

        if parent is not None and not fully_reactive and parent.fully_reactive:
            # TODO: Add tag name by using self.tag_name
            raise template.TemplateSyntaxError("Can't have a fully reactive child inside a non-full reactive one.")
    
    def __repr__(self) -> str:
        return f'{super().__repr__()}({str(self)})'

    def basic_repr(self) -> str:
        return super().__repr__()
    
    def __str__(self) -> str:
        return f'ReactContext(id={self.id}, vars={self.vars}, parent={None if self.parent is None else self.parent.basic_repr()})'
    
    def destroy(self):
        """Destroy all children when done, to help gc avoiding cycle references"""

        self.parent = None
        self.vars = None

        for child in self.child_contexts:
            child.destroy()
        
        self.child_contexts = None
    
    # Clear render computation, need for many iteration rendering
    # TODO?: Don't use it, instead have a render board which contains varaibles, and have a result object after render.
    def clear_render(self):
        self.vars: Dict[str, ReactVar] = {}
        self.compute_initial = False

        self.clear_render_inside()
    
    def clear_render_inside(self):
        for child in self.child_contexts:
            child.clear_render()
    
    def id_prefix_expression(self) -> 'Expression':
        return StringExpression(self.id)

    def add_var(self, var: ReactVar):
        if self.vars.get(var.name):
            raise template.TemplateSyntaxError(
                f"Can't add a new variable named {var.name} since it already define exactly in this context.")
        
        self.vars[var.name] = var
        var.context = self

        if self.compute_initial and var.expression is not None:
            var.saved_initial = var.expression.eval_initial(self)
    
    def vars_needed_decleration(self):
        """Virtual method which tells the parent what vars in its scope are needed to be declared"""
        return sum([list(self.vars.values())] + [child.vars_needed_decleration() for child in self.child_contexts], [])
    
    def search_var(self, name):
        current: ReactContext = self

        while current != None:
            var: Optional[ReactVar] = current.vars.get(name)
            if var != None:
                return var    

            current = current.parent
    
    # TODO: Implement this better
    def var_js(self, var) -> str:
        return None

    @abstractmethod
    def render_html(self, subtree: Optional[List]) -> str:
        pass

    def render_html_inside(self, subtree: Optional[List]) -> str:
        if subtree is None:
            return None
        # otherwise

        strings: List[str] = []
        for element in subtree:
            if isinstance(element, str):
                result = element
            elif isinstance(element, tuple):
                context, subsubtree = element
                
                result = context.render_html(subsubtree)
            else:
                raise Exception("All element of the internal subtree must be strings or pairs of form (ReactContext, subsubtree)!")
        
            strings.append(result)

        return ''.join(strings)

    def render_script(self, subtree: Optional[List]) -> ResorceScript:
        return self.render_script_inside(subtree)

    def render_script_inside(self, subtree: Optional[List]) -> ResorceScript:
        if subtree is None:
            return ResorceScript()
        # otherwise

        initial_pre_calc_scripts: List[str] = []
        initial_post_calc_scripts: List[str] = []
        destructor_scripts: List[str] = []

        for element in subtree:
            if isinstance(element, str):
                continue
            elif isinstance(element, tuple):
                context, subsubtree = element
                
                result: ResorceScript = context.render_script(subsubtree)

                if result.initial_pre_calc:
                    initial_pre_calc_scripts.append(result.initial_pre_calc)

                if result.initial_post_calc:
                    initial_post_calc_scripts.append(result.initial_post_calc)

                if result.destructor:
                    destructor_scripts.append(result.destructor)
            else:
                raise Exception("All element of the internal subtree must be scripts or pairs of form (ReactContext, subsubtree)!")

        new_line = '\n'
        return ResorceScript(
            initial_pre_calc = f"{{{new_line.join(initial_pre_calc_scripts)}}}",
            initial_post_calc = f"{{{new_line.join(initial_post_calc_scripts)}}}",
            destructor = f"{{{new_line.join(reversed(destructor_scripts))}}}",
        )
    
    def render_js_and_hooks_inside(self, subtree: Optional[List]) -> Tuple[str, Iterable[ReactHook]]:
        if subtree is None:
            return None, []
        # otherwise

        js_and_hooks: List[str, Iterable[ReactHook]] = []
        for element in subtree:
            if isinstance(element, str):
                result = f"'{escapejs(element)}'", []
            elif isinstance(element, tuple):
                context, subsubtree = element
                
                # TODO: Verify that context is ReactRerendableContext, maybe by the relation to funnly renderable?
                
                js_expression, hooks = context.render_js_and_hooks(subsubtree)

                if not js_expression:
                    continue

                result = js_expression, hooks
            else:
                raise Exception("All element of the internal subtree must be strings or pairs of form (ReactContext, subsubtree)!")
        
            js_and_hooks.append(result)

        js_expressions = [js_expression for js_expression, hooks in js_and_hooks]
        all_hooks = [hooks for js_expression, hooks in js_and_hooks]
        return '+'.join(js_expressions), chain(*all_hooks)
    
    def generate_reduced_subtree(self, nodelist: Optional[template.NodeList], template_context: template.Context) -> List:
        if nodelist is None:
            return None
        # otherwise

        output_list = []

        # TODO: Reduce subsequential strings

        def parse_text(text_result: str):
            output_list.append(text_result)

        def parse_react_node(node: ReactNode):
            context = node.make_context(self, template_context)
            subtree = context.generate_reduced_subtree(node.nodelist, template_context)

            result = (context, subtree)
            output_list.append(result)

        for node in nodelist:
            if isinstance(node, template.base.TextNode):
                result = node.render(template_context)
                parse_text(result)
            elif isinstance(node, ReactNode):
                parse_react_node(node)
            else:
                parent_tracker = template_context.get(reacttrack_str)

                tracker = ReactTracker()
                template_context[reacttrack_str] = tracker
                render_result: str = node.render(template_context)
                j = 0
                i = render_result.find(reacttrack_uuid_str)
                if i == -1:
                    parse_text(render_result)

                while i != -1:
                    parse_text(render_result[j:i])

                    i += len(reacttrack_uuid_str)
                    j = render_result.find(reacttrack_uuid_str, i)
                    if j == -1:
                        raise template.TemplateSyntaxError("Error in reactive template rendering tracking!")

                    node_index = int(render_result[i:j])
                    node = tracker.children[node_index]
                    parse_react_node(node)

                    j += len(reacttrack_uuid_str)

                    i = render_result.find(reacttrack_uuid_str, j)

                template_context[reacttrack_str] = parent_tracker
        
        return output_list
    
    @staticmethod
    def get_current(template_context: template.Context, tag_name: Optional[str] = None, allow_none=False):
        if current := template_context.get(reactcontext_str):
            return current
        elif not allow_none:
            if tag_name:
                raise template.TemplateSyntaxError(
                    f"Must put '{tag_name}' tag inside some react context!")
            else:
                raise template.TemplateSyntaxError(
                    f"Must put this tag inside some react context!")


# TODO: Make sure that we have the relation - fully renderable = inherit ReactRerendable mixin.
class ReactRerenderableContext(ReactContext):
    @abstractmethod
    def render_js_and_hooks(self, subtree: Optional[List]) -> Tuple[str, Iterable[ReactHook]]:
        """Return a tupple of (string of rerender js expression, hooks)."""
        pass


with open(Path(__file__).resolve().parent.parent / 'resources/reactscripts.js', 'r') as f:
    reactive_script = f.read()

class ReactNode(template.Node):
    tag_name: str = ""

    def __init__(self, nodelist: Optional[List[template.Node]], can_be_top_level: bool = False) -> None:
        self.nodelist: Optional[List[template.Node]] = nodelist
        self.can_be_top_level = can_be_top_level

    @abstractmethod
    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        pass

    def render(self, template_context: template.Context):
        # TODO: Is it really needed? Shell we only render here toplevel nodes, and scan the rest in the tree?
        # Answer: We only need to store a tupple of "react_data" so sub-react-nodes will know something.

        parent_context: ReactContext = ReactContext.get_current(template_context, self.tag_name, True)

        is_toplevel: bool = parent_context is None

        if is_toplevel:
            if not self.can_be_top_level:
                # TODO: More informative exception, and add the template tag name!
                raise template.TemplateSyntaxError("This reactive tag can't be toplevel, but it is!")

            current_context = self.make_context(parent_context, template_context)

            template_context[reactcontext_str] = current_context

            subtree = None if (self.nodelist is None) else current_context.generate_reduced_subtree(self.nodelist, template_context)

            template_context[reactcontext_str] = None

            output = current_context.render_html(subtree)

            var_defs = '\n'.join(f'var {var.js()} = {var.initial_val_js(self)};'
                for var in current_context.vars_needed_decleration())

            current_context.clear_render()

            script = current_context.render_script(subtree)

            # Recuservly destroy all context in order to help the garbage collector
            current_context.destroy()

            return output + ('<script>\n{\n' + \
                reactive_script + '\n' + \
                var_defs + '\n' + \
                script.initial_post_calc + '\n' + \
                '}\n</script>' if script else '')
        else:
            tracker: Optional[ReactTracker] = template_context.get(reacttrack_str)

            if not tracker:
                raise Exception("Internal error in reactive -" + \
                    " the reactive tag isn't toplevel but called with render without a tracker!")
            # otherwise

            index = len(tracker.children)
            tracker.children.append(self)

            return mark_safe(reacttrack_uuid_str + str(index) + reacttrack_uuid_str)

from .expressions import *