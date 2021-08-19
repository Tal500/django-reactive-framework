from typing import Iterator, List, Optional, Tuple


sq = "'"
dq = '"'

def str_repr_s(string: str):
    return sq + string.translate(str.maketrans({'\\': '\\\\', sq: "\\'", '\n': '\\n', '\t': '\\t'})) + sq

def str_repr_d(string: str):
    return dq + string.translate(str.maketrans({'\\': '\\\\', dq: '\\"', '\n': '\\n', '\t': '\\t'})) + dq

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

def parse_string(expression: str, delimiter: str) -> Optional[str]:
    if result := parse_first_string(expression, delimiter):
        result_str, i = result
        if i == len(expression):
            return result_str
    # otherwise

    return None

common_delimiters = [('(', ')'), ('[', ']'), ('{', '}'), ('"', '"'), ("'", "'")]

def match_and_return_second(char: str, pairs: List[Tuple[str, str]]):
    for first, second in pairs:
        if char == first:
            return second
    # otherwise

    return None

# TODO: Handle correct string parsing, and raise exception on syntax error? (use parse_first_string)
def smart_split(expression: str, seperator: str, delimiters: List[Tuple[str, str]]) -> Iterator[str]:
    i = 0

    end_delimiters_stack = []

    for loc, char in enumerate(expression):
        if len(end_delimiters_stack) == 0:
            if char == seperator and len(end_delimiters_stack) == 0:
                yield expression[i:loc]
                i = loc + 1
                continue
        else:
            if char == end_delimiters_stack[-1]:
                end_delimiters_stack.pop()
                continue
        # otherwise

        if end_delimiter := match_and_return_second(char, delimiters):
            end_delimiters_stack.append(end_delimiter)\

    yield expression[i:]

def manual_non_empty_sum(iter):
    is_first = True
    for element in iter:
        if is_first:
            sum = element
            is_first = False
        else:
            sum = sum + element
    
    return sum