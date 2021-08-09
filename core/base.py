from abc import abstractmethod
from typing import Dict, Iterable, List, Optional, Set, Union

import uuid

from django import template
from django.utils.html import escapejs
from django.utils.safestring import mark_safe

count_str = 'react_currect_count'
count_reactcontent_str = 'currect_reactcontent_count'
def next_id(context: template.Context, reactcontent = None) -> int:
    if reactcontent is None:
        revelant_str = count_reactcontent_str
    else:
        revelant_str = count_str

    if not context.get(revelant_str):
        context[revelant_str] = 0
    
    currect = context[revelant_str]
    context[revelant_str] = currect + 1

    return currect

def value_to_expression(val):
    if isinstance(val, str):
        return StringExpression(val)
    elif isinstance(val, bool):
        return BoolExpression(val)
    elif isinstance(val, int):
        return IntExpression(val)
    elif isinstance(val, list):
        return ArrayExpression([value_to_expression(element) for element in val])
    else:
        raise template.TemplateSyntaxError(
            "Currently the only types supported are string, bool and int for reactive variables values.")

def value_js_representation(val):
    expression: Expression = value_to_expression(val)

    js, hooks = expression.eval_js_and_hooks(None)

    return js

class ReactHook:
    @abstractmethod
    def js_attach(self, js_callable, invoke_if_changed_from_initial):
        pass

ReactValType = Union[str, int]
class ReactData(ReactHook):
    def __init__(self, val: ReactValType):
        self.val: ReactValType = val
    
    def reactive_val_js(self, other_expression = None):
        val = self.val

        var_val_expr = value_js_representation(val) if other_expression is None else other_expression
        
        return f'new ReactVar({var_val_expr})'

class ReactVar(ReactData):
    def __init__(self, name: str, val: ReactValType):
        super().__init__(val)
        self.name: str = name
        self.context: Optional[ReactContext] = None

    def js(self) -> str:
        return self.context.var_js(self)
    
    def js_get(self) -> str:
        return "(" + self.js() + ".val)"
    
    def js_set(self, js_expression: str) -> str:
        return self.js() + ".val = (" + js_expression + ");"
    
    def js_attach(self, js_callable, invoke_if_changed_from_initial: bool):
        return f'{self.js()}.attach({js_callable}, {value_js_representation(invoke_if_changed_from_initial)});'


# TODO: Remove this obsolete interface
class ReactRerendable:
    # TODO: Remove finally this method
    @abstractmethod
    def render_with_rerender_js(self, template_context: template.Context):
        """Return a pair of (html_output, rerender_js_expression).
        All hooks shell be registered manually in the render context."""
        pass

reactcontext_str = 'reactcontext'
reacttrack_uuid_str: str = uuid.uuid4().hex
reacttrack_str = "react_track"
class ReactTracker:
    def __init__(self):
        self.childs: List[ReactNode] = []
class ReactContext:
    def __init__(self, id: str, parent: 'ReactContext' = None, fully_reactive: bool = False, need_get_tag_hooks: bool = False):
        self.id: str = id
        self.parent: ReactContext = parent
        self.child_contexts: List[ReactContext] = []
        self.fully_reactive: bool = fully_reactive
        self.need_get_tag_hooks: bool = need_get_tag_hooks
        self.vars: Dict[str, ReactVar] = {}
        self.hooks: Set[ReactHook] = set()

        if parent:
            parent.child_contexts.append(self)

        if parent is not None and not fully_reactive and parent.fully_reactive:
            # TODO: Add tag name by using self.tag_name
            raise template.TemplateSyntaxError("Can't have a fully reactive child inside a non-full reactive one.")
    
    def destroy(self):
        """Destroy all childs when done, to help gc avoiding cycle references"""

        self.parent = None
        self.vars = None
        self.hooks = None

        for child in self.child_contexts:
            child.destroy()
        
        self.child_contexts = None
    
    # Clear render computation, need for many iteration rendering
    # TODO?: Don't use it, instead have a render board which contains varaibles and hooks, and have a result object after render.
    def clear_render(self):
        self.vars: Dict[str, ReactVar] = {}
        self.hooks: Set[ReactHook] = set()

        self.clear_render_inside()
    
    def clear_render_inside(self):
        for child in self.child_contexts:
            child.clear_render()

    def add_var(self, var: ReactVar):
        if self.vars.get(var.name):
            raise template.TemplateSyntaxError(
                f"Can't add a new variable named {var.name} since it already define exactly in this context.")
        
        self.vars[var.name] = var
        var.context = self
    
    def vars_needed_decleration(self):
        """Virtual method which tells the parent what vars in its scope are needed to be declared"""
        return sum([list(self.vars.values())] + [child.vars_needed_decleration() for child in self.child_contexts], [])
    
    def add_hook(self, var: ReactHook):
        if not self.fully_reactive:
            raise template.TemplateSyntaxError(
                "Unable to add hook, because the current react context isn't fully reactive.")

        self.hooks.add(var)
    
    # TODO: Add support for conditional hooks, which can improve performance for example in if else tags.
    def add_hooks(self, vars: Iterable[ReactHook], need_full_reactivity: bool = True):
        if (not self.fully_reactive) and need_full_reactivity:
            raise template.TemplateSyntaxError(
                "Unable to add hooks, because the current react context isn't fully reactive.")

        self.hooks.update(vars)
    
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

    # TODO: Use pair for hooks, etc. ? Or just store them in the context?
    @abstractmethod
    def render_html(self, subtree: Optional[List]) -> str:
        pass

    def render_html_inside(self, subtree: List) -> str:
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
    
    def render_js_inside(self, subtree: List) -> str:
        strings: List[str] = []
        for element in subtree:
            if isinstance(element, str):
                result = f"'{escapejs(element)}'"
            elif isinstance(element, tuple):
                context, subsubtree = element
                
                # TODO: Verify that context is ReactRerendableContext, maybe by the relation to funnly renderable?
                
                result = context.render_js(subsubtree)

                if not result:
                    continue
            else:
                raise Exception("All element of the internal subtree must be strings or pairs of form (ReactContext, subsubtree)!")
        
            strings.append(result)

        return '+'.join(strings)
    
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
                while i != -1:
                    parse_text(render_result[j:i])

                    i += len(reacttrack_uuid_str)
                    j = render_result.find(reacttrack_uuid_str, i)
                    if j == -1:
                        raise template.TemplateSyntaxError("Error in reactive template rendering tracking!")

                    node_index = int(render_result[i:j])
                    node = tracker.childs[node_index]
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
class ReactRerendableContext(ReactContext):
    @abstractmethod
    def render_js(self, subtree: Optional[List]) -> str:
        """Return a string of rerender js expression.
        All hooks shell be registered manually in the render context."""
        pass

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

            # Recuservly destroy all context in order to help the garbage collector
            current_context.destroy()

            return output
        else:
            tracker: Optional[ReactTracker] = template_context.get(reacttrack_str)

            if not tracker:
                raise Exception("Internal error in reactive -" + \
                    " the reactive tag isn't toplevel but called with render without a tracker!")
            # otherwise

            index = len(tracker.childs)
            tracker.childs.append(self)

            return mark_safe(reacttrack_uuid_str + str(index) + reacttrack_uuid_str)

from .expressions import *