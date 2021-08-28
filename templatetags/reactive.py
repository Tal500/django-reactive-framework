from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import itertools
from itertools import chain

from pathlib import Path

from django import template
from django.utils.safestring import mark_safe
from django.templatetags.static import static

from ..core.base import ReactHook, ReactRerenderableContext, ReactValType, ReactVar, ReactContext, ReactNode, ResorceScript, next_id_by_context, value_to_expression
from ..core.expressions import EscapingContainerExpression, Expression, IntExpression, NativeVariableExpression, SettableExpression, SettablePropertyExpression, StringExpression, SumExpression, VariableExpression, parse_expression

from ..core.utils import reduce_nodelist, remove_whitespaces_on_boundaries, split_kwargs, str_repr_s, smart_split, common_delimiters, dq, whitespaces

register = template.Library()

with open(Path(__file__).resolve().parent.parent / 'resources/reactscripts.js', 'r') as f:
    reactive_script = f.read()

class ReactBlockNode(ReactNode):
    tag_name = 'block'
    class Context(ReactContext):
        def __init__(self, parent, id: str, need_load_scripts: bool):
            super().__init__(id=id, parent=parent)
            self.need_load_scripts: bool = need_load_scripts
    
        def var_js(self, var):
            return f'{var.name}_{self.id}'

        def render_html(self, subtree: List) -> str:
            output = self.render_html_inside(subtree)

            def get_def(var: ReactVar):
                return f'var {var.js()} = {var.initial_val_js(self)};'

            if self.parent is None:# If it is the root level context
                script = '<script>\n' + ((reactive_script + '\n') if self.need_load_scripts else '') + \
                    '\n'.join(get_def(var) for var in self.vars_needed_decleration()) + '</script>'

                return script + '\n' + output
            else:
                return output

    def __init__(self, nodelist):
        super().__init__(nodelist=nodelist, can_be_top_level=True)
    
    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        id = f'block_{next_id_by_context(template_context, "__react_block")}'
        
        reactive_scripts_are_loaded_str = 'reactive_scripts_are_loaded'
        if template_context.get(reactive_scripts_are_loaded_str):
            need_load_scripts = False
        else:
            need_load_scripts = True
            template_context[reactive_scripts_are_loaded_str] = True
        
        return ReactBlockNode.Context(parent_context, id, need_load_scripts)

@register.tag('#' + ReactBlockNode.tag_name)
def do_reactblock(parser, token):
    nodelist = parser.parse(('/' + ReactBlockNode.tag_name,))
    parser.delete_first_token()

    return ReactBlockNode(nodelist)

reactcontent_node_str = 'reactcontent_node'

class ReactDefNode(ReactNode):
    tag_name = 'def'

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

@register.tag('#/' + ReactDefNode.tag_name)
def do_reactdef(parser: template.base.Parser, token: template.base.Token):
    # TODO: Make the difference between bounded and unbounded expressions(i.e. if reactivity change them).
    try:
        tag_name, var_name, var_val_expression = tuple(smart_split(token.contents, whitespaces, common_delimiters))
    except ValueError:
        raise template.TemplateSyntaxError(
            "%r tag requires exactly two arguments" % token.contents.split()[0]
        )

    return ReactDefNode(var_name, parse_expression(var_val_expression))

class ReactTagNode(ReactNode):
    tag_name = 'tag'

    class RenderData(ReactRerenderableContext):
        def __init__(self, parent: ReactContext, id: str, self_enclosed: bool, html_tag: str,
            html_attributes: Dict[str, Expression]):

            super().__init__(id=id, parent=parent, fully_reactive=True)
            self.self_enclosed: bool = self_enclosed
            self.html_tag: str = html_tag
            self.control_var_name: str = f'__react_control_{id}'
            self.html_attributes: Dict[str, Expression] = html_attributes
    
        def var_js(self, var):
            return f'{var.name}_tag{self.id}'
        
        def compute_attributes(self) -> Dict[str, Expression]:
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
        
        def make_control_var(self) -> ReactVar:
            control_var = ReactVar(self.control_var_name, value_to_expression({'first': True}))
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
        
        def set_attribute_js_expression(self, element_js: str, attribute: str, js_expression: str) -> str:
            if attribute.startswith('data-'):
                return f"{element_js}.setAttribute({attribute}, {js_expression});"
            else:
                return f"{element_js}.{attribute} = {js_expression};"

        def render_script(self, subtree: Optional[List]) -> str:
            script = self.render_script_inside(subtree)
            
            self.clear_render()

            computed_attributes = self.compute_attributes()
            id_js_expression = computed_attributes['id'].eval_js_and_hooks(self)[0]

            attribute_js_expressions_and_hooks = {key: expression.eval_js_and_hooks(self) \
                for key, expression in computed_attributes.items()}

            js_rerender_expression, hooks_inside = self.render_js_and_hooks_inside(subtree)

            hooks = set(hooks_inside)

            control_var = self.make_control_var()

            first_expression = SettablePropertyExpression(VariableExpression(self.control_var_name), ['first'])

            def change_attribute(id_js_expression: str, attribute: str, js_expression: str):
                return f"() => {{ {self.set_attribute_js_expression(f'document.getElementById({id_js_expression})', attribute, js_expression)} }}"

            # TODO: Handle the unsupported style and events setting in old IE versions?
            
            script.initial_post_calc = '( () => {\n' + \
                '// Tag post calc\n' + \
                'function proc() {\n' + \
                f'if(!{first_expression.eval_js_and_hooks(self)[0]}) {{\n' + \
                script.destructor + \
                '\n' + first_expression.js_set(self, 'false') + \
                '\n}\n' + \
                script.initial_pre_calc + \
                (f'document.getElementById({id_js_expression}).innerHTML = ' + js_rerender_expression + ';\n'
                if not self.self_enclosed else '') + \
                script.initial_post_calc + '\n' + \
                ';}\n' + \
                '\n'.join( chain.from_iterable((f'{control_var.js_get()}.attachment_attribute_{hook.get_name()} = ' + \
                hook.js_attach(change_attribute(id_js_expression, attribute, js_expression), True) \
                for hook in _hooks) \
                for attribute, (js_expression, _hooks) in attribute_js_expressions_and_hooks.items())) + \
                ';\n' + \
                '\n'.join((f'{control_var.js_get()}.attachment_content_{hook.get_name()} = {hook.js_attach("proc", True)};' for hook in hooks)) + \
                script.initial_post_calc + \
                '\n})();'

            script.destructor = '( () => {\n' + \
                '// Tag destructor\n' + \
                '\n'.join((hook.js_detach(f'{control_var.js_get()}.attachment_content_{hook.get_name()}') for hook in hooks)) + \
                '\n' + script.destructor + '} )();'
            
            return script
    
    def __init__(self, nodelist: Optional[template.NodeList], self_enclosed: bool, html_tag: str,
        html_attributes: Dict[str, Expression], html_unary_attributes: Set[str]):
        
        self.self_enclosed: bool = self_enclosed
        self.html_tag: str = html_tag
        self.html_attributes = html_attributes
        # TODO: Use html_unary_attributes somehow. Maybe import them to self.html_attributes with constant true value?

        super().__init__(nodelist=nodelist)
    
    def make_context(self, parent_context: Optional[ReactContext], template_context: template.Context) -> ReactContext:
        id = f'tag_{next_id_by_context(template_context, "__react_tag")}'

        parsed_html_attributes = {key: val.reduce(template_context) for key, val in self.html_attributes.items()}

        return ReactTagNode.RenderData(parent_context, id, self.self_enclosed, self.html_tag, parsed_html_attributes)

def parse_reacttag_internal(html_tag: str, bits_after: List[str], nodelist: template.NodeList):
    html_attributes_unparsed, html_unary_attributes_ = split_kwargs(bits_after)
    html_attributes = { attribute: parse_expression(val_unparsed) for attribute, val_unparsed in html_attributes_unparsed }
    html_unary_attributes = set(html_unary_attributes_)
    
    self_enclosed = (nodelist is None)

    return ReactTagNode(nodelist, self_enclosed, html_tag, html_attributes, html_unary_attributes)

@register.tag('#' + ReactTagNode.tag_name)
@register.tag('#/' + ReactTagNode.tag_name)
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
            'the html tag is self enclosed (i.e. ended with / in html tag name or at the last aurgument list).')
    
    if self_enclosed:
        nodelist = None
    else:
        nodelist = parser.parse(('/' + ReactTagNode.tag_name,))
        parser.delete_first_token()

    return parse_reacttag_internal(html_tag, remaining_bits, nodelist)

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
            'The first tag <...> is empty inside a reactive generic block {% # %}...{% / %}'
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
            'Found more than one slash (\'/\') in start tag <..> while parsimg a reactive generic block {% # %}...{% / %}'
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
                'Found more than one slash (\'/\') which is not in the right place in start tag <..> ' + \
                'while parsimg a reactive generic block {% # %}...{% / %}'
                )
    
    if html_tag == 'script':
        raise template.TemplateSyntaxError(
            'Script interactive tag is not supported!'
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
                'Found a slash (\'/\') in start tag <..> while parsimg a reactive generic block {% # %}...{% / %}, ' + \
                'which indicate that the tag is self enclosing, but found more HTML code or or non-whitespace text after.'
                )

        if not end.endswith('>'):
            raise template.TemplateSyntaxError(
                'A reactive generic block {% # %}...{% / %} must be ended with \'>\' (and possibly whitespaces after).'
                )
        
        end = end[:-1]
        end_parts = list(smart_split(end, ['<'], skip_blank=False))
        if len(end_parts) < 2:
            raise template.TemplateSyntaxError(
                'Missing \'<\' on the closing tag while parsimg a reactive generic block {% # %}...{% / %}'
                )
        
        end_bits = list(smart_split(end_parts[-1], whitespaces))
        if not end_bits:
            raise template.TemplateSyntaxError(
                'The first tag <...> is empty inside a reactive generic block {% # %}...{% / %}'
                )
        
        if not end_bits[0].startswith('/'):
            raise template.TemplateSyntaxError(
                'Missing \'/\' on the start of the closing tag, while parsimg a reactive generic block {% # %}...{% / %}'
                )
        
        end_seperated_by_slash = list(smart_split(end_parts[-1], ['/'], skip_blank=False))
        if len(end_seperated_by_slash) > 2:
            raise template.TemplateSyntaxError(
                'Found more than one slash (\'/\') in closing tag </..> while parsimg a reactive generic block {% # %}...{% / %}'
                )
        
        end_bits[0] = end_bits[0][1:]# Remove the slash '/'
        if not end_bits[0]:# If now the part string is empty after removing the slash '/'
            end_bits = end_bits[1:]
        
        if len(end_bits) != 1:
            raise template.TemplateSyntaxError(
                'There should be exactly one word after the slash (\'/\') in closing tag </..> ' + \
                    '(found while parsimg a reactive generic block {% # %}...{% / %})'
                )
        
        if end_bits[0] != html_tag:
            raise template.TemplateSyntaxError(
                f'There name of the closing tag ({end_bits[0]}) must be identical to the name of the opening tag ({html_tag}) ' + \
                    '(found while parsimg a reactive generic block {% # %}...{% / %})'
                )

        end_location = len(end) - len(end_parts[-1]) - 1
        nodelist[-1].s = nodelist[-1].s[:end_location]
    else:
        if not self_enclosed:
            raise template.TemplateSyntaxError(
                'A slash (\'/\') in start tag <..> was not found while parsimg a reactive generic block {% # %}...{% / %}, ' + \
                'which indicate that the tag is not self enclosing, but not found more HTML code or or non-whitespace text after.'
                )

        nodelist = None

    return parse_reacttag_internal(html_tag, bits_after, nodelist)

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

                iter_data: Dict[str, ReactValType] = {('var_' + var.js()): var for var in vars}

                iters.append(iter_data)

                self.clear_render()
            
            control_data = {'last_length': len(iters), 'iters': iters}
            if self.key_expression:
                control_data['key_table'] = {}

            control_var = ReactVar(self.control_var_name, value_to_expression(control_data))
            
            self.add_var(control_var)
            
            return ''.join(html_outputs)
        
        def get_def(self, control_var: ReactVar, var: ReactVar,
            other_js_expression: Optional[str] = None, iteration_expression: str = None):

            val = (iteration_expression if (iteration_expression is not None) else (control_var.js_get() + ".iters[i]")) + \
                ".var_" + var.js() if (other_js_expression is None) else other_js_expression
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

            control_var = ReactVar(self.control_var_name, None)
            self.add_var(control_var)

            defs = '\n'.join(self.get_def(control_var, var) for var in vars)

            def get_set(var: ReactVar, other_js_expression: Optional[str] = None):
                if other_js_expression is None and var.expression is None:
                    return ''
                # otherwise

                return var.js_set(
                    var.expression.eval_js_and_hooks(self)[0] if other_js_expression is None else other_js_expression,
                    alt_js_name=f'{control_var.js_get()}.iters[i].var_{var.js()}')

            def get_reactive_js(var: ReactVar, other_js_expression: Optional[str] = None):
                return f'var_{var.js()}:' + (var.reactive_val_js(self) if other_js_expression is None else other_js_expression)

            if self.key_expression:
                defs_but_iter_and_id_keyed = '\n'.join(
                    self.get_def(control_var, var, iteration_expression='__reactive_iter_store') \
                    for var in vars_but_iter if var is not iter_id_var)

                tag_context: ReactTagNode.RenderData = subtree[0][0]
                tag_subtree = subtree[0][1]

                computed_attributes = tag_context.compute_attributes()

                tag_id_js = computed_attributes["id"].eval_js_and_hooks(self)[0]
            
                self.clear_render()

                # Redefine vars after clear
                iter_var = ReactVar(self.var_name, None)
                self.add_var(iter_var)

                iter_id_var = ReactVar('__react_iter_id',
                    SumExpression([StringExpression('key_'), self.key_expression]) if \
                        self.key_expression else NativeVariableExpression('i'))
                self.add_var(iter_id_var)

                tag_inner_js = tag_context.render_js_and_hooks_inside(tag_subtree)[0]

                update_for_code = \
                f'const react_iter = {iter_val_js};\n' + \
                f'const __reactive_old_iters = {control_var.js_get()}.iters;\n' + \
                f'{control_var.js_get()}.iters = [];\n' + \
                'var current_old_element = null;\n' + \
                'var __reactive_need_work = true;\n' + \
                'if (__reactive_old_iters.length === 0) {\n' + \
                    'if (react_iter.length !== 0) {\n' + \
                        f'{control_var.js_get()}.last_length = 0;// TODO: Remove this non-useful last_length\n' + \
                        control_var.js_notify() + '\n' + \
                        '__reactive_need_work = false;\n' + \
                    '}\n' + \
                '} else {\n' + \
                    self.get_def(control_var, iter_var, iteration_expression='__reactive_old_iters[0]') + '\n' + \
                    f'const {iter_id_var.js()} = {iter_id_var.reactive_val_js(self)};\n' + \
                    f'current_old_element = document.getElementById({tag_id_js});\n' + \
                '}\n' + \
                'if (__reactive_need_work) {\n' + \
                'for (var i = 0; i < react_iter.length; ++i) {\n' + \
                    f'const {iter_var.js()} = {iter_var.reactive_val_js(self, "react_iter[i]")};\n' + \
                    f'const {iter_id_var.js()} = {iter_id_var.reactive_val_js(self)};\n' + \
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
                        iter_var.js_set(iter_var.js_get(), f'__reactive_iter_store.var_{iter_var.js()}') + '\n' + \
                    '} else {\n' + \
                        '__reactive_iter_store = {' + \
                        ','.join(chain((get_reactive_js(iter_var, iter_var.js()),), \
                            (get_reactive_js(var) for var in vars_but_iter))) + \
                        '};\n' + \
                        f'{control_var.js_get()}.key_table[{iter_id_var.js_get()}] = __reactive_iter_store;\n' + \
                        defs_but_iter_and_id_keyed + '\n' + \
                        script.initial_pre_calc + '\n' + \
                        f'const current_element = document.createElement(\'{tag_context.html_tag}\');\n' + \
                        '\n'.join(tag_context.set_attribute_js_expression("current_element", attribute,
                            val.eval_js_and_hooks(self)[0]) for attribute, val in computed_attributes.items()) + '\n' + \
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
                    '}\n' + \
                '}\n' + \
                '}\n'

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
                    '\n'.join((f'const {var.js()} = {var.reactive_val_js(self)};' for var in vars_but_iter)) + '\n' + \
                    f'if (length_changed) {{\n' + \
                    f'{control_var.js_get()}.iters.push({{' + \
                    ','.join((f'var_{var.js()}:{var.js()}' for var in vars)) + \
                    '} ); } else {\n' + \
                    '\n'.join(get_set(var, var.js_get()) for var in vars) + '\n' \
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
            
            script.destructor = '( () => {' + \
                f'// For loop destructor\n' + \
                f'for (var i = 0; i < {control_var.js_get()}.iters.length; ++i) {{\n' + \
                '\n'.join((hook.js_detach(f'{control_var.js_get()}.attachment_{hook.get_name()}') for hook in iter_hooks)) + \
                '\n' + defs + '\n' + script.destructor + '} } )();'

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
        if len(nodelist) != 1 and not isinstance(nodelist[0], ReactTagNode):
            raise template.TemplateSyntaxError('Error: Keyed loops must have one one child node which is a reactive tag node.')

    return ReactForNode(nodelist, var_name, parse_expression(iter_expression),
        key_expression=(parse_expression(key_expression) if key_expression is not None else None))

class ReactIfNode(ReactNode):
    tag_name = 'if'

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

@register.tag('#' + ReactIfNode.tag_name)
def do_reactif(parser: template.base.Parser, token: template.base.Token):
    # TODO: add support for else and elif in the future

    bits = list(smart_split(token.contents, whitespaces, common_delimiters))

    if len(bits) != 2:
        raise template.TemplateSyntaxError(
            "%r tag requires exactly two arguments" % token.contents.split()[0]
        )
    # otherwise

    expression = bits[1]

    nodelist = parser.parse(('/' + ReactIfNode.tag_name,))
    parser.delete_first_token()

    return ReactIfNode(nodelist, parse_expression(expression))

class ReactPrintNode(ReactNode):
    tag_name = 'print'

    class Context(ReactRerenderableContext):
        def __init__(self, parent, id: str, expression: Expression):
            self.expression: Expression = expression
            super().__init__(id=id, parent=parent, fully_reactive=True)
    
        def var_js(self, var):
            return f'{var.name}_{self.id}'

        def make_vars(self) -> Tuple[ReactVar, ReactVar]:
            control_var = ReactVar('print_control', value_to_expression({}))
            self.add_var(control_var)

            print_var = ReactVar('print_var', self.expression)
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
                # TODO: HTML excaping also after reaction hook, in js
                return str(val_initial)

        def render_js_and_hooks(self, subtree: List) -> Tuple[str, Iterable[ReactHook]]:
            # TODO: HTML escaping?
            
            control_var, print_var = self.make_vars()

            return VariableExpression(print_var.name).eval_js_html_output_and_hooks(self)[0], [print_var]

        def render_script(self, subtree: Optional[List]) -> str:
            # TODO: HTML escaping?
            js_html_expression, hooks = self.expression.eval_js_html_output_and_hooks(self)
            
            control_var, print_var = self.make_vars()

            script = ResorceScript()
            
            script.initial_post_calc = \
                '{\n' + \
                    'function proc() {\n' + \
                        print_var.js_set(js_html_expression) + \
                    '}\n' + \
                    '\n'.join((f'{control_var.js_get()}.attachment_{hook.get_name()} = {hook.js_attach("proc", True)};' \
                        for hook in hooks)) + \
                '\n}\n'
            
            script.destructor = \
                '{\n' + \
                    '\n'.join((hook.js_detach(f'{control_var.js_get()}.attachment_{hook.get_name()}') \
                        for hook in hooks)) + \
                '\n}\n'
            
            return script

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

@register.tag('#' + ReactSetNode.tag_name)
def do_reactset(parser: template.base.Parser, token: template.base.Token):
    """Set current present value to a js expression"""

    # TODO: Make the difference between bounded and unbounded expressions. (Currently unbound)

    bits = list(smart_split(token.contents, whitespaces, common_delimiters))

    if len(bits) != 2:
        raise template.TemplateSyntaxError(
            "%r tag requires at exactly two arguments" % token.contents.split()[0]
        )
    # otherwise

    var_expression = bits[1]
    
    nodelist: template.NodeList = parser.parse(('/' + ReactSetNode.tag_name,))
    parser.delete_first_token()

    expression = parse_expression(var_expression)

    if not isinstance(expression, SettableExpression):
        raise template.TemplateSyntaxError(
            "%r tag requires the first expression to be reactively setable." % token.contents.split()[0]
        )

    return ReactSetNode(nodelist, expression)

class ReactNotifyNode(ReactNode):
    tag_name = 'notify'

    class Context(ReactContext):
        def __init__(self, parent, settable_expression: SettableExpression):
            self.settable_expression: SettableExpression = settable_expression
            super().__init__(id='', parent=parent, fully_reactive=False)

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