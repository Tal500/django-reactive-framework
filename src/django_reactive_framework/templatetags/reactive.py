from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import itertools
from itertools import chain

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from ..core.base import ReactHook, ReactRerenderableContext, ReactValType, ReactVar, ReactContext, ReactNode, ResorceScript, next_id_by_context, value_to_expression
from ..core.expressions import BinaryOperatorExpression, BoolExpression, EscapingContainerExpression, Expression, FunctionCallExpression, IntExpression, NativeVariableExpression, SettableExpression, SettablePropertyExpression, StringExpression, SumExpression, TernaryOperatorExpression, VariableExpression, parse_expression
from ..core.reactive_function import CustomReactiveFunction
from ..core.reactive_binary_operators import StrictEqualityOperator

from ..core.utils import enumerate_reversed, reduce_nodelist, remove_whitespaces_on_boundaries, split_kwargs, str_repr_s, smart_split, common_delimiters, dq, whitespaces

register = template.Library()

class ReactBlockNode(ReactNode):
    tag_name = 'block'
    class Context(ReactContext):
        def __init__(self, parent, id: str):
            super().__init__(id=id, parent=parent, fully_reactive=True)
    
        def var_js(self, var):
            return f'{var.name}_{self.id}'

        def render_html(self, subtree: List) -> str:
            return self.render_html_inside(subtree)

    def __init__(self, nodelist):
        super().__init__(nodelist=nodelist, can_be_top_level=True)
    
    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        id = f'block_{next_id_by_context(template_context, "__react_block")}'
        
        return ReactBlockNode.Context(parent_context, id)

@register.tag('#' + ReactBlockNode.tag_name)
def do_reactblock(parser, token):
    nodelist = parser.parse(('/' + ReactBlockNode.tag_name,))
    parser.delete_first_token()

    return ReactBlockNode(nodelist)

reactcontent_node_str = 'reactcontent_node'

class ReactDefNode(ReactNode):
    tag_name = 'def'

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
            return '', []
        
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

@register.tag('#/' + ReactDefNode.tag_name)
def do_reactdef(parser: template.base.Parser, token: template.base.Token):
    bits = tuple(smart_split(token.contents, whitespaces, common_delimiters))
    bits_after = bits[1:]

    var_def = tuple(split_kwargs(bits_after))

    if len(var_def) != 1 or (var_def[0][1] is None):
        raise template.TemplateSyntaxError(
            "%r tag requires exactly one aurgument in the form of {name}={val}" % token.contents.split()[0]
        )
    # otherwise

    var_name, var_val_expression = var_def[0]

    return ReactDefNode(var_name, parse_expression(var_val_expression))

class ReactElementNode(ReactNode):
    tag_name = 'element'

    class RenderData(ReactRerenderableContext):
        def __init__(self, parent: ReactContext, id: str, self_enclosed: bool, html_tag: str,
            html_attributes: Dict[str, Tuple[Optional[Expression], Optional[Expression]]]):

            super().__init__(id=id, parent=parent, fully_reactive=True)
            self.self_enclosed: bool = self_enclosed
            self.html_tag: str = html_tag
            self.control_var_name: str = f'__react_control_{id}'
            self.html_attributes: Dict[str, Tuple[Optional[Expression], Optional[Expression]]] = html_attributes
    
        def var_js(self, var):
            return f'{var.name}_element{self.id}'
        
        def compute_attributes(self) -> Dict[str, Tuple[Optional[Expression], Optional[Expression]]]:
            computed_attributes = dict(self.html_attributes)

            id_attribute: Optional[Tuple[Optional[Expression], Optional[Expression]]] = computed_attributes.get('id')
            if id_attribute is None:
                path_id_expressions: List[Expression] = [self.id_prefix_expression()]
                current: ReactContext = self.parent
                while current is not None:
                    path_id_expressions.append(StringExpression('_'))
                    path_id_expressions.append(current.id_prefix_expression())
                    current = current.parent
                
                path_id_expressions.append(StringExpression('react_html_element_'))
                
                path_id_expressions.reverse()

                id_attribute = SumExpression(path_id_expressions)
                computed_attributes['id'] = (None, id_attribute)
            elif id_attribute[0] is not None:
                raise Exception('Internal error in reactive: didn\'t catch on parsing that id attribute is conditional!')
            elif id_attribute[1] is None:
                raise Exception('Internal error in reactive: didn\'t catch on parsing that id attribute is empty!')
            
            return computed_attributes
        
        def compute_attribute_expression(self) -> Expression:
            computed_attributes = self.compute_attributes()

            def attribute_expression_part(key: str,
                expressions: Tuple[Optional[Expression], Optional[Expression]]) -> Iterable[Expression]:

                cond_expression, val_expression = expressions

                if val_expression is None:
                    set_attr_part = (StringExpression(f' {key}="{key}"'), )
                else:
                    set_attr_part = (
                        StringExpression(f' {key}=\"'),
                        EscapingContainerExpression(val_expression, dq),
                        StringExpression('\"')
                    )
                
                if cond_expression is None:
                    return set_attr_part
                else:
                    return (TernaryOperatorExpression(cond_expression,
                        SumExpression.sum_expressions(set_attr_part), StringExpression('')), )

            exp_iter = (attribute_expression_part(key, expressions) for key, expressions in computed_attributes.items())

            return SumExpression.sum_expressions(list(itertools.chain.from_iterable(exp_iter)))
        
        def make_control_var(self) -> ReactVar:
            control_var = ReactVar(self.control_var_name, value_to_expression({}))
            self.add_var(control_var)

            return control_var
        
        def render_html(self, subtree: Optional[List]) -> str:
            computed_attributes_expression = self.compute_attribute_expression()

            attribute_str = computed_attributes_expression.eval_initial(self)
        
            inner_html_output = self.render_html_inside(subtree)

            self.make_control_var()

            if self.self_enclosed:
                return '<' + self.html_tag + attribute_str + ' />'
            else:
                return '<' + self.html_tag + attribute_str + \
                    '>' + inner_html_output + '</' + self.html_tag + '>'
        
        def render_js_and_hooks(self, subtree: List) -> Tuple[str, Iterable[ReactHook]]:
            computed_attributes_expression = self.compute_attribute_expression()

            attribute_str = computed_attributes_expression.eval_js_and_hooks(self)[0]

            inner_js_expression, hooks_inside = self.render_js_and_hooks_inside(subtree)

            self.make_control_var()

            if self.self_enclosed:
                js_expression = \
                    f"{str_repr_s('<' + self.html_tag)}+{attribute_str}+' />'"
            else:
                js_expression = \
                    f"{str_repr_s('<' + self.html_tag)}+{attribute_str}+'>'+" + \
                        inner_js_expression + f"+{str_repr_s('</' + self.html_tag + '>')}"
            
            return js_expression, []
        
        def set_attribute_js_expression(self, element_js: str, attribute: str,
            js_cond_exp: Optional[str], js_val_exp: Optional[str]) -> str:

            if attribute == 'checked':# TODO: Make this exception only for 'input' elements
                if js_val_exp is not None:
                    raise template.TemplateSyntaxError(
                        'Error: \'checked\' attribute can have no value other than empty or "checked"')
                # otherwise

                if js_cond_exp is None:
                    js_cond_exp = 'true'

                js_val_exp = js_cond_exp
                js_cond_exp = None

            if ((js_cond_exp is not None) or (js_val_exp is None) or attribute.startswith(('data-', 'on'))):
                if js_val_exp is None:
                    js_val_exp = f"'{attribute}'"
                
                if js_cond_exp is None:
                    return f"{element_js}.setAttribute('{attribute}', {js_val_exp});"
                else:
                    return \
                        f"if ({js_cond_exp}) {{\n" + \
                            f"{element_js}.setAttribute('{attribute}', {js_val_exp});" + \
                        "} else {\n" + \
                            f"{element_js}.removeAttribute('{attribute}');" + \
                        "}\n"
            else:
                return f"{element_js}.{attribute} = {js_val_exp};"
        
        def all_attributes_js_expressions_and_hooks(self,
            computed_attributes: Dict[str, Tuple[Optional[Expression], Optional[Expression]]]):

            def attribute_js_expressions_and_hooks(expressions: Tuple[Optional[Expression], Optional[Expression]]):
                cond_expression, val_expression = expressions

                cond_hooks, val_hooks = [], []
                
                if cond_expression is not None:
                    cond_expression, cond_hooks = cond_expression.eval_js_and_hooks(self)
                
                if val_expression is not None:
                    val_expression, val_hooks = val_expression.eval_js_and_hooks(self)
                
                return cond_expression, val_expression, list(chain(cond_hooks, val_hooks))

            return {
                key: attribute_js_expressions_and_hooks(expressions) for key, expressions in computed_attributes.items()
            }

        def render_script(self, subtree: Optional[List]) -> str:
            script = self.render_script_inside(subtree)
            
            self.clear_render()

            computed_attributes = self.compute_attributes()
            id_js_expression = computed_attributes['id'][1].eval_js_and_hooks(self)[0]

            all_attributes_js_expressions_and_hooks = self.all_attributes_js_expressions_and_hooks(computed_attributes)

            js_rerender_expression, hooks_inside = self.render_js_and_hooks_inside(subtree)

            hooks = set(hooks_inside)

            control_var = self.make_control_var()

            first_expression = SettablePropertyExpression(VariableExpression(self.control_var_name), ['first'])

            def change_attribute(id_js_expression: str, attribute: str, js_cond_exp: Optional[str], js_val_exp: Optional[str]):
                js_code = self.set_attribute_js_expression(
                    f'document.getElementById({id_js_expression})', attribute, js_cond_exp, js_val_exp)
                
                return f"() => {{ {js_code} }}"

            # TODO: Handle the unsupported style and events setting in old IE versions?
            
            script.initial_post_calc = '( () => {\n' + \
                '// Element post calc\n' + \
                'var __reactive_block_reset = true;\n' + \
                'var __reactive_need_reset = false;\n' + \
                'var __reactive_had_reset = false;\n' + \
                'function __reactive_reset_content() {\n' + \
                    'if (__reactive_block_reset) { __reactive_need_reset=true; return;};\n' + \
                    '__reactive_block_reset = true;\n' + \
                    '__reactive_need_reset = false;\n' + \
                    '__reactive_had_reset = true;\n' + \
                    f'{control_var.js_get()}.inner_destructor();\n' + \
                    script.initial_pre_calc + '\n' + \
                    (f'document.getElementById({id_js_expression}).innerHTML = ' + js_rerender_expression + ';\n'
                    if not self.self_enclosed else '') + \
                    f'{control_var.js_get()}.inner_post();\n' + \
                    '__reactive_block_reset = false;\n' + \
                    'if (__reactive_need_reset) { __reactive_reset_content();};\n' + \
                ';}\n' + \
                f'{control_var.js_get()}.inner_post = function() {{\n{script.initial_post_calc}\n}};\n' + \
                f'{control_var.js_get()}.inner_destructor = function() {{\n{script.destructor}\n}};\n' + \
                '\n'.join(chain.from_iterable((f'{control_var.js_get()}.attachment_attribute_{attribute}_var_{hook.get_name()} = ' + \
                hook.js_attach(change_attribute(id_js_expression, attribute, js_cond_exp, js_val_exp), True) + ';' \
                for hook in _hooks) \
                for attribute, (js_cond_exp, js_val_exp, _hooks) in all_attributes_js_expressions_and_hooks.items())) + \
                '\n' + \
                f'{control_var.js_get()}.inner_post();\n' + \
                '__reactive_block_reset = false;\n' + \
                'if (__reactive_need_reset) { __reactive_reset_content();};\n' + \
                '\n'.join((f'{control_var.js_get()}.attachment_content_{hook.get_name()} = {hook.js_attach("__reactive_reset_content", True)};' \
                    for hook in hooks)) + \
                '\n})();'

            script.destructor = '( () => {\n' + \
                '// Element destructor\n' + \
                '\n'.join((hook.js_detach(f'{control_var.js_get()}.attachment_content_{hook.get_name()}') for hook in hooks)) + \
                '\n' + \
                '\n'.join(chain.from_iterable(
                    (hook.js_detach(f'{control_var.js_get()}.attachment_attribute_{attribute}_var_{hook.get_name()}') \
                    for hook in _hooks) \
                for attribute, (js_cond_exp, js_vaL_exp, _hooks) in all_attributes_js_expressions_and_hooks.items())) + \
                '\n' + \
                f'{control_var.js_get()}.inner_destructor();\n' + \
                '} )();'
            
            return script
    
    def __init__(self, nodelist: Optional[template.NodeList], self_enclosed: bool, html_tag: str,
        html_attributes: Dict[str, Tuple[Optional[Expression], Optional[Expression]]]):
        
        self.self_enclosed: bool = self_enclosed
        self.html_tag: str = html_tag
        self.html_attributes = html_attributes

        super().__init__(nodelist=nodelist)
    
    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        id = f'element_{next_id_by_context(template_context, "__react_element")}'

        def reduce_attribute_expressions(expressions: Tuple[Optional[Expression], Optional[Expression]]) -> \
            Tuple[Optional[Expression], Optional[Expression]]:

            cond_expression, val_expression = expressions
            if cond_expression:
                cond_expression = cond_expression.reduce(template_context)
            if val_expression:
                val_expression = val_expression.reduce(template_context)

            return cond_expression, val_expression

        parsed_html_attributes = {key: reduce_attribute_expressions(expressions) for
            key, expressions in self.html_attributes.items()}

        return ReactElementNode.RenderData(parent_context, id, self.self_enclosed, self.html_tag, parsed_html_attributes)

def parse_reactelement_internal(html_tag: str, bits_after: List[str], nodelist: template.NodeList):
    html_attributes_unparsed = split_kwargs(bits_after)

    def parse_attribute(attribute_unparsed: Tuple[str, Optional[str]]) -> \
        Tuple[str, Tuple[Optional[Expression], Optional[Expression]]]:

        key_and_condition, val = attribute_unparsed

        key_parts = list(smart_split(key_and_condition, ['?']))
        if len(key_parts) > 2:
            raise template.TemplateSyntaxError(f'Too many \'?\' in the attribute key: ({key})')
        elif len(key_parts) == 2:
            key, condition_str = key_parts
        else:
            key = key_and_condition
            condition_str = None

        if key=='id':
            if condition_str is not None:
                raise template.TemplateSyntaxError('\'id\' attribute cannot be conditional!')
            if val is None:
                raise template.TemplateSyntaxError('\'id\' attribute cannot appear with no assignment.')
        # otherwise

        condition_expression = parse_expression(condition_str) if condition_str is not None else None

        val_expression = parse_expression(val) if val is not None else None

        return key, (condition_expression, val_expression)

    html_attributes = dict(parse_attribute(attribute_unparsed) for attribute_unparsed in html_attributes_unparsed)
    
    self_enclosed = (nodelist is None)

    return ReactElementNode(nodelist, self_enclosed, html_tag, html_attributes)

@register.tag('#' + ReactElementNode.tag_name)
@register.tag('#/' + ReactElementNode.tag_name)
def do_reacttag(parser: template.base.Parser, token: template.base.Token):

    bits = list(smart_split(token.contents, whitespaces, common_delimiters))

    tag = token.contents.split()[0]

    if len(bits) < 2:
        raise template.TemplateSyntaxError(
            "%r tag requires at least one arguments" % tag
        )
    # otherwise

    html_tag = bits[1]
    self_enclosed = False
    if html_tag.endswith('/'):
        self_enclosed = True
        html_tag = html_tag[:-1]
    elif bits[-1] == '/':
        self_enclosed = True
        bits = bits[:-1]

    remaining_bits = bits[2:]

    if tag.startswith('#/') != self_enclosed:
        raise template.TemplateSyntaxError('You need to use #/ instead of # on tag if and only if ' + \
            'the html element is self enclosed (i.e. ended with / in html tag name or at the last aurgument list).')
    
    if self_enclosed:
        nodelist = None
    else:
        nodelist = parser.parse(('/' + ReactElementNode.tag_name,))
        parser.delete_first_token()

    return parse_reactelement_internal(html_tag, remaining_bits, nodelist)

class ReactScriptNode(ReactNode):
    tag_name = 'script'

    class Context(ReactRerenderableContext):
        def __init__(self, parent):
            super().__init__(id='', parent=parent, fully_reactive=True)

        def render_html(self, subtree: List) -> str:
            return ''

        def render_js_and_hooks(self, subtree: List) -> Tuple[str, Iterable[ReactHook]]:
            return '', []
        
        def render_script(self, subtree: Optional[List]) -> ResorceScript:
            js_script = self.render_html_inside(subtree)
            return ResorceScript(initial_post_calc=js_script)
    
    def __init__(self, nodelist: template.NodeList):
        super().__init__(nodelist=nodelist)
    
    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        return ReactScriptNode.Context(parent_context)

@register.tag('#' + ReactScriptNode.tag_name)
def do_reactscript(parser: template.base.Parser, token: template.base.Token):
    bits = tuple(smart_split(token.contents, whitespaces, common_delimiters))

    if len(bits) != 1:
        raise template.TemplateSyntaxError(
            "%r tag requires no aurgument!" % token.contents.split()[0]
        )
    # otherwise

    nodelist = parser.parse(('/' + ReactScriptNode.tag_name,))
    parser.delete_first_token()

    return ReactScriptNode(nodelist)

@register.tag('#')
def do_reactgeneric(parser: template.base.Parser, token: template.base.Token):
    bits = list(smart_split(token.contents, whitespaces, common_delimiters))

    if len(bits) != 1:
        raise template.TemplateSyntaxError(
            "# tag requires no arguments"
        )
    
    nodelist = parser.parse(('/',))
    parser.delete_first_token()

    if not nodelist:
        raise template.TemplateSyntaxError(
            'Child nodes of reactive generic block {% # %}...{% / %} is empty.'
            )
    
    if not isinstance(nodelist[0], template.base.TextNode) or not nodelist[0].s:
        raise template.TemplateSyntaxError(
            'A reactive generic block {% # %}...{% / %} must start with non empty text, and not with django tags.'
            )
    
    if not isinstance(nodelist[-1], template.base.TextNode) or not nodelist[-1].s:
        raise template.TemplateSyntaxError(
            'A reactive generic block {% # %}...{% / %} must be ended with non empty text, and not with django tags.'
            )
    
    # if clean so far

    start: str = nodelist[0].s

    start = remove_whitespaces_on_boundaries(start, left=True, right=False)

    if not start.startswith('<'):
        raise template.TemplateSyntaxError(
            'A reactive generic block {% # %}...{% / %} must be started with \'<\' (and possibly whitespaces before).'
            )
    
    start = start[1:]
    start_parts = list(smart_split(start, ['>'], skip_blank=False))
    if len(start_parts) < 2:
        raise template.TemplateSyntaxError(
            'Missing \'>\' while parsimg a reactive generic block {% # %}...{% / %}'
            )

    start_bits = list(smart_split(start_parts[0], whitespaces))
    if not start_bits:
        raise template.TemplateSyntaxError(
            'The first HTML element tag <...> is empty inside a reactive generic block {% # %}...{% / %}'
            )

    html_tag = start_bits[0]
    bits_after = start_bits[1:]

    self_enclosed = False
    if html_tag.endswith('/'):
        html_tag = html_tag[:-1]
        self_enclosed = True
    
    start_seperated_by_slash = list(smart_split(start_parts[0], ['/'], skip_blank=False))
    if len(start_seperated_by_slash) > 2:
        raise template.TemplateSyntaxError(
            'Found more than one slash (\'/\') in start HTML element tag <..> while parsimg a reactive generic block {% # %}...{% / %}'
            )
    elif len(start_seperated_by_slash) == 2 and not self_enclosed:
        if start_bits[-1].endswith('/'):
            if start_bits[-1] == '/':
                bits_after = bits_after[:-1]
            else:
                bits_after[-1] = bits_after[-1][:-1]
            
            self_enclosed = True
        else:
            raise template.TemplateSyntaxError(
                'Found more than one slash (\'/\') which is not in the right place in start HTML element tag <..> ' + \
                'while parsimg a reactive generic block {% # %}...{% / %}'
                )

    start = start[len(start_parts[0])+1:]
    nodelist[0].s = start
    
    if len(nodelist) == 1:
        end: str = start
    else:
        end: str = nodelist[-1].s
    
    end = remove_whitespaces_on_boundaries(end, left=False, right=True)

    if end:
        if self_enclosed:
            raise template.TemplateSyntaxError(
                'Found a slash (\'/\') in start HTML element tag <..> while parsimg a reactive generic block {% # %}...{% / %}, ' + \
                'which indicate that the HTML element is self enclosing, but found more HTML code or or non-whitespace text after.'
                )

        if not end.endswith('>'):
            raise template.TemplateSyntaxError(
                'A reactive generic block {% # %}...{% / %} must be ended with \'>\' (and possibly whitespaces after).'
                )
        
        end = end[:-1]
        end_parts = list(smart_split(end, ['<'], skip_blank=False))
        if len(end_parts) < 2:
            raise template.TemplateSyntaxError(
                'Missing \'<\' on the closing HTML element tag while parsimg a reactive generic block {% # %}...{% / %}'
                )
        
        end_bits = list(smart_split(end_parts[-1], whitespaces))
        if not end_bits:
            raise template.TemplateSyntaxError(
                'The first HTML element tag <...> is empty inside a reactive generic block {% # %}...{% / %}'
                )
        
        if not end_bits[0].startswith('/'):
            raise template.TemplateSyntaxError(
                'Missing \'/\' on the start of the closing HTML element tag, while parsimg a reactive generic block {% # %}...{% / %}'
                )
        
        end_seperated_by_slash = list(smart_split(end_parts[-1], ['/'], skip_blank=False))
        if len(end_seperated_by_slash) > 2:
            raise template.TemplateSyntaxError(
                'Found more than one slash (\'/\') in closing HTML element tag </..> while parsimg a reactive generic block {% # %}...{% / %}'
                )
        
        end_bits[0] = end_bits[0][1:]# Remove the slash '/'
        if not end_bits[0]:# If now the part string is empty after removing the slash '/'
            end_bits = end_bits[1:]
        
        if len(end_bits) != 1:
            raise template.TemplateSyntaxError(
                'There should be exactly one word after the slash (\'/\') in closing HTML element tag </..> ' + \
                    '(found while parsimg a reactive generic block {% # %}...{% / %})'
                )
        
        if end_bits[0] != html_tag:
            raise template.TemplateSyntaxError(
                f'There name of the closing HTML element tag ({end_bits[0]}) must be identical to the name of the opening HTML element tag ({html_tag}) ' + \
                    '(found while parsimg a reactive generic block {% # %}...{% / %})'
                )

        end_location = len(end) - len(end_parts[-1]) - 1
        nodelist[-1].s = nodelist[-1].s[:end_location]
    else:
        if not self_enclosed:
            raise template.TemplateSyntaxError(
                'A slash (\'/\') in start HTML element tag <..> was not found while parsimg a reactive generic block {% # %}...{% / %}, ' + \
                'which indicate that the HTML element is not self enclosing, but not found more HTML code or or non-whitespace text after.'
                )

        nodelist = None
    
    if html_tag == 'script':
        if self_enclosed:
            raise template.TemplateSyntaxError(
                'Script interactive HTML element cannot be self enclosing!'
                )
        # otherwise

        if len(bits) != 1:
            raise template.TemplateSyntaxError(
                'Script interactive HTML element tag cannot have arguments!'
                )
        # otherwise

        return ReactScriptNode(nodelist)
    else:
        return parse_reactelement_internal(html_tag, bits_after, nodelist)

class ReactForNode(ReactNode):
    tag_name = 'for'

    class Context(ReactRerenderableContext):
        def __init__(self, id: str, parent: ReactContext, var_name: str, iter_expression: Expression,
            key_expression: Optional[Expression]):

            self.var_name: str = var_name
            self.iter_expression: Expression = iter_expression
            self.key_expression: Optional[Expression] = key_expression
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
            return SumExpression((StringExpression(self.id + '_iter_'), VariableExpression('__react_iter_id')))

        def render_html(self, subtree: List) -> str:
            iter_val_initial = self.iter_expression.eval_initial(self)

            if not isinstance(iter_val_initial, list):
                raise template.TemplateSyntaxError("Can't loop through non-list value!")

            iters: List[Dict[str, ReactValType]] = []
            html_outputs: List[str] = []
            
            for i, element_val in enumerate(iter_val_initial):
                self.compute_initial = True
                
                iter_var = ReactVar(self.var_name, value_to_expression(element_val))
                self.add_var(iter_var)

                iter_id_var = ReactVar('__react_iter_id',
                    SumExpression([StringExpression('key_'), self.key_expression]) if self.key_expression else IntExpression(i))
                self.add_var(iter_id_var)

                html_output = self.render_html_inside(subtree)
                html_outputs.append(html_output)

                vars = super().vars_needed_decleration()

                iter_data: Dict[str, ReactValType] = {'vars': {(var.js()): var for var in vars} }

                iters.append(iter_data)

                # It's important to save the local variables, so we don't clear on the last iteration
                # TODO: Find a better solution for saving local variables
                if i < len(iter_val_initial) - 1:
                    self.clear_render()
            
            control_data = {'iters': iters}
            if self.key_expression:
                control_data['key_table'] = {}

            control_var = ReactVar(self.control_var_name, value_to_expression(control_data))
            
            self.add_var(control_var)
            
            return ''.join(html_outputs)
        
        def get_def(self, control_var: ReactVar, var: ReactVar,
            other_js_expression: Optional[str] = None, iteration_expression: str = None):

            val = (iteration_expression if (iteration_expression is not None) else (control_var.js_get() + ".iters[i]")) + \
                ".vars." + var.js() if (other_js_expression is None) else other_js_expression
            return f'const {var.js()} = {val};'

        def render_js_and_hooks(self, subtree: List) -> Tuple[str, Iterable[ReactHook]]:
            iter_val_js, iter_hooks = self.iter_expression.eval_js_and_hooks(self)

            iter_var = ReactVar(self.var_name, None)
            self.add_var(iter_var)

            iter_id_var = ReactVar('__react_iter_id', None)
            self.add_var(iter_id_var)

            js_section_rerender_expression, hooks_inside_unfiltered = self.render_js_and_hooks_inside(subtree)

            # get all the hooks without iter_var, because that on change the array it's gonna change.
            hooks_inside = filter((iter_var).__ne__, hooks_inside_unfiltered)
            
            hooks = set(chain(iter_hooks, hooks_inside))

            vars = super().vars_needed_decleration()

            control_data = {'iters': []}
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
            
            return js_rerender_expression, \
                (hook for hook in hooks if (hook not in vars)) if self.key_expression is None else [control_var]
                # We're using control_var hooks for calling to rerendering if the loop was empty before.

        def render_script(self, subtree: Optional[List]) -> ResorceScript:
            iter_var = ReactVar(self.var_name, None)
            self.add_var(iter_var)

            iter_id_var = ReactVar('__react_iter_id',
                SumExpression([StringExpression('key_'), self.key_expression]) if \
                    self.key_expression else NativeVariableExpression('i'))
            self.add_var(iter_id_var)

            script = self.render_script_inside(subtree)
            
            self.clear_render()

            iter_var = ReactVar(self.var_name, None)
            self.add_var(iter_var)

            iter_id_var = ReactVar('__react_iter_id',
                SumExpression([StringExpression('key_'), self.key_expression]) if \
                    self.key_expression else NativeVariableExpression('i'))
            self.add_var(iter_id_var)

            js_section_rerender_expression, hooks_inside_unfiltered = self.render_js_and_hooks_inside(subtree)

            # get all the hooks without iter_var, because that on change the array it's gonna change.
            hooks_inside = filter((iter_var).__ne__, hooks_inside_unfiltered)

            vars = super().vars_needed_decleration()
            vars_but_iter = list(filter((iter_var).__ne__, vars))
            
            iter_val_js, iter_hooks = self.iter_expression.eval_js_and_hooks(self)
            iter_hooks = list(iter_hooks)

            control_var = ReactVar(self.control_var_name, None)
            self.add_var(control_var)

            defs = '\n'.join(self.get_def(control_var, var) for var in vars)

            def get_reactive_js(var: ReactVar, other_js_expression: Optional[str] = None, clear_hooks: bool = False):
                return f'{var.js()}:' + \
                    (var.reactive_val_js(self, clear_hooks=clear_hooks) if other_js_expression is None else other_js_expression)

            if self.key_expression:
                defs_but_iter_and_id_keyed = '\n'.join(
                    self.get_def(control_var, var, iteration_expression='__reactive_iter_store') \
                    for var in vars_but_iter if var is not iter_id_var)

                tag_context: ReactElementNode.RenderData = subtree[0][0]
                tag_subtree = subtree[0][1]

                computed_attributes = tag_context.compute_attributes()

                tag_id_js = computed_attributes["id"][1].eval_js_and_hooks(self)[0]
            
                self.clear_render()

                # Redefine vars after clear
                iter_var = ReactVar(self.var_name, None)
                self.add_var(iter_var)

                iter_id_var = ReactVar('__react_iter_id',
                    SumExpression([StringExpression('key_'), self.key_expression]) if \
                        self.key_expression else NativeVariableExpression('i'))
                self.add_var(iter_id_var)

                tag_inner_js = tag_context.render_js_and_hooks_inside(tag_subtree)[0]

                all_attributes_js_expressions_and_hooks = tag_context.all_attributes_js_expressions_and_hooks(computed_attributes)

                update_for_code = \
                f'const react_iter = {iter_val_js};\n' + \
                f'const __reactive_old_iters = {control_var.js_get()}.iters;\n' + \
                f'{control_var.js_get()}.iters = [];\n' + \
                'var current_old_element = null;\n' + \
                'var __reactive_need_work = true;\n' + \
                'if (__reactive_old_iters.length === 0) {\n' + \
                    'if (react_iter.length !== 0) {\n' + \
                        control_var.js_notify() + '\n' + \
                        '__reactive_need_work = false;\n' + \
                    '}\n' + \
                '} else {\n' + \
                    self.get_def(control_var, iter_var, iteration_expression='__reactive_old_iters[0]') + '\n' + \
                    f'const {iter_id_var.js()} = {iter_id_var.reactive_val_js(self, clear_hooks=True)};\n' + \
                    f'current_old_element = document.getElementById({tag_id_js});\n' + \
                '}\n' + \
                'if (__reactive_need_work) {\n' + \
                'for (var i = 0; i < react_iter.length; ++i) {\n' + \
                    f'const {iter_var.js()} = {iter_var.reactive_val_js(self, "react_iter[i]")};\n' + \
                    f'const {iter_id_var.js()} = {iter_id_var.reactive_val_js(self, clear_hooks=True)};\n' + \
                    f'var __reactive_iter_store = {control_var.js_get()}.key_table[{iter_id_var.js_get()}];\n' + \
                    'if (__reactive_iter_store) {\n' + \
                        f'const current_element = document.getElementById({tag_id_js});\n' + \
                        'if (current_element === null) {\n' + \
                            'throw \'current_element is null!\';\n' + \
                        '}\n' + \
                        'if (current_element !== current_old_element) {\n' + \
                        'current_old_element.parentNode.insertBefore(current_element, current_old_element);\n' + \
                        '} else {\n' + \
                        'current_old_element = current_element.nextSibling;\n' + \
                        '}\n' + \
                        '__reactive_iter_store.keep = true;\n' + \
                        iter_var.js_set(iter_var.js_get(), f'__reactive_iter_store.vars.{iter_var.js()}') + '\n' + \
                    '} else {\n' + \
                        '__reactive_iter_store = { vars: {' + \
                        ','.join(chain((get_reactive_js(iter_var, iter_var.js()),), \
                            (get_reactive_js(var) for var in vars_but_iter))) + \
                        '} };\n' + \
                        f'{control_var.js_get()}.key_table[{iter_id_var.js_get()}] = __reactive_iter_store;\n' + \
                        defs_but_iter_and_id_keyed + '\n' + \
                        script.initial_pre_calc + '\n' + \
                        f'const current_element = document.createElement(\'{tag_context.html_tag}\');\n' + \
                        '\n'.join(tag_context.set_attribute_js_expression("current_element", attribute,
                            js_cond_exp, js_vaL_exp) \
                            for attribute, (js_cond_exp, js_vaL_exp, _hooks) \
                            in all_attributes_js_expressions_and_hooks.items()) + '\n' + \
                        f'current_element.innerHTML = {tag_inner_js};\n' + \
                        'current_old_element.parentNode.insertBefore(current_element, current_old_element);\n' + \
                        script.initial_post_calc + '\n' \
                    '}\n' + \
                    f'({control_var.js_get()}).iters.push(__reactive_iter_store);\n' + \
                '}\n' + \
                'for (var i = 0; i < __reactive_old_iters.length; ++i)\n {' + \
                    'if (__reactive_old_iters[i].keep) {\n' + \
                        '__reactive_old_iters[i].keep = undefined;\n' + \
                    '} else {\n' + \
                        '\n'.join(self.get_def(control_var, var, iteration_expression='__reactive_old_iters[i]') \
                            for var in vars) + \
                        script.destructor + '\n' + \
                        f'const element = document.getElementById({tag_id_js});\n' + \
                        'element.parentNode.removeChild(element);\n' + \
                        f'delete {control_var.js_get()}.key_table[{iter_id_var.js_get()}];\n' + \
                        '\n'.join(f'__reactive_data_destroy({var.js()});' for var in reversed(vars)) + '\n' + \
                    '}\n' + \
                '}\n' + \
                '}\n'

            script.initial_pre_calc = '( () => {\n' + \
                f'// For loop initial pre calc\n' + \
                f'const react_iter = {iter_val_js};\n' + \
                f'const length_changed = ({control_var.js_get()}.iters.length !== react_iter.length);\n' + \
                f'if (length_changed) {{\n' + \
                    f'{control_var.js_get()}.iters = [];\n' + \
                '}\n' + \
                'for (var i = 0; i < react_iter.length; ++i) {\n' + \
                    f'const {iter_var.js()} = {iter_var.reactive_val_js(self, "react_iter[i]")};\n' + \
                    '\n'.join((f'const {var.js()} = {var.reactive_val_js(self)};' for var in vars_but_iter)) + '\n' + \
                    f'if (length_changed) {{\n' + \
                    f'{control_var.js_get()}.iters.push({{ vars: {{\n' + \
                    ','.join((f'{var.js()}:{var.js()}' for var in vars)) + \
                    '\n} } ); } else {\n' + \
                    '\n'.join(f'{control_var.js_get()}.iters[i].vars.{var.js()} = {var.js()};' for var in vars) + '\n' \
                    '}\n' + \
                    script.initial_pre_calc + '\n' \
                '} } )();'
            
            script.initial_post_calc = '( () => {\n' + \
                f'// For loop initial post calc\n' + \
                f'const react_iter = {iter_val_js};\n' + \
                (f'{control_var.js_get()}.key_table = {{}};\n' + \
                'function update_for() {\n' + \
                update_for_code + \
                '\n}\n' + \
                '\n'.join((f'{control_var.js_get()}.attachment_{hook.get_name()} = {hook.js_attach("update_for", False)};' \
                    for hook in iter_hooks)) + \
                '\n'
                if self.key_expression else '') + \
                'for (var i = 0; i < react_iter.length; ++i) {\n' + \
                defs + '\n' + \
                (f'{control_var.js_get()}.key_table[{iter_id_var.js_get()}] = {control_var.js_get()}.iters[i];\n'
                if self.key_expression else '') + \
                script.initial_post_calc + '} } )();'
            
            script.destructor = '( () => {\n' + \
                f'// For loop destructor\n' + \
                ('\n'.join((hook.js_detach(f'{control_var.js_get()}.attachment_{hook.get_name()}') \
                    for hook in iter_hooks)) + \
                '\n' \
                if self.key_expression else '') + \
                f'for (var i = 0; i < {control_var.js_get()}.iters.length; ++i) {{\n' + \
                    defs + '\n' + \
                    script.destructor + '\n' + \
                    '\n'.join(f'__reactive_data_destroy({var.js()});' for var in reversed(vars)) + '\n' + \
                '} } )();'

            return script

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        iter_expression: Expression = self.iter_expression.reduce(template_context)
        key_expression: Optional[Expression] = (self.key_expression.reduce(template_context) if
            self.key_expression is not None else None)

        id = f'for_{next_id_by_context(template_context, "__react_for")}'

        return ReactForNode.Context(id=id, parent=parent_context, var_name=self.var_name, iter_expression=iter_expression,
            key_expression=key_expression)
    
    def __init__(self, nodelist: template.NodeList, var_name: str, iter_expression: Expression,
        key_expression: Optional[Expression]):

        self.var_name: str = var_name
        self.iter_expression: Expression = iter_expression
        self.key_expression: Optional[Expression] = key_expression
        super().__init__(nodelist=nodelist)

@register.tag('#' + ReactForNode.tag_name)
def do_reactfor(parser: template.base.Parser, token: template.base.Token):
    bits = list(smart_split(token.contents, whitespaces, common_delimiters))

    if len(bits) != 4 and len(bits) != 6:
        raise template.TemplateSyntaxError(
            "%r tag requires exactly four or six arguments (with 'in' as the third one, and optionally 'by as the fifth one)" %
            token.contents.split()[0]
        )
    # otherwise

    var_name = bits[1]

    in_str = bits[2]
    if in_str != 'in':
        raise template.TemplateSyntaxError(
            "%r tag requires that the third arguments will be 'in'" % token.contents.split()[0]
        )
    
    iter_expression = bits[3]

    if len(bits) == 6:
        by_str = bits[4]
        if in_str != 'in':
            raise template.TemplateSyntaxError(
                "%r tag requires that the fifth arguments will be 'by', or nothing at all" % token.contents.split()[0]
            )
        key_expression = bits[5]
    else:
        key_expression = None

    nodelist = parser.parse(('/' + ReactForNode.tag_name,))
    parser.delete_first_token()

    if key_expression:
        nodelist = reduce_nodelist(nodelist)
        if len(nodelist) != 1 and not isinstance(nodelist[0], ReactElementNode):
            raise template.TemplateSyntaxError('Error: Keyed loops must have one one child node which is a reactive tag node.')

    return ReactForNode(nodelist, var_name, parse_expression(iter_expression),
        key_expression=(parse_expression(key_expression) if key_expression is not None else None))

class ReactClauseNode(ReactNode):
    tag_name = 'clause'
    
    class Context(ReactRerenderableContext):
        def __init__(self, id: str, parent: ReactContext,
            condition: Expression):
            self.condition = condition

            super().__init__(id=id, parent=parent, fully_reactive=True)
    
        def var_js(self, var):
            return f'{var.name}_clause{self.id}'
        
        def is_condition_met_initial(self) -> bool:
            return self.condition.eval_initial(self)
        
        def render_html(self, subtree: Optional[List]) -> str:
            return self.render_html_inside(subtree)
        
        def render_js_and_hooks(self, subtree: List) -> Tuple[str, Iterable[ReactHook]]:
            return self.render_js_and_hooks_inside(subtree)

        def render_js_conditional_or_else(self, subtree: List,
            else_js: str, else_hooks: Iterable[ReactHook],
            alias_condition: Optional[Expression] = None) -> Tuple[str, Iterable[ReactHook]]:

            inner_js, inner_hooks = self.render_js_and_hooks(subtree)

            if self.condition.constant:
                if self.condition.eval_initial(self):
                    return inner_js, inner_hooks
                else:
                    return else_js, else_hooks
            else:
                condition = self.condition if alias_condition is None else alias_condition
                condition_js, condition_hooks = condition.eval_js_and_hooks(self)
                return f'(({condition_js})?({inner_js}):({else_js}))', chain(condition_hooks, inner_hooks, else_hooks)

        def make_expression_conditional_or_else(self, subtree: List,
            if_true_expression: Expression, else_expression: Expression) -> Tuple[str, Iterable[ReactHook]]:

            if self.condition.constant:
                if self.condition.eval_initial(self):
                    return if_true_expression
                else:
                    return else_expression
            else:
                return TernaryOperatorExpression(self.condition, if_true_expression, else_expression)

    def __init__(self, nodelist: template.NodeList, condition: Expression):
        self.condition = condition
        super().__init__(nodelist=nodelist)

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        condition: Expression = self.condition.reduce(template_context)

        id = f'clause_{next_id_by_context(template_context, "__react_clause")}'

        return ReactClauseNode.Context(id=id, parent=parent_context, condition=condition)

class ReactIfNode(ReactNode):
    tag_name = 'if'

    class Context(ReactRerenderableContext):
        def __init__(self, id: str, parent: ReactContext):
            super().__init__(id=id, parent=parent, fully_reactive=True)
    
        def var_js(self, var):
            return f'{var.name}_if{self.id}'
        
        def make_tracking_var(self, subtree) -> ReactVar:
            else_expression = IntExpression(-1)

            for i, element in enumerate_reversed(subtree):
                context, subsubtree = element
                context: ReactClauseNode.Context = context
                else_expression = context.make_expression_conditional_or_else(subsubtree, IntExpression(i), else_expression)

            current_clause_var = ReactVar('__reactive_current_clause', else_expression)
            self.add_var(current_clause_var)

            return current_clause_var

        def render_html(self, subtree: List) -> str:

            # It's important to render everyone, so they can register their variables. (TODO: Find a better way)
            # TODO: Keep only the active clause variables at init, and manually create them when invoked.
            html_outputs = [context.render_html(subsubtree) for context, subsubtree in subtree]

            current_clause_var = self.make_tracking_var(subtree)
            current_cluse = current_clause_var.eval_initial(self)

            if current_cluse == -1:
                return ''
            else:
                return html_outputs[current_cluse]

        def render_js_and_hooks(self, subtree: List) -> Tuple[str, Iterable[ReactHook]]:
            else_js, else_hooks = '\'\'', []

            current_clause = self.make_tracking_var(subtree)

            for i, element in enumerate_reversed(subtree):
                context, subsubtree = element
                context: ReactClauseNode.Context = context
                else_js, else_hooks = context.render_js_conditional_or_else(subsubtree, else_js, else_hooks,
                    alias_condition=BinaryOperatorExpression('==',
                        StrictEqualityOperator(),
                        [VariableExpression(current_clause.name), IntExpression(i)]
                        ))
            
            return else_js, []
            
        def render_script(self, subtree: Optional[List]) -> ResorceScript:
            all_hooks: List[Set[ReactHook]] = \
                [set(context.render_js_and_hooks(subsubtree)[1]) for context, subsubtree in subtree]
            self.clear_render()

            scripts = [context.render_script(subsubtree) for context, subsubtree in subtree]

            current_clause_var = self.make_tracking_var(subtree)

            script = ResorceScript()

            script.initial_pre_calc = '{\n' + \
                'const __reactive_clause_pre_scripts = ' + \
                    f'[{",".join(f"function(){{{script.initial_pre_calc}}}" for script in scripts)}];\n' + \
                f'if ({current_clause_var.js_get()} !== -1) {{\n' + \
                    f'__reactive_clause_pre_scripts[{current_clause_var.js_get()}]();\n' + \
                '}\n' + \
                '}\n'
            
            script.initial_post_calc = '{\n' + \
                '// If post calc\n' + \
                'const __reactive_clause_post_scripts = ' + \
                    f'[{",".join(f"function(){{{script.initial_post_calc}}}" for script in scripts)}];\n' + \
                f'{current_clause_var.js()}.last_from_post = {current_clause_var.js_get()};\n' + \
                f'{current_clause_var.js()}.attachment_main = ' + \
                    current_clause_var.js_attach('__reactive_reset_content', '!__reactive_had_reset') + '\n' + \
                ''.join(chain.from_iterable(
                    chain(
                        (f'{"else " if i > 0  else ""}if ({current_clause_var.js()}.last_from_post == {i}) {{\n', ),
                        (f'{current_clause_var.js()}.attachment_{i}_var_{hook.get_name()} = ' + \
                        hook.js_attach('__reactive_reset_content', '!__reactive_had_reset') + ';\n'
                        for hook in hooks),
                        ('}\n', )
                    )
                    for i, hooks in enumerate(all_hooks)
                ) ) + \
                f'if ({current_clause_var.js()}.last_from_post !== -1) {{\n' + \
                    f'__reactive_clause_post_scripts[{current_clause_var.js()}.last_from_post]();\n' + \
                '}\n' + \
                '}\n'

            script.destructor = '{\n' + \
                '// If destructor\n' + \
                'const __reactive_clause_destructor_scripts = ' + \
                    f'[{",".join(f"function(){{{script.destructor}}}" for script in scripts)}];\n' + \
                f'if ({current_clause_var.js()}.last_from_post !== -1) {{\n' + \
                    f'__reactive_clause_destructor_scripts[{current_clause_var.js()}.last_from_post]();\n' + \
                '}\n' + \
                current_clause_var.js_detach(f'{current_clause_var.js()}.attachment_main') + '\n' + \
                ''.join(chain.from_iterable(
                    chain(
                        (f'{"else " if i > 0  else ""}if ({current_clause_var.js()}.last_from_post == {i}) {{\n', ),
                        (hook.js_detach(f'{current_clause_var.js()}.attachment_{i}_var_{hook.get_name()}') + '\n' \
                        for hook in hooks),
                        ('}\n', )
                    )
                    for i, hooks in enumerate(all_hooks)
                ) ) + \
                '\n}\n'
            
            return script

    def __init__(self, nodelist: template.NodeList):
        super().__init__(nodelist=nodelist)

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        id = f'if_{next_id_by_context(template_context, "__react_if")}'

        return ReactIfNode.Context(id=id, parent=parent_context)

def parse_if_clause(content: str, nodelist: template.NodeList) -> ReactClauseNode:
    bits = list(smart_split(content, whitespaces, common_delimiters))

    if bits[0] == ':else':
        if len(bits) != 1:
            raise template.TemplateSyntaxError('Reactive else tag cannot have arguments!')
        # otherwise

        return ReactClauseNode(nodelist, BoolExpression(True))
    elif bits[0] in ('#if', ':elif'):
        if len(bits) != 2:
            raise template.TemplateSyntaxError('Reactive if/elif tag must have exactly one argument!')
        # otherwise

        return ReactClauseNode(nodelist, parse_expression(bits[1]))
    else:
        raise template.TemplateSyntaxError('Cannot parse continuation tag of if. ' + \
            f'Must be :elif or :else, but got {bits[0]}')

@register.tag('#' + ReactIfNode.tag_name)
def do_reactif(parser: template.base.Parser, token: template.base.Token):
    nodelist = parser.parse((':elif', ':else', '/if'))
    clauses = [parse_if_clause(token.contents, nodelist)]
    token = parser.next_token()

    # {% :elif ... %} (repeatable)
    while token.contents.startswith(':elif'):
        nodelist = parser.parse((':elif', ':else', '/if'))
        clause = parse_if_clause(token.contents, nodelist)
        clauses.append(clause)
        token = parser.next_token()

    # {% :else %} (optional)
    if token.contents == ':else':
        nodelist = parser.parse(('/if',))
        clause = parse_if_clause(token.contents, nodelist)
        clauses.append(clause)
        token = parser.next_token()
    
    # {% endif %}
    if token.contents != '/if':
        raise template.TemplateSyntaxError('Malformed template tag at line {}: "{}"'.format(token.lineno, token.contents))

    return ReactIfNode(nodelist=template.NodeList(clauses))

class ReactPrintNode(ReactNode):
    tag_name = 'print'

    class Context(ReactRerenderableContext):
        def __init__(self, parent, id: str, expression: Expression):
            self.expression: Expression = expression
            super().__init__(id=id, parent=parent, fully_reactive=True)
    
        def var_js(self, var):
            return f'{var.name}_{self.id}'

        render_html_func = CustomReactiveFunction(
            eval_initial_func=lambda reactive_context, args:
                str(args[0].eval_initial(reactive_context)),
            eval_js_func=lambda reactive_context, delimiter, args:
                args[0].eval_js_html_output_and_hooks(reactive_context, delimiter)[0],
        )

        def make_vars(self) -> Tuple[ReactVar, ReactVar]:
            control_var = ReactVar('print_control', value_to_expression({}))
            self.add_var(control_var)

            print_var = ReactVar('print_var', FunctionCallExpression('render_html', self.render_html_func, [self.expression]))
            self.add_var(print_var)

            return control_var, print_var

        def render_html(self, subtree: List) -> str:
            val_initial = self.expression.eval_initial(self)

            self.compute_initial = True
            control_var, print_var = self.make_vars()

            # Change from python to js if it is bool or None
            if val_initial is None:
                return 'None'
            elif val_initial is True:
                return 'True'
            elif val_initial is False:
                return 'False'
            else:
                return escape(val_initial)

        def render_js_and_hooks(self, subtree: List) -> Tuple[str, Iterable[ReactHook]]:
            control_var, print_var = self.make_vars()

            unescaped_js = VariableExpression(print_var.name).eval_js_html_output_and_hooks(self)[0]

            escaped_js = f'__reactive_print_html({unescaped_js}, true)'

            return escaped_js, [print_var]

    def __init__(self, expression: Expression):
        self.expression = expression
        super().__init__(nodelist=None)

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        id = f'print_{next_id_by_context(template_context, "__react_print")}'

        expression: Expression = self.expression.reduce(template_context)

        return ReactPrintNode.Context(parent_context, id, expression)

# TODO: Maybe instead use just the {% ... %} tag and just track it and render it from outside?
@register.tag('#/' + ReactPrintNode.tag_name)
def do_reactprint(parser: template.base.Parser, token: template.base.Token):
    bits = list(smart_split(token.contents, whitespaces, common_delimiters))

    if len(bits) != 2:
        raise template.TemplateSyntaxError(
            "%r tag requires exactly two arguments" % token.contents.split()[0]
        )
    # otherwise

    extra_attach = bits[2:]# TODO: Use it

    expression = bits[1]

    return ReactPrintNode(parse_expression(expression))

class ReactGetNode(ReactNode):
    tag_name = 'get'

    class Context(ReactRerenderableContext):
        def __init__(self, parent, expression: Expression):
            self.expression: Expression = expression
            super().__init__(id='', parent=parent, fully_reactive=True)

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

@register.tag('#/' + ReactGetNode.tag_name)
def do_reactget(parser: template.base.Parser, token: template.base.Token):
    """Get current present value, in js expression"""

    bits = list(smart_split(token.contents, whitespaces, common_delimiters))

    if len(bits) != 2:
        raise template.TemplateSyntaxError(
            "%r tag requires at exactly two arguments" % token.contents.split()[0]
        )
    # otherwise

    var_expression = bits[1]

    return ReactGetNode(parse_expression(var_expression))

class ReactSetNode(ReactNode):
    tag_name = 'set'

    class Context(ReactContext):
        def __init__(self, parent, settable_expression: SettableExpression, val_expression: Optional[Expression]):
            self.settable_expression: SettableExpression = settable_expression
            self.val_expression: Optional[Expression] = val_expression
            super().__init__(id='', parent=parent, fully_reactive=True)

        def render_html(self, subtree: List) -> str:
            if self.val_expression is None:
                js_expression = self.render_html_inside(subtree)
                hooks = []
            else:
                js_expression, hooks = self.val_expression.eval_js_and_hooks(self)

            output = self.settable_expression.js_set(self, js_expression, hooks)

            return output# TODO: Shell we use "mark_safe" here?

    def __init__(self, nodelist: template.NodeList, settable_expression: SettableExpression, val_expression: Optional[Expression]):
        self.settable_expression = settable_expression
        self.val_expression: Optional[Expression] = val_expression
        super().__init__(nodelist=nodelist)

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        settable_expression: SettableExpression = self.settable_expression.reduce(template_context)
        val_expression: Optional[Expression] = None if self.val_expression is None else \
            self.val_expression.reduce(template_context)

        return ReactSetNode.Context(parent_context, settable_expression, val_expression)

@register.tag('#' + ReactSetNode.tag_name)
@register.tag('#/' + ReactSetNode.tag_name)
def do_reactset(parser: template.base.Parser, token: template.base.Token):
    """Set current present value to a js expression"""

    bits = list(smart_split(token.contents, whitespaces, common_delimiters))

    tag = token.contents.split()[0]

    if len(bits) < 2:
        raise template.TemplateSyntaxError(
            "%r tag requires exactly one aurgument." % tag
        )
    # otherwise

    self_enclosing = tag.startswith('#/')

    remaining_bits = bits[1:]

    parts = tuple(split_kwargs(remaining_bits))

    if len(parts) != 1:
        raise template.TemplateSyntaxError(
            "%r tag (which is self enclosing) requires exactly one aurgument!" %
                token.contents.split()[0]
        )
    
    settable_expression_str, val_expression_str = parts[0]

    if self_enclosing:
        if val_expression_str is None:
            raise template.TemplateSyntaxError(
                "%r tag (which is self enclosing) requires exactly one aurgument in the form of {settable}={val}" %
                    token.contents.split()[0]
            )
    else:
        if val_expression_str is not None:
            raise template.TemplateSyntaxError(
                "%r tag (which isn't self enclosing) requires exactly one aurgument in the form of {settable}" %
                    token.contents.split()[0]
            )
    # otherwise

    #return ReactDefNode(var_name, parse_expression(val_expression_str))
    
    if self_enclosing:
        nodelist = None
    else:
        nodelist = parser.parse(('/' + ReactSetNode.tag_name,))
        parser.delete_first_token()

    settable_expression = parse_expression(settable_expression_str)
    val_expression = None if val_expression_str is None else parse_expression(val_expression_str)

    if not isinstance(settable_expression, SettableExpression):
        raise template.TemplateSyntaxError(
            "%r tag requires the first expression to be reactively setable." % token.contents.split()[0]
        )

    return ReactSetNode(nodelist, settable_expression, val_expression)

class ReactNotifyNode(ReactNode):
    tag_name = 'notify'

    class Context(ReactContext):
        def __init__(self, parent, settable_expression: SettableExpression):
            self.settable_expression: SettableExpression = settable_expression
            super().__init__(id='', parent=parent, fully_reactive=True)

        def render_html(self, subtree: List) -> str:
            output = self.settable_expression.js_notify(self)

            return output# TODO: Shell we use "mark_safe" here?

    def __init__(self, settable_expression: SettableExpression):
        self.settable_expression = settable_expression
        super().__init__(nodelist=None)

    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        settable_expression: Expression = self.settable_expression.reduce(template_context)

        return ReactNotifyNode.Context(parent_context, settable_expression)

@register.tag('#/' + ReactNotifyNode.tag_name)
def do_reactnotify(parser: template.base.Parser, token: template.base.Token):
    """Set current present value to a js expression"""

    # TODO: Make the difference between bounded and unbounded expressions. (Currently unbound)

    bits = list(smart_split(token.contents, whitespaces, common_delimiters))

    if len(bits) != 2:
        raise template.TemplateSyntaxError(
            "%r tag requires at exactly two arguments" % token.contents.split()[0]
        )
    # otherwise

    var_expression = bits[1]

    expression = parse_expression(var_expression)

    if not isinstance(expression, SettableExpression):
        raise template.TemplateSyntaxError(
            "%r tag requires the first expression to be reactively setable." % token.contents.split()[0]
        )

    return ReactNotifyNode(expression)

class ReactRedoNode(ReactNode):
    tag_name = 'redo'

    class Context(ReactContext):
        def __init__(self, id: str, parent: ReactContext):
            super().__init__(id=id, parent=parent, fully_reactive=True)
    
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

        return ReactRedoNode.Context(id=id, parent=parent_context)

@register.tag('#' + ReactRedoNode.tag_name)
def do_reactredo(parser: template.base.Parser, token: template.base.Token):
    bits = list(smart_split(token.contents, whitespaces, common_delimiters))

    if len(bits) != 1:
        raise template.TemplateSyntaxError(
            "%r tag have no arguments" % token.contents.split()[0]
        )
    # otherwise

    # TODO: Forbit puttting reactivescript inside another reactivescript
    # TODO: Allow only get&set reactive tags as children, or other non-reactive ones, maybe by using "in_script" field in context?

    nodelist = parser.parse(('/' + ReactRedoNode.tag_name,))
    parser.delete_first_token()

    return ReactRedoNode(nodelist)