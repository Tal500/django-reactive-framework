from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from django import template


sq = "'"
dq = '"'

def str_repr(val: Any, delimiter: str):
    return delimiter + \
        str(val).translate(str.maketrans({'\\': '\\\\', delimiter: "\\" + delimiter, '\n': '\\n', '\t': '\\t'})) + \
        delimiter

def str_repr_s(val: Any):
    return str_repr(val, sq)

def str_repr_d(val: Any):
    return str_repr(val, dq)

def parse_first_string(expression: str, delimiter: str) -> Optional[Tuple[str, int]]:
    """ Return a tupple first substring found and the location to the next character, unless failed and then None. """
    if (not expression) or expression[0] != delimiter:
        return None
    # otherwise

    i = 1
    output = []

    while i < len(expression):
        char = expression[i]
        if char == delimiter:
            return ''.join(output), (i + 1)
        elif char == '\\':
            next_char = expression[i+1]
            if next_char == delimiter:
                output.append(delimiter)
            if next_char == '\\':
                output.append('\\')
            if next_char == 'n':
                output.append('\n')
            if next_char == 't':
                output.append('\t')
            else:
                return None

            i += 2
        else:
            output.append(char)
            i += 1
    
    # otherwise (expression was ended before delimiter)
    return None

def parse_string(expression: str, delimiter: str) -> Optional[str]:
    if result := parse_first_string(expression, delimiter):
        result_str, i = result
        if i == len(expression):
            return result_str
    # otherwise

    return None

common_delimiters = [
    ('(', ')', None),
    ('[', ']', None),
    ('{', '}', None),
    ('"', '"', lambda expression: parse_first_string(expression, '"')),
    ("'", "'", lambda expression: parse_first_string(expression, "'"))]

def match_first(char: str, tuples: List[Tuple]):
    for t in tuples:
        if char == t[0]:
            return t
    # otherwise

    return None

def smart_split(expression: str, seperator: str,
    delimiters: List[Tuple[str, str, Any]] = common_delimiters, skip_blank: bool = True) -> Iterator[str]:
    i = 0
    loc = 0

    end_delimiters_stack = []

    def process_delimiter(tuple, j: int):
        section = expression[j:]
        begin_delimiter, end_delimiter, processor = tuple
        if processor is None:
            end_delimiters_stack.append(end_delimiter)
            return j + 1
        else:
            result: Optional[Tuple[str, int]] = processor(section)
            if result is None:
                raise template.TemplateSyntaxError(f'Cannot extract starting substring from: {section}')
            else:
                assert(0 != result[1])
                return j + result[1]

    while loc < len(expression):
        char = expression[loc]

        if len(end_delimiters_stack) == 0:
            if char == seperator and len(end_delimiters_stack) == 0:
                if i != loc or (not skip_blank):
                    yield expression[i:loc]
                i = loc + 1
            elif tuple := match_first(char, delimiters):
                loc = process_delimiter(tuple, loc) - 1
        else:
            if char == end_delimiters_stack[-1]:
                end_delimiters_stack.pop()
            elif tuple := match_first(char, delimiters):
                loc = process_delimiter(tuple, loc) - 1
        
        loc += 1

    yield expression[i:]

def split_assignment(assignment: str) -> Tuple[str, str]:
    iter = smart_split(assignment, '=', skip_blank=False)

    try:
        lhs = next(iter)
        rhs = next(iter)
        try:
            next(iter)
            raise template.TemplateSyntaxError(
                "More than one assignment operator ('=') was seen while attempting to parse an assinment")
        except StopIteration:
            pass
    except StopIteration:
        raise template.TemplateSyntaxError('Error in parsing assignment, it should be in the form: lhs = rhs')
    
    return lhs, rhs

def split_kwargs(assignments: Iterable[str]) -> Iterable[Tuple[str, str]]:
    return (split_assignment(assignment) for assignment in assignments)

def manual_non_empty_sum(iter):
    is_first: bool = True
    is_string: bool = False
    for element in iter:
        if is_first:
            sum = element
            is_first = False

            if isinstance(element, str):
                is_string = True
        else:
            if is_string:
                element = str(element)
            
            sum = sum + element
    
    return sum

whitespaces = [' ', '\t', '\n']

def remove_whitespaces_on_boundaries(s: str) -> str:
    for i in range(len(s)):
        if s[i] not in whitespaces:
            break
    
    if i == len(s) - 1 and s[i] in whitespaces:
        return ''
    # otherwise

    for j in range(len(s) - 1, i - 1, -1):
        if s[j] not in whitespaces:
            break
    
    return s[i:j+1]

def reduce_nodelist(nodelist: template.NodeList) -> template.NodeList:
    """
    A function which trims whitespaces and comment nodes from a nodelist.
    Notice that this function might remove a relevant regular html space ' ', 
      so use with care.
    """

    new_nodelist = template.NodeList()
    for node in nodelist:
        if isinstance(node, template.defaulttags.CommentNode):
            continue
        elif isinstance(node, template.base.TextNode):
            print('str before:', node.s)
            test = remove_whitespaces_on_boundaries(node.s)
            print('str after:', test)
            if not test:
                print('skipping', node.s)
                continue
        
        new_nodelist.append(node)
    
    return new_nodelist

def is_iterable_empty(iterable: Iterable) -> bool:
    for e in iterable:
        return False
    # otherwise
    
    return True