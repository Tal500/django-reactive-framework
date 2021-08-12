from typing import Any, Dict, Iterable, List, Optional, Tuple

from itertools import chain

from django import template
from django.utils.html import escapejs
from django.utils.safestring import mark_safe
from django.templatetags.static import static

from ..core.base import ReactHook, ReactRerenderableContext, ReactVar, ReactContext, ReactNode, next_id, value_to_expression
from ..core.expressions import Expression, SettableExpression, parse_expression

register = template.Library()

@register.simple_tag()
def reactprescript():
    path = static('js/reactscripts.js')
    return mark_safe(f'<script src="{path}"></script>')

class ReactBlockNode(ReactNode):
    tag_name = 'reactblock'
    class Context(ReactContext):
        def __init__(self, parent, id: str):
            super().__init__(id=id, parent=parent)
    
        def var_js(self, var):
            return f'{var.name}_{self.id}'

        def render_html(self, subtree: List) -> str:
            output = self.render_html_inside(subtree)

            def get_def(var: ReactVar):
                return f'var {var.js()} = {var.initial_val_js(self)};'

            if self.parent is None:# If it is the root level context
                script = '<script>' + '\n'.join(get_def(var) for var in self.vars_needed_decleration()) + '</script>'

                return script + '\n' + output
            else:
                return output

    def __init__(self, nodelist):
        super().__init__(nodelist=nodelist, can_be_top_level=True)
    
    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        # TODO: use better id generating with recursive contexts
        id = next_id(template_context)
        
        return ReactBlockNode.Context(parent_context, id)

@register.tag(ReactBlockNode.tag_name)
def do_reactblock(parser, token):
    nodelist = parser.parse(('endreactblock',))
    parser.delete_first_token()

    return ReactBlockNode(nodelist)

reactcontent_node_str = 'reactcontent_node'

class ReactDefNode(ReactNode):
    tag_name = 'reactdef'

    # TODO: Support reactive definition (i.e. update value when expression value is changed)
    class Context(ReactRerenderableContext):
        def __init__(self, parent, var_name: str, var_val_expression: Expression):
            self.var_name: str = var_name
            self.var_val_expression: Expression = var_val_expression
            super().__init__(id='', parent=parent, fully_reactive=True)
        
        def act(self) -> None:
            var = ReactVar(self.var_name, self.var_val_expression)
            self.parent.add_var(var)

        def render_html(self, subtree: List) -> str:
            self.act()
            return ''

        def render_js_and_hooks(self, subtree: List) -> Tuple[str, Iterable[ReactHook]]:
            self.act()
            return '', []# TODO: Return a hook for all hooks in the expression?
        
        def render_post_script(self, subtree: Optional[List]) -> str:
            self.act()
            return ''
    
    def __init__(self, var_name: str, var_val_expression: Expression):
        self.var_name: str = var_name
        self.var_val_expression: Expression = var_val_expression

        super().__init__(nodelist=None)
    
    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        var_val_expression: Expression = self.var_val_expression.reduce(template_context)

        return ReactDefNode.Context(parent_context, self.var_name, var_val_expression)

@register.tag(ReactDefNode.tag_name)
def do_reactdef(parser, token):
    # TODO: Make the difference between bounded and unbounded expressions(i.e. if reactivity change them).
    try:
        tag_name, var_name, var_val_expression = token.split_contents()
    except ValueError:
        raise template.TemplateSyntaxError(
            "%r tag requires exactly two arguments" % token.contents.split()[0]
        )

    return ReactDefNode(var_name, parse_expression(var_val_expression))

class ReactTagNode(ReactNode):
    tag_name = 'reacttag'

    class RenderData(ReactContext):
        def __init__(self, parent: ReactContext, id: str, html_tag: str, computed_attributes: Dict[str, Any]):
            super().__init__(id=id, parent=parent, fully_reactive=True)
            self.html_tag = html_tag
            self.computed_attributes: Dict[str, Any] = computed_attributes
    
        def var_js(self, var):
            return f'{var.name}_tag{self.id}'
        
        def render_html(self, subtree: Optional[List]) -> str:
            attribute_str = ' '.join((f'{key}="{escapejs(val)}"' for key, val in self.computed_attributes.items()))
        
            inner_html_output = self.render_html_inside(subtree)

            return '<' + self.html_tag + (' ' + attribute_str if attribute_str else '') + \
                '>' + inner_html_output + '</' + self.html_tag + '>'
        
        def render_post_script(self, subtree: Optional[List]) -> str:
            js_rerender_expression, hooks = self.render_js_and_hooks_inside(subtree)
            
            script = '( () => { function proc() {' + f'document.getElementById(\'{self.id}\').innerHTML = ' + \
                js_rerender_expression + ';}\n' + \
                '\n'.join((hook.js_attach('proc', True) for hook in set(hooks))) +\
                '} )();'
            
            self.clear_render()
            
            return script + '\n' + self.render_post_script_inside(subtree)
    
    def __init__(self, nodelist, html_tag: str, extra_attributes):
        self.nodelist = nodelist
        self.html_tag: str = html_tag
        self.extra_attributes = extra_attributes

        super().__init__(nodelist=nodelist)
    
    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        # TODO: Compute the attributes by reactive expression instead (including tracking)
        computed_attributes = {key: val.resolve(template_context) for key, val in self.extra_attributes.items()}

        id = computed_attributes.get('id')
        if id is None:
            local_id = next_id(template_context)#, react_context)
            id = f'react_html_tag_{parent_context.id}_{local_id}'
            computed_attributes['id'] = id

        return ReactTagNode.RenderData(parent_context, id, self.html_tag, computed_attributes)

@register.tag(ReactTagNode.tag_name)
def do_reacttag(parser, token):
    bits = token.split_contents()

    if len(bits) < 2:
        raise template.TemplateSyntaxError(
            "%r tag requires at least two arguments" % token.contents.split()[0]
        )
    # otherwise

    html_tag = bits[1]

    remaining_bits = bits[2:]
    extra_attributes = template.base.token_kwargs(remaining_bits, parser, support_legacy=False)

    if remaining_bits:
        raise template.TemplateSyntaxError("%r received an invalid token: %r" %
                                  (bits[0], remaining_bits[0]))
    # otherwise

    nodelist = parser.parse(('endreacttag',))
    parser.delete_first_token()

    return ReactTagNode(nodelist, html_tag, extra_attributes)

class ReactForNode(ReactNode):
    tag_name = 'reactfor'
    tag_name_enclose = 'endreactfor'

    class Context(ReactRerenderableContext):
        def __init__(self, id: str, parent: ReactContext, var_name: str, iter_expression: Expression):
            self.var_name: str = var_name
            self.iter_expression: Expression = iter_expression
            super().__init__(id=id, parent=parent, fully_reactive=True)
    
        def var_js(self, var):
            return f'{var.name}_for{self.id}'
        
        def vars_needed_decleration(self):
            # All loop varaibles shell be local
            return []

        def render_html(self, subtree: List) -> str:
            iter_val_initial = self.iter_expression.eval_initial(self)

            if not isinstance(iter_val_initial, list):
                raise template.TemplateSyntaxError("Can't loop through non-list value!")

            html_outputs = []
            for element_val in iter_val_initial:
                iter_var = ReactVar(self.var_name, value_to_expression(element_val))
                self.add_var(iter_var)

                html_output = self.render_html_inside(subtree)
                html_outputs.append(html_output)

                self.clear_render()
            
            return ''.join(html_outputs)

        def render_js_and_hooks(self, subtree: List) -> Tuple[str, Iterable[ReactHook]]:
            iter_val_js, iter_hooks = self.iter_expression.eval_js_and_hooks(self)

            iter_var = ReactVar(self.var_name, None)
            self.add_var(iter_var)

            js_section_rerender_expression, hooks_inside_unfiltered = self.render_js_and_hooks_inside(subtree)

            # get all the hooks without iter_var, because that on change the array it's gonna change.
            hooks_inside = filter((iter_var).__ne__, hooks_inside_unfiltered)
            
            hooks = set(chain(iter_hooks, hooks_inside))

            if js_section_rerender_expression:
                def get_def(var: ReactVar, other_expression: Optional[Expression] = None):
                    return f'const {var.js()} = {var.reactive_val_js(self, other_expression)};'
                
                vars = list(filter((iter_var).__ne__, super().vars_needed_decleration()))

                js_rerender_expression = \
                    f'(() => {{ const react_iter = {iter_val_js}; var output = \'\';' + \
                        'for (var i = 0; i < react_iter.length; ++i) {' + \
                        get_def(iter_var, "react_iter[i]") + '\n' + \
                        '\n'.join(get_def(var) for var in vars) + '\n' + \
                        '\n'.join((hook.js_attach('proc', False) for hook in hooks if hook in vars)) + \
                        '\n output += ' + js_section_rerender_expression + '; }; return output; })()'
            else:
                js_rerender_expression = None
            
            return js_rerender_expression, (hook for hook in hooks if hook not in vars)

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        iter_expression: Expression = self.iter_expression.reduce(template_context)

        id = next_id(template_context, parent_context)

        return ReactForNode.Context(id=id, parent=parent_context, var_name=self.var_name, iter_expression=iter_expression)
    
    def __init__(self, nodelist: template.NodeList, var_name: str, iter_expression: Expression):
        self.var_name = var_name
        self.iter_expression = iter_expression
        super().__init__(nodelist=nodelist)

@register.tag(ReactForNode.tag_name)
def do_reactfor(parser, token):
    bits = token.split_contents()

    if len(bits) != 4:
        raise template.TemplateSyntaxError(
            "%r tag requires exactly four arguments (with 'in' as the third one)" % token.contents.split()[0]
        )
    # otherwise

    var_name = bits[1]

    in_str = bits[2]
    if in_str != 'in':
        raise template.TemplateSyntaxError(
            "%r tag requires that the third arguments will be 'in'" % token.contents.split()[0]
        )
    
    iter_expression = bits[3]

    nodelist = parser.parse((ReactForNode.tag_name_enclose,))
    parser.delete_first_token()

    return ReactForNode(nodelist, var_name, parse_expression(iter_expression))

class ReactIfNode(ReactNode):
    tag_name = 'reactif'
    tag_name_enclose = 'endreactif'

    class Context(ReactRerenderableContext):
        def __init__(self, id: str, parent: ReactContext, expression: Expression):
            self.expression: Expression = expression
            super().__init__(id=id, parent=parent, fully_reactive=True)
    
        def var_js(self, var):
            return f'{var.name}_if{self.id}'

        def render_html(self, subtree: List) -> str:
            condition_val_initial = self.expression.eval_initial(self)

            if condition_val_initial:
                return self.render_html_inside(subtree)
            else:
                return ''

        def render_js_and_hooks(self, subtree: List) -> Tuple[str, Iterable[ReactHook]]:
            val_js, condition_hooks = self.expression.eval_js_and_hooks(self)

            js_section_expression, hooks_inside = self.render_js_and_hooks_inside(subtree)

            hooks = chain(condition_hooks, hooks_inside)

            if js_section_expression and condition_hooks:
                js_rerender_expression = f'({val_js}?{js_section_expression}:\'\')'
            elif js_section_expression:
                condition_val_initial = self.expression.eval_initial(self)
                if condition_val_initial:
                    js_rerender_expression = js_section_expression
                else:
                    js_rerender_expression = None
            else:
                js_rerender_expression = None
            
            return js_rerender_expression, hooks

    def __init__(self, nodelist: template.NodeList, expression: Expression):
        self.expression = expression
        super().__init__(nodelist=nodelist)

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        expression: Expression = self.expression.reduce(template_context)

        id = next_id(template_context, parent_context)

        return ReactIfNode.Context(id=id, parent=parent_context, expression=expression)

@register.tag(ReactIfNode.tag_name)
def do_reactif(parser, token):
    # TODO: add support for else and elif in the future

    bits = token.split_contents()

    if len(bits) != 2:
        raise template.TemplateSyntaxError(
            "%r tag requires exactly two arguments" % token.contents.split()[0]
        )
    # otherwise

    expression = bits[1]

    nodelist = parser.parse((ReactIfNode.tag_name_enclose,))
    parser.delete_first_token()

    return ReactIfNode(nodelist, parse_expression(expression))

class ReactPrintNode(ReactNode):
    tag_name = 'reactprint'

    class Context(ReactRerenderableContext):
        def __init__(self, parent, expression: Expression):
            self.expression: Expression = expression
            super().__init__(id='', parent=parent, fully_reactive=True)

        def render_html(self, subtree: List) -> str:
            val_initial = self.expression.eval_initial(self)

            # Change from python to js if it is bool or None
            if val_initial is None:
                return 'None'
            elif val_initial is True:
                return 'True'
            elif val_initial is False:
                return 'False'
            else:
                # TODO: HTML excaping also after reaction hook, in js
                return str(val_initial)

        def render_js_and_hooks(self, subtree: List) -> Tuple[str, Iterable[ReactHook]]:
            val_js, hooks = self.expression.eval_js_and_hooks(self)
            
            # TODO: HTML escaping?
            return f'react_print_html({val_js})', hooks

    def __init__(self, expression: Expression):
        self.expression = expression
        super().__init__(nodelist=None)

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        expression: Expression = self.expression.reduce(template_context)

        return ReactPrintNode.Context(parent_context, expression)

# TODO: Maybe instead use just the {% ... %} tag and just track it and render it from outside?
@register.tag(ReactPrintNode.tag_name)
def do_reactprint(parser, token):
    bits = token.split_contents()

    if len(bits) < 2:
        raise template.TemplateSyntaxError(
            "%r tag requires at least two arguments" % token.contents.split()[0]
        )
    # otherwise

    extra_attach = bits[2:]# TODO: Use it

    expression = bits[1]

    return ReactPrintNode(parse_expression(expression))

class ReactGetNode(ReactNode):
    tag_name = 'reactget'

    class Context(ReactRerenderableContext):
        def __init__(self, parent, expression: Expression):
            self.expression: Expression = expression
            super().__init__(id='', parent=parent, fully_reactive=False)

        def render_html(self, subtree: List) -> str:
            js_expression, hooks = self.expression.eval_js_and_hooks(self)

            return mark_safe(js_expression)

        def render_js_and_hooks(self, subtree: List) -> str:
            js_expression, hooks = self.expression.eval_js_and_hooks(self)

            return js_expression, hooks

    def __init__(self, expression: Expression):
        self.expression = expression
        super().__init__(nodelist=None)

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        expression: Expression = self.expression.reduce(template_context)

        return ReactGetNode.Context(parent_context, expression)

@register.tag(ReactGetNode.tag_name)
def do_reactget(parser, token):
    """Get current present value, in js expression"""

    bits = token.split_contents()

    if len(bits) != 2:
        raise template.TemplateSyntaxError(
            "%r tag requires at exactly two arguments" % token.contents.split()[0]
        )
    # otherwise

    var_expression = bits[1]

    return ReactGetNode(parse_expression(var_expression))

class ReactSetNode(ReactNode):
    tag_name = 'reactset'
    tag_name_enclose = 'endreactset'

    class Context(ReactContext):
        def __init__(self, parent, settable_expression: SettableExpression):
            self.settable_expression: SettableExpression = settable_expression
            super().__init__(id='', parent=parent, fully_reactive=False)

        def render_html(self, subtree: List) -> str:
            js_expression = self.render_html_inside(subtree)

            output = self.settable_expression.js_set(self, js_expression)

            return output# TODO: Shell we use "mark_safe" here?

    def __init__(self, nodelist: template.NodeList, settable_expression: SettableExpression):
        self.settable_expression = settable_expression
        super().__init__(nodelist=nodelist)

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        settable_expression: Expression = self.settable_expression.reduce(template_context)

        return ReactSetNode.Context(parent_context, settable_expression)

@register.tag(ReactSetNode.tag_name)
def do_reactset(parser, token):
    """Set current present value to a js expression"""

    # TODO: Make the difference between bounded and unbounded expressions. (Currently unbound)

    bits = token.split_contents()

    if len(bits) != 2:
        raise template.TemplateSyntaxError(
            "%r tag requires at exactly two arguments" % token.contents.split()[0]
        )
    # otherwise

    var_expression = bits[1]
    
    nodelist: template.NodeList = parser.parse((ReactSetNode.tag_name_enclose,))
    parser.delete_first_token()

    expression = parse_expression(var_expression)

    if not isinstance(expression, SettableExpression):
        raise template.TemplateSyntaxError(
            "%r tag requires the first expression to be reactively setable." % token.contents.split()[0]
        )

    return ReactSetNode(nodelist, expression)

class ReactScriptNode(ReactNode):
    tag_name = 'reactscript'
    tag_name_enclose = 'endreactscript'

    class Context(ReactContext):
        def __init__(self, id: str, parent: ReactContext):
            super().__init__(id=id, parent=parent, fully_reactive=False)
    
        def var_js(self, var):
            return f'{var.name}_script{self.id}'

        def render_html(self, subtree: List) -> str:
            script = self.render_html_inside(subtree)

            js_expression, hooks = self.render_js_and_hooks_inside(subtree)

            return mark_safe(f'( () => {{ function proc() {{ {script} }} \n' + \
                '\n'.join((hook.js_attach('proc', False) for hook in set(hooks))) + \
                '\n proc(); } )();')

    def __init__(self, nodelist: template.NodeList):
        super().__init__(nodelist=nodelist)

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        id = next_id(template_context, parent_context)

        return ReactScriptNode.Context(id=id, parent=parent_context)

@register.tag(ReactScriptNode.tag_name)
def do_reactscript(parser, token):
    bits = token.split_contents()

    if len(bits) != 1:
        raise template.TemplateSyntaxError(
            "%r tag have no arguments" % token.contents.split()[0]
        )
    # otherwise

    # TODO: Forbit puttting reactivescript inside another reactivescript
    # TODO: Allow only get&set reactive tags as children, or other non-reactive ones, maybe by using "in_script" field in context?

    nodelist = parser.parse((ReactScriptNode.tag_name_enclose,))
    parser.delete_first_token()

    return ReactScriptNode(nodelist)