import itertools
from typing import Any, Dict, Iterable, List, Optional, Tuple

from itertools import chain

from django import template
from django.utils.safestring import mark_safe
from django.templatetags.static import static

from ..core.base import ReactHook, ReactRerenderableContext, ReactValType, ReactVar, ReactContext, ReactNode, ResorceScript, next_id_by_context, value_to_expression
from ..core.expressions import EscapingContainerExpression, Expression, SettableExpression, StringExpression, SumExpression, parse_expression

from ..core.utils import str_repr_s, smart_split, common_delimiters, dq

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
        id = f'block_{next_id_by_context(template_context, "__react_block")}'
        
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
        
        def render_script(self, subtree: Optional[List]) -> ResorceScript:
            self.act()
            return ResorceScript()
    
    def __init__(self, var_name: str, var_val_expression: Expression):
        self.var_name: str = var_name
        self.var_val_expression: Expression = var_val_expression

        super().__init__(nodelist=None)
    
    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        var_val_expression: Expression = self.var_val_expression.reduce(template_context)

        return ReactDefNode.Context(parent_context, self.var_name, var_val_expression)

@register.tag(ReactDefNode.tag_name)
def do_reactdef(parser: template.base.Parser, token: template.base.Token):
    # TODO: Make the difference between bounded and unbounded expressions(i.e. if reactivity change them).
    try:
        tag_name, var_name, var_val_expression = tuple(smart_split(token.contents, ' ', common_delimiters))
    except ValueError:
        raise template.TemplateSyntaxError(
            "%r tag requires exactly two arguments" % token.contents.split()[0]
        )

    return ReactDefNode(var_name, parse_expression(var_val_expression))

class ReactTagNode(ReactNode):
    tag_name = 'reacttag'

    class RenderData(ReactRerenderableContext):
        def __init__(self, parent: ReactContext, id: str, html_tag: str, html_attributes: Dict[str, str]):
            super().__init__(id=id, parent=parent, fully_reactive=True)
            self.html_tag: str = html_tag
            self.control_var_name: str = f'__react_control_{id}'
            self.html_attributes: Dict[str, str] = html_attributes
    
        def var_js(self, var):
            return f'{var.name}_tag{self.id}'
        
        def compute_attributes(self) -> Dict[str, Expression]:
            # TODO: Compute the attributes by reactive expression instead (including tracking)
            computed_attributes = dict(self.html_attributes)

            id_attribute: Optional[Expression] = computed_attributes.get('id')
            if id_attribute is None:
                path_id_expressions: List[Expression] = [self.id_prefix_expression()]
                current: ReactContext = self.parent
                while current is not None:
                    path_id_expressions.append(StringExpression('_'))
                    path_id_expressions.append(current.id_prefix_expression())
                    current = current.parent
                
                path_id_expressions.append(StringExpression('react_html_tag_'))
                
                path_id_expressions.reverse()

                id_attribute = SumExpression(path_id_expressions)
                computed_attributes['id'] = id_attribute
            
            return computed_attributes
        
        def compute_attribute_expression(self) -> Expression:
            computed_attributes = self.compute_attributes()

            exp_iter = ( (StringExpression(f' {key}=\"'), EscapingContainerExpression(expression, dq), StringExpression('\"')) \
                for key, expression in computed_attributes.items() )

            return SumExpression(list(itertools.chain.from_iterable(exp_iter)))
        
        def render_html(self, subtree: Optional[List]) -> str:
            computed_attributes_expression = self.compute_attribute_expression()

            attribute_str = computed_attributes_expression.eval_initial(self)
        
            inner_html_output = self.render_html_inside(subtree)

            control_var = ReactVar(self.control_var_name, value_to_expression(dict()))
            self.add_var(control_var)

            return '<' + self.html_tag + attribute_str + \
                '>' + inner_html_output + '</' + self.html_tag + '>'
        
        def render_js_and_hooks(self, subtree: List) -> Tuple[str, Iterable[ReactHook]]:
            computed_attributes_expression = self.compute_attribute_expression()

            attribute_str = computed_attributes_expression.eval_js_and_hooks(self)[0]

            inner_js_expression, hooks_inside = self.render_js_and_hooks_inside(subtree)

            js_expression = \
                f"{str_repr_s('<' + self.html_tag)}+{attribute_str}+'>'+" + \
                    inner_js_expression + f"+{str_repr_s('</' + self.html_tag + '>')}"
            
            return js_expression, []
        
        def render_script(self, subtree: Optional[List]) -> str:
            script = self.render_script_inside(subtree)
            
            self.clear_render()

            computed_attributes = self.compute_attributes()
            id_js_expression = computed_attributes['id'].eval_js_and_hooks(self)[0]

            attribute_js_expressions_and_hooks = {key: expression.eval_js_and_hooks(self) \
                for key, expression in computed_attributes.items()}

            js_rerender_expression, hooks_inside = self.render_js_and_hooks_inside(subtree)

            hooks = set(hooks_inside)

            control_var = ReactVar(self.control_var_name, value_to_expression(dict()))
            self.add_var(control_var)

            # TODO: Handle the unsupported style and events setting in old IE versions?
            # TODO: Using setting attribute by property instead of setAttribute? E.g. .value instead of SetAttribute that works better in Gecko.
            
            script.initial_post_calc = '( () => { function proc() {' + \
                script.destructor + \
                script.initial_pre_calc + \
                f'document.getElementById({id_js_expression}).innerHTML = ' + js_rerender_expression + ';\n' + \
                script.initial_post_calc + '\n' + \
                ';}\n' + \
                '\n'.join( chain.from_iterable((f'{control_var.js_get()}.attachment_attribute_{hook.get_name()} = ' + \
                hook.js_attach(f"() => {{ document.getElementById({id_js_expression}).setAttribute(\'{attribute}\', " + \
                js_expression + ")}", True) \
                for hook in _hooks) \
                for attribute, (js_expression, _hooks) in attribute_js_expressions_and_hooks.items())) + \
                '\n' + \
                '\n'.join((f'{control_var.js_get()}.attachment_content_{hook.get_name()} = {hook.js_attach("proc", True)};' for hook in hooks)) + \
                ';\n})();'
            
            script.initial_pre_calc = ''

            script.destructor = '( () => {' + \
                '\n'.join((hook.js_detach(f'{control_var.js_get()}.attachment_content_{hook.get_name()}') for hook in hooks)) + \
                '\n' + script.destructor + '} )();'
            
            return script
    
    def __init__(self, nodelist: template.NodeList, html_tag: str, html_attributes: Dict[str, Any]):
        self.nodelist = nodelist
        self.html_tag: str = html_tag
        self.html_attributes = html_attributes

        super().__init__(nodelist=nodelist)
    
    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        id = f'tag_{next_id_by_context(template_context, "__react_tag")}'

        # TODO: Compute the attributes by reactive expression instead (including tracking)
        parsed_html_attributes = {key: StringExpression(str(val.resolve(template_context))) for key, val in self.html_attributes.items()}

        return ReactTagNode.RenderData(parent_context, id, self.html_tag, parsed_html_attributes)

@register.tag(ReactTagNode.tag_name)
def do_reacttag(parser: template.base.Parser, token: template.base.Token):
    bits = list(smart_split(token.contents, ' ', common_delimiters))

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
            self.control_var_name: str = f'__react_control_{id}'
            super().__init__(id=id, parent=parent, fully_reactive=True)
    
        def var_js(self, var):
            return f'{var.name}_for{self.id}'
        
        def vars_needed_decleration(self):
            # All loop varaibles shell be local, except from the control var
            control_var = self.search_var(self.control_var_name)

            if control_var:
                return [control_var]
            else:
                return []
        
        def id_prefix_expression(self) -> Expression:
            iter_var = self.search_var(self.var_name)

            return SumExpression((StringExpression(self.id + '_iter_'), iter_var.reactive_val_js(self)))

        def render_html(self, subtree: List) -> str:
            iter_val_initial = self.iter_expression.eval_initial(self)

            if not isinstance(iter_val_initial, list):
                raise template.TemplateSyntaxError("Can't loop through non-list value!")

            iters: List[Dict[str, ReactValType]] = []
            html_outputs: List[str] = []
            for element_val in iter_val_initial:
                self.compute_initial = True
                
                iter_var = ReactVar(self.var_name, value_to_expression(element_val))
                self.add_var(iter_var)

                html_output = self.render_html_inside(subtree)
                html_outputs.append(html_output)

                #vars = list(filter((iter_var).__ne__, super().vars_needed_decleration()))
                vars = super().vars_needed_decleration()

                iter_data: Dict[str, ReactValType] = {('var_' + var.js()): var for var in vars}

                iters.append(iter_data)

                self.clear_render()
            
            control_data = {'last_length': len(iters), 'iters': iters}

            control_var = ReactVar(self.control_var_name, value_to_expression(control_data))
            
            self.add_var(control_var)
            
            return ''.join(html_outputs)
        
        
        def get_def(self, control_var: ReactVar, var: ReactVar, other_expression: Optional[str] = None):
            return f'const {var.js()} = ' + \
                f'{(control_var.js_get() + ".iters[i].var_" + var.js()) if (other_expression is None) else other_expression};'

        def render_js_and_hooks(self, subtree: List) -> Tuple[str, Iterable[ReactHook]]:
            iter_val_js, iter_hooks = self.iter_expression.eval_js_and_hooks(self)

            iter_var = ReactVar(self.var_name, None)
            self.add_var(iter_var)

            js_section_rerender_expression, hooks_inside_unfiltered = self.render_js_and_hooks_inside(subtree)

            # get all the hooks without iter_var, because that on change the array it's gonna change.
            hooks_inside = filter((iter_var).__ne__, hooks_inside_unfiltered)
            
            hooks = set(chain(iter_hooks, hooks_inside))

            #vars = list(filter((iter_var).__ne__, super().vars_needed_decleration()))
            vars = super().vars_needed_decleration()

            control_data = {'last_length': 0, 'iters': []}
            control_var = ReactVar(self.control_var_name, value_to_expression(control_data))
            self.add_var(control_var)

            if js_section_rerender_expression:
                js_rerender_expression = \
                    '(() => {\n' + \
                    f'// For loop expression calc\n' + \
                    f'const react_iter = {iter_val_js}; var output = \'\';' + \
                    'for (var i = 0; i < react_iter.length; ++i) {' + \
                    '\n'.join(self.get_def(control_var, var) for var in vars) + '\n' + \
                    '\n output += ' + js_section_rerender_expression + '; }; return output; })()'
            else:
                js_rerender_expression = None
            
            return js_rerender_expression, (hook for hook in hooks if hook not in vars)

        def render_script(self, subtree: Optional[List]) -> ResorceScript:
            iter_var = ReactVar(self.var_name, None)
            self.add_var(iter_var)

            script = self.render_script_inside(subtree)
            
            self.clear_render()

            iter_var = ReactVar(self.var_name, None)
            self.add_var(iter_var)

            js_section_rerender_expression, hooks_inside_unfiltered = self.render_js_and_hooks_inside(subtree)

            # get all the hooks without iter_var, because that on change the array it's gonna change.
            hooks_inside = filter((iter_var).__ne__, hooks_inside_unfiltered)

            vars_but_iter = list(filter((iter_var).__ne__, super().vars_needed_decleration()))
            vars = super().vars_needed_decleration()
            
            iter_val_js, iter_hooks = self.iter_expression.eval_js_and_hooks(self)

            control_var = ReactVar(self.control_var_name, None)
            self.add_var(control_var)

            defs = '\n'.join(self.get_def(control_var, var) for var in vars)

            def get_set(var: ReactVar, other_js_expression: Optional[str] = None):
                return control_var.js_get() + '.iters[i].var_' + \
                    var.js_set(var.expression.eval_js_and_hooks(self)[0] if other_js_expression is None else other_js_expression)

            def get_reactive_js(var: ReactVar, other_js_expression: Optional[str] = None):
                return f'var_{var.js()}:' + (var.reactive_val_js(self) if other_js_expression is None else other_js_expression)

            script.initial_pre_calc = '( () => {\n' + \
                f'// For loop initial pre calc\n' + \
                f'const react_iter = {iter_val_js};\n' + \
                f'const length_changed = ({control_var.js_get()}.last_length !== react_iter.length);\n' + \
                f'{control_var.js_get()}.last_length = react_iter.length;\n' +\
                f'if (length_changed) {{\n' + \
                f'{control_var.js_get()}.iters = [];\n' + \
                '}\n' + \
                'for (var i = 0; i < react_iter.length; ++i) {\n' + \
                f'const {iter_var.js()} = {iter_var.reactive_val_js(self, "react_iter[i]")};\n' + \
                f'if (length_changed) {{\n' + \
                f'{control_var.js_get()}.iters.push({{' + \
                ','.join(chain((get_reactive_js(iter_var, iter_var.js()), ), (get_reactive_js(var) for var in vars_but_iter))) + \
                '} ); } else {\n' + \
                get_set(iter_var, iter_var.js()) + '\n' + \
                '\n'.join(get_set(var) for var in vars_but_iter) + \
                '}\n' + \
                '\n'.join(self.get_def(control_var, var) for var in vars_but_iter) + '\n' + \
                script.initial_pre_calc + \
                '} } )();'
            
            script.initial_post_calc = '( () => {\n' + \
                f'// For loop initial post calc\n' + \
                f'const react_iter = {iter_val_js};\n' + \
                'for (var i = 0; i < react_iter.length; ++i) {\n' + \
                '\n' + defs + '\n' + script.initial_post_calc + '} } )();'
            
            script.destructor = '( () => {' + \
                f'// For loop destructor\n' + \
                f'for (var i = 0; i < {control_var.js_get()}.iters.length; ++i) {{\n' + \
                '\n' + defs + '\n' + script.destructor + '} } )();'

            return script

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        iter_expression: Expression = self.iter_expression.reduce(template_context)

        id = f'for_{next_id_by_context(template_context, "__react_for")}'

        return ReactForNode.Context(id=id, parent=parent_context, var_name=self.var_name, iter_expression=iter_expression)
    
    def __init__(self, nodelist: template.NodeList, var_name: str, iter_expression: Expression):
        self.var_name = var_name
        self.iter_expression = iter_expression
        super().__init__(nodelist=nodelist)

@register.tag(ReactForNode.tag_name)
def do_reactfor(parser: template.base.Parser, token: template.base.Token):
    bits = list(smart_split(token.contents, ' ', common_delimiters))

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

        id = f'if_{next_id_by_context(template_context, "__react_if")}'

        return ReactIfNode.Context(id=id, parent=parent_context, expression=expression)

@register.tag(ReactIfNode.tag_name)
def do_reactif(parser: template.base.Parser, token: template.base.Token):
    # TODO: add support for else and elif in the future

    bits = list(smart_split(token.contents, ' ', common_delimiters))

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
            # TODO: HTML escaping?

            return self.expression.eval_js_html_output_and_hooks(self)

    def __init__(self, expression: Expression):
        self.expression = expression
        super().__init__(nodelist=None)

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        expression: Expression = self.expression.reduce(template_context)

        return ReactPrintNode.Context(parent_context, expression)

# TODO: Maybe instead use just the {% ... %} tag and just track it and render it from outside?
@register.tag(ReactPrintNode.tag_name)
def do_reactprint(parser: template.base.Parser, token: template.base.Token):
    bits = list(smart_split(token.contents, ' ', common_delimiters))

    if len(bits) != 2:
        raise template.TemplateSyntaxError(
            "%r tag requires exactly two arguments" % token.contents.split()[0]
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
def do_reactget(parser: template.base.Parser, token: template.base.Token):
    """Get current present value, in js expression"""

    bits = list(smart_split(token.contents, ' ', common_delimiters))

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
def do_reactset(parser: template.base.Parser, token: template.base.Token):
    """Set current present value to a js expression"""

    # TODO: Make the difference between bounded and unbounded expressions. (Currently unbound)

    bits = list(smart_split(token.contents, ' ', common_delimiters))

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
                '\n'.join((hook.js_attach('proc', False) + ';' for hook in set(hooks))) + \
                '\n proc(); } )();')

    def __init__(self, nodelist: template.NodeList):
        super().__init__(nodelist=nodelist)

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        id = f'script_{next_id_by_context(template_context, "__react_script")}'

        return ReactScriptNode.Context(id=id, parent=parent_context)

@register.tag(ReactScriptNode.tag_name)
def do_reactscript(parser: template.base.Parser, token: template.base.Token):
    bits = list(smart_split(token.contents, ' ', common_delimiters))

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