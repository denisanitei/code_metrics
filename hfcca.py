#!/usr/bin/env python
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
#  author: terry.yinzhe@gmail.com
#

"""
hfcca is a simple code complexity analyzer without caring about the C/C++ 
header files or Java imports. It can deal with

* Java
* /C/C++
* Objective C.

It counts 

* the nloc (lines of code without comments), 
* CCN (cyclomatic complexity number),
* token count of functions.
* parameter count of functions.

You can set limitation for CCN (-C), the number of parameters (-a). Functions
that exceed these limitations will generate warnings. The exit code of hfcca
will be none-Zero if there are warnings. 

This tool actually calculates how complex the code 'looks' rather than how
complex the code real 'is'. People will need this tool because it's often very
hard to get all the included folders and files right when they are complicated.
But we don't really need that kind of accuracy when come to cyclomatic
complexity.

It requires python2.6 or above (early versions are not verified).
"""

VERSION = "1.7.1"

import itertools
import re
import sys
import yaml
from lxml import etree

DEFAULT_CCN_THRESHOLD = 15

ASSIGN_OPERATORS = {
    '=', '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '<<=', '>>='
}
INC_DEC_OPERATORS = {
    '++', '--'
}
CONTROL_FLOW_KEYWORDS = {
    'if', 'for', 'while', 'switch', 'do'
}
JUMP_FLOW_KEYWORDS = {
    'return', 'goto', 'break', 'continue'
}

class FunctionInfo(object):
    ''' Statistic information of a function.
    '''
    def __init__(self, name, start_line):
        self.cyclomatic_complexity    = 1
        self.nloc                     = 0
        self.sloc                     = 0
        self.eloc                     = 0
        self.token_count              = 0
        self.name                     = name
        self.function_name_with_param = name
        self.start_line               = start_line
        self.parameter_count          = 0
        self.comment_count            = 0
        self.cdrp                     = 0.0
        self.return_count             = 0
        self.max_nesting_depth        = 0
        self.statement_count          = 0
        self.goto_count               = 0
        self._called_functions        = set()
        self.called_count             = 0
        self.calling_functions_count  = 0
        self.path_count               = 1
        self.recursion_count          = 0
        self.dead_code_count          = 0
        self.vocf                     = 0.0
        self.average_statement_size   = 0.0
        self.call_depth               = 1
        self.if_without_else_count    = 0
        self.unused_variables_count   = 0
        self.filename                 = ""

    def __eq__(self, other):
        return other == self.name

    def add_to_function_name(self, app):
        self.name += app
        self.function_name_with_param += app

    def long_name(self):
        return self.function_name_with_param

    def add_to_long_name(self, app):
        self.function_name_with_param += app

    def add_condition(self):
        self.cyclomatic_complexity += 1

    def add_token(self):
        self.token_count += 1

    def add_non_comment_line(self):
        self.nloc += 1

    def add_sloc(self):
        self.sloc += 1

    def add_eloc(self):
        self.eloc += 1

    def add_comment(self, count=1):
        self.comment_count += count

    def update_cdrp(self):
        _denom = self.nloc + self.comment_count
        if _denom > 0:
            self.cdrp = round((float(self.comment_count) / float(_denom)) * 100.0, 2)
        else:
            self.cdrp = 0.0

    def add_return(self):
        self.return_count += 1

    def add_statement(self):
        self.statement_count += 1

    def set_statement_count(self, count):
        self.statement_count = count if count >= 0 else 0

    def add_goto(self):
        self.goto_count += 1

    def add_called_function(self, callee):
        self._called_functions.add(callee)
        self.called_count = len(self._called_functions)
        if callee == self.name:
            self.recursion_count += 1
        else:
            # call to another function
            pass

    def set_path_count(self, count):
        self.path_count = _cap_his_path(count if count >= 1 else 1)

    def add_path_branch(self):
        self.path_count = _cap_his_path(self.path_count * 2)

    def add_dead_code(self):
        self.dead_code_count += 1

    def add_if_without_else(self):
        self.if_without_else_count += 1

    def add_unused_variable(self):
        self.unused_variables_count += 1

    def set_vocf(self, value):
        _val                        = round(float(value), 2) if value > 0.0 else 0.0
        self.vocf                   = _val
        self.average_statement_size = _val

    def finalize_metrics(self):
        self.called_count           = len(self._called_functions)
        self.average_statement_size = self.vocf
        self.update_cdrp()

    def update_nesting_depth(self, depth):
        if depth > self.max_nesting_depth:
            self.max_nesting_depth = depth
        else:
            # depth does not exceed maximum
            pass

    def add_parameter(self, token):
        if self.parameter_count == 0:
            self.parameter_count = 1
        else:
            # already at least one parameter
            pass
        if token == ",":
            self.parameter_count += 1
        else:
            # not a parameter separator
            pass

"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
class FileInformation(list):
    ''' Statistic information of a source file.
        Including all the functions and the file summary.
    '''
    def __init__(self, filename):
        list.__init__(self)
        self.filename                     = filename
        self.static_declarations_count    = 0
        self.line_count                   = 0
        self.unreachable_statements_count = 0
        self.sloc                         = 0
        self.average_SLOC                 = 0.0
        self.eloc                         = 0
        self.average_ELOC                 = 0.0

    def summarize(self, NLOC, comm_cnt):
        self.nloc         = NLOC
        self.average_NLOC = 0.0
        self.average_CCN  = 0.0
        self.average_token = 0.0
        self.average_SLOC = 0.0
        self.average_ELOC = 0.0

        _nloc          = 0
        _ccn           = 0
        _token         = 0
        _sloc          = 0
        _eloc          = 0
        _comment_count = comm_cnt
        for _fun in self:
            _nloc          += _fun.nloc
            _ccn           += _fun.cyclomatic_complexity
            _token         += _fun.token_count
            _comment_count += _fun.comment_count
            _sloc          += _fun.sloc
            _eloc          += _fun.eloc
        _func_count = len(self)
        if _func_count > 0:
            self.average_NLOC  = _nloc / _func_count
            self.average_CCN   = _ccn / _func_count
            self.average_token = _token / _func_count
            self.average_SLOC  = _sloc / _func_count
            self.average_ELOC  = _eloc / _func_count
        else:
            # no functions in file
            pass

        self.com_cnt = _comment_count
        self.cdrp    = (_comment_count / (NLOC + _comment_count)) * 100 if (NLOC + _comment_count) != 0 else 0
        self.ccrp    = self.cdrp
        self.CCN     = _ccn
        self.token   = _token
        self.sloc    = _sloc
        self.eloc    = _eloc

MAX_HIS_PATH_COUNT = 1000000000

_STMT_BOUNDARY_KEYWORDS = {
    'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'default',
    'return', 'break', 'continue', 'goto', 'try', 'catch', 'throw'
}
_TRUE_CONST_TOKENS = {
    '1', '1U', '1u', '1L', '1l', '1UL', '1ul', 'true', 'TRUE', 'STD_ON'
}
_FALSE_CONST_TOKENS = {
    '0', '0U', '0u', '0L', '0l', '0UL', '0ul', 'false', 'FALSE', 'STD_OFF'
}


def _cap_his_path(value):
    _capped = value if value < MAX_HIS_PATH_COUNT else MAX_HIS_PATH_COUNT
    return _capped


def _strip_outer_parens(tokens):
    _slice = list(tokens)
    while len(_slice) >= 2 and _slice[0] == '(' and _slice[-1] == ')':
        _depth = 0
        _valid = True
        for _idx in range(len(_slice) - 1):
            if _slice[_idx] == '(':
                _depth += 1
            elif _slice[_idx] == ')':
                _depth -= 1
                if _depth == 0:
                    _valid = False
                    break
            else:
                # token inside parentheses
                pass
        if _valid and _depth == 1:
            _slice = _slice[1:-1]
        else:
            break
    return _slice


def _is_always_true_cond(tokens):
    _stripped = _strip_outer_parens(tokens)
    _is_true  = (len(_stripped) == 1 and _stripped[0] in _TRUE_CONST_TOKENS)
    return _is_true


def _is_always_false_cond(tokens):
    _stripped = _strip_outer_parens(tokens)
    _is_false = (len(_stripped) == 1 and _stripped[0] in _FALSE_CONST_TOKENS)
    return _is_false


def _find_matching_delim(tokens, open_idx, limit, open_tok, close_tok):
    _depth = 0
    _idx   = open_idx
    while _idx < limit:
        _tok = tokens[_idx]
        if _tok == open_tok:
            _depth += 1
        elif _tok == close_tok:
            _depth -= 1
            if _depth <= 0:
                return _idx
        else:
            # inner token
            pass
        _idx += 1
    return limit - 1


def _is_balanced_slice(tokens):
    _b_depth = 0
    _p_depth = 0
    for _tok in tokens:
        if isinstance(_tok, tuple):
            continue
        if _tok == '{':
            _b_depth += 1
        elif _tok == '}':
            _b_depth -= 1
            if _b_depth < 0:
                return False
        elif _tok == '(':
            _p_depth += 1
        elif _tok == ')':
            _p_depth -= 1
            if _p_depth < 0:
                return False
        else:
            # normal token
            pass
    return (_b_depth == 0) and (_p_depth == 0)


def _normalize_pp_blocks(tokens):
    if '#if' not in tokens and '#else' not in tokens and '#elif' not in tokens and '#endif' not in tokens:
        return tokens
    _stack = [[[]]]
    for _tok in tokens:
        if _tok == '#if':
            _stack.append([[]])
        elif _tok in ('#elif', '#else'):
            if len(_stack) > 1:
                _stack[-1].append([])
            else:
                # unmatched preprocessor branch token ignored
                pass
        elif _tok == '#endif':
            if len(_stack) > 1:
                _branches = _stack.pop()
                if all(_is_balanced_slice(_br) for _br in _branches):
                    _branch_tuples = tuple(tuple(_br) for _br in _branches)
                    _stack[-1][-1].append(('#PP_BRANCHES', _branch_tuples))
                else:
                    # unbalanced preprocessor branches: keep primary #if branch to preserve brace balance
                    _stack[-1][-1].extend(_branches[0])
            else:
                # unmatched #endif ignored
                pass
        else:
            _stack[-1][-1].append(_tok)
    while len(_stack) > 1:
        _unclosed = _stack.pop()
        _stack[-1][-1].extend(_unclosed[0])
    return _stack[0][0]


def _expr_his_paths(expr_tokens):
    if '?' not in expr_tokens:
        return 1

    # split on top-level comma expressions or argument lists
    _parts   = []
    _cur     = []
    _p_depth = 0
    _b_depth = 0
    _s_depth = 0
    for _tok in expr_tokens:
        if isinstance(_tok, tuple):
            continue
        if _tok == '(':
            _p_depth += 1
            _cur.append(_tok)
        elif _tok == ')':
            if _p_depth > 0:
                _p_depth -= 1
            _cur.append(_tok)
        elif _tok == '{':
            _b_depth += 1
            _cur.append(_tok)
        elif _tok == '}':
            if _b_depth > 0:
                _b_depth -= 1
            _cur.append(_tok)
        elif _tok == '[':
            _s_depth += 1
            _cur.append(_tok)
        elif _tok == ']':
            if _s_depth > 0:
                _s_depth -= 1
            _cur.append(_tok)
        elif _tok == ',' and _p_depth == 0 and _b_depth == 0 and _s_depth == 0:
            _parts.append(_cur)
            _cur = []
        else:
            _cur.append(_tok)
    _parts.append(_cur)

    if len(_parts) > 1:
        _prod = 1
        for _part in _parts:
            _prod = _cap_his_path(_prod * _expr_his_paths(_part))
        return _prod

    _part    = _parts[0]
    _p_depth = 0
    _b_depth = 0
    _s_depth = 0
    _q_idx   = -1
    for _i, _tok in enumerate(_part):
        if _tok == '(':
            _p_depth += 1
        elif _tok == ')' and _p_depth > 0:
            _p_depth -= 1
        elif _tok == '{':
            _b_depth += 1
        elif _tok == '}' and _b_depth > 0:
            _b_depth -= 1
        elif _tok == '[':
            _s_depth += 1
        elif _tok == ']' and _s_depth > 0:
            _s_depth -= 1
        elif _tok == '?' and _p_depth == 0 and _b_depth == 0 and _s_depth == 0:
            _q_idx = _i
            break
        else:
            # continue scanning expression
            pass

    if _q_idx != -1:
        _q_nest    = 1
        _p_depth   = 0
        _b_depth   = 0
        _s_depth   = 0
        _colon_idx = -1
        for _j in range(_q_idx + 1, len(_part)):
            _tok = _part[_j]
            if _tok == '(':
                _p_depth += 1
            elif _tok == ')' and _p_depth > 0:
                _p_depth -= 1
            elif _tok == '{':
                _b_depth += 1
            elif _tok == '}' and _b_depth > 0:
                _b_depth -= 1
            elif _tok == '[':
                _s_depth += 1
            elif _tok == ']' and _s_depth > 0:
                _s_depth -= 1
            elif _p_depth == 0 and _b_depth == 0 and _s_depth == 0:
                if _tok == '?':
                    _q_nest += 1
                elif _tok == ':':
                    _q_nest -= 1
                    if _q_nest == 0:
                        _colon_idx = _j
                        break
                else:
                    # token inside ternary arm
                    pass
            else:
                # nested bracket token
                pass
        if _colon_idx != -1:
            _p_cond  = _expr_his_paths(_part[:_q_idx])
            _p_true  = _expr_his_paths(_part[_q_idx + 1:_colon_idx])
            _p_false = _expr_his_paths(_part[_colon_idx + 1:])
            return _cap_his_path(_p_cond * (_p_true + _p_false))

    # no top-level '?', multiply paths of any parenthesized or bracketed sub-expressions
    _prod  = 1
    _i     = 0
    _limit = len(_part)
    while _i < _limit:
        _tok = _part[_i]
        if _tok == '(':
            _close = _find_matching_delim(_part, _i, _limit, '(', ')')
            _prod  = _cap_his_path(_prod * _expr_his_paths(_part[_i + 1:_close]))
            _i     = _close + 1
        elif _tok == '[':
            _close = _find_matching_delim(_part, _i, _limit, '[', ']')
            _prod  = _cap_his_path(_prod * _expr_his_paths(_part[_i + 1:_close]))
            _i     = _close + 1
        else:
            _i += 1
    return _prod


def _split_for_semicolons(hdr_tokens):
    _parts   = []
    _cur     = []
    _p_depth = 0
    _b_depth = 0
    for _tok in hdr_tokens:
        if _tok == '(':
            _p_depth += 1
            _cur.append(_tok)
        elif _tok == ')' and _p_depth > 0:
            _p_depth -= 1
            _cur.append(_tok)
        elif _tok == '{':
            _b_depth += 1
            _cur.append(_tok)
        elif _tok == '}' and _b_depth > 0:
            _b_depth -= 1
            _cur.append(_tok)
        elif _tok == ';' and _p_depth == 0 and _b_depth == 0:
            _parts.append(_cur)
            _cur = []
        else:
            _cur.append(_tok)
    _parts.append(_cur)
    return _parts


def _skip_case_label(tokens, idx, limit):
    # idx points right after 'case'
    _p_depth = 0
    _q_depth = 0
    while idx < limit:
        _tok = tokens[idx]
        if _tok == '(':
            _p_depth += 1
        elif _tok == ')' and _p_depth > 0:
            _p_depth -= 1
        elif _p_depth == 0:
            if _tok == '?':
                _q_depth += 1
            elif _tok == ':':
                if _q_depth > 0:
                    _q_depth -= 1
                else:
                    return idx + 1
            elif _tok in (';', '{', '}'):
                return idx
            else:
                # token inside case label constant expression
                pass
        else:
            # token inside parens
            pass
        idx += 1
    return idx


def _is_assign_token(tok):
    if not isinstance(tok, str) or not tok or tok[0] in ('"', "'"):
        return False
    _stripped = tok.lstrip(']')
    if _stripped in ASSIGN_OPERATORS:
        return True
    if _stripped.startswith(('=', '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '<<=', '>>=')):
        if not _stripped.startswith('=='):
            return True
        else:
            # equality operator
            pass
    else:
        # non-assignment token
        pass
    return False


def _is_inc_dec_token(tok):
    if not isinstance(tok, str) or not tok or tok[0] in ('"', "'"):
        return False
    if tok in INC_DEC_OPERATORS:
        return True
    if '++' in tok or '--' in tok:
        return True
    return False


def _scan_simple_expr(tokens, idx, limit):
    _expr       = []
    _saw_assign = False
    _saw_type_b = False
    _start      = idx
    while idx < limit:
        _tok = tokens[idx]
        if isinstance(_tok, tuple):
            break
        if _tok == ';':
            idx += 1
            break
        if _tok == '}':
            break
        if _tok in _STMT_BOUNDARY_KEYWORDS and idx > _start:
            break
        if _tok == '(':
            _close = _find_matching_delim(tokens, idx, limit, '(', ')')
            _expr.extend(tokens[idx:_close + 1])
            idx = _close + 1
        elif _tok == '{':
            _close = _find_matching_delim(tokens, idx, limit, '{', '}')
            _is_brace_init = (
                idx > _start
                and tokens[idx - 1] != ')'
                and ';' not in tokens[idx + 1:_close]
                and _close + 1 < limit
                and tokens[_close + 1] in (';', ',')
            )
            if _saw_assign or _saw_type_b or _is_brace_init:
                _expr.extend(tokens[idx:_close + 1])
                idx = _close + 1
            else:
                break
        else:
            if _is_assign_token(_tok):
                _saw_assign = True
            elif _tok in ('typedef', 'struct', 'union', 'enum'):
                _saw_type_b = True
            else:
                # regular token
                pass
            _expr.append(_tok)
            idx += 1
    return _expr, idx


def _parse_his_seq(tokens, start_idx=0, end_idx=None):
    _limit = len(tokens) if end_idx is None else end_idx
    _c     = 1
    _b     = 0
    _k     = 0
    _r     = 0
    _gotos = {}
    _idx   = start_idx

    while _idx < _limit:
        while (
            _idx + 1 < _limit
            and isinstance(tokens[_idx], str)
            and tokens[_idx] not in ('case', 'default')
            and tokens[_idx].isidentifier()
            and tokens[_idx + 1] == ':'
        ):
            _lbl = tokens[_idx]
            _idx += 2
            if _lbl in _gotos:
                _c = _cap_his_path(_c + _gotos.pop(_lbl))
            else:
                # label without pending forward goto
                pass

        if _idx >= _limit:
            break

        if tokens[_idx] == '}':
            _idx += 1
            continue

        (_sc, _sb, _sk, _sr, _sg), _next_idx = _parse_his_stmt(tokens, _idx, _limit)
        if _next_idx <= _idx:
            _next_idx = _idx + 1
        else:
            # parser advanced
            pass

        if _c > 0:
            _b = _cap_his_path(_b + _c * _sb)
            _k = _cap_his_path(_k + _c * _sk)
            _r = _cap_his_path(_r + _c * _sr)
            for _glbl, _gcnt in _sg.items():
                _gotos[_glbl] = _cap_his_path(_gotos.get(_glbl, 0) + _c * _gcnt)
            _c = _cap_his_path(_c * _sc)
        else:
            # unreachable code following unconditional jump/return
            pass

        _idx = _next_idx

    return (_c, _b, _k, _r, _gotos)


def _parse_his_stmt(tokens, idx, limit):
    _tok = tokens[idx]

    if isinstance(_tok, tuple) and _tok[0] == '#PP_BRANCHES':
        _best_res   = (1, 0, 0, 0, {})
        _best_total = 0
        for _br_slice in _tok[1]:
            _res   = _parse_his_seq(list(_br_slice))
            _total = _res[0] + _res[1] + _res[2] + _res[3] + sum(_res[4].values())
            if _total > _best_total:
                _best_total = _total
                _best_res   = _res
            else:
                # branch does not exceed max paths
                pass
        return _best_res, idx + 1

    if _tok == '{':
        _close_b = _find_matching_delim(tokens, idx, limit, '{', '}')
        _res     = _parse_his_seq(tokens, idx + 1, _close_b)
        return _res, _close_b + 1

    if _tok == ';':
        return (1, 0, 0, 0, {}), idx + 1

    if _tok == 'if':
        # iterative parsing of if / else if / else ladders to avoid deep recursion
        _branches = []
        while True:
            idx += 1
            _cond_p = 1
            if idx < limit and tokens[idx] == '(':
                _close_p = _find_matching_delim(tokens, idx, limit, '(', ')')
                _cond_p  = _expr_his_paths(tokens[idx + 1:_close_p])
                idx      = _close_p + 1
            else:
                # malformed if without condition parens
                pass

            if idx < limit:
                _then_res, idx = _parse_his_stmt(tokens, idx, limit)
            else:
                _then_res = (1, 0, 0, 0, {})

            _branches.append((_cond_p, _then_res))

            if idx < limit and tokens[idx] == 'else':
                idx += 1
                if idx < limit and tokens[idx] == 'if':
                    continue
                elif idx < limit:
                    _else_res, idx = _parse_his_stmt(tokens, idx, limit)
                    break
                else:
                    _else_res = (1, 0, 0, 0, {})
                    break
            else:
                _else_res = (1, 0, 0, 0, {})
                break

        _acc_c, _acc_b, _acc_k, _acc_r, _acc_g = _else_res
        for _cp, (_tc, _tb, _tk, _tr, _tg) in reversed(_branches):
            _merged_g = {}
            for _gl, _gv in _tg.items():
                _merged_g[_gl] = _cap_his_path(_merged_g.get(_gl, 0) + _cp * _gv)
            for _gl, _gv in _acc_g.items():
                _merged_g[_gl] = _cap_his_path(_merged_g.get(_gl, 0) + _cp * _gv)
            _acc_c = _cap_his_path(_cp * (_tc + _acc_c))
            _acc_b = _cap_his_path(_cp * (_tb + _acc_b))
            _acc_k = _cap_his_path(_cp * (_tk + _acc_k))
            _acc_r = _cap_his_path(_cp * (_tr + _acc_r))
            _acc_g = _merged_g
        return (_acc_c, _acc_b, _acc_k, _acc_r, _acc_g), idx

    if _tok == 'while':
        idx += 1
        _cond_p     = 1
        _cond_slice = []
        if idx < limit and tokens[idx] == '(':
            _close_p    = _find_matching_delim(tokens, idx, limit, '(', ')')
            _cond_slice = tokens[idx + 1:_close_p]
            _cond_p     = _expr_his_paths(_cond_slice)
            idx         = _close_p + 1
        else:
            # while without parens
            pass
        if idx < limit:
            (_bc, _bb, _bk, _br, _bg), idx = _parse_his_stmt(tokens, idx, limit)
        else:
            _bc, _bb, _bk, _br, _bg = 1, 0, 0, 0, {}
        _skip  = 0 if _is_always_true_cond(_cond_slice) else 1
        _out_c = _cap_his_path(_cond_p * (_skip + _bc + _bk + _bb))
        _out_r = _cap_his_path(_cond_p * _br)
        _out_g = {_gl: _cap_his_path(_cond_p * _gv) for _gl, _gv in _bg.items()}
        return (_out_c, 0, 0, _out_r, _out_g), idx

    if _tok == 'for':
        idx += 1
        _hdr_p    = 1
        _has_cond = True
        if idx < limit and tokens[idx] == '(':
            _close_p    = _find_matching_delim(tokens, idx, limit, '(', ')')
            _hdr_slice  = tokens[idx + 1:_close_p]
            _hdr_p      = _expr_his_paths(_hdr_slice)
            _semi_parts = _split_for_semicolons(_hdr_slice)
            if len(_semi_parts) == 3 and (len(_semi_parts[1]) == 0 or _is_always_true_cond(_semi_parts[1])):
                _has_cond = False
            else:
                # conditional for loop
                pass
            idx = _close_p + 1
        else:
            # for without parens
            pass
        if idx < limit:
            (_bc, _bb, _bk, _br, _bg), idx = _parse_his_stmt(tokens, idx, limit)
        else:
            _bc, _bb, _bk, _br, _bg = 1, 0, 0, 0, {}
        _skip  = 1 if _has_cond else 0
        _out_c = _cap_his_path(_hdr_p * (_skip + _bc + _bk + _bb))
        _out_r = _cap_his_path(_hdr_p * _br)
        _out_g = {_gl: _cap_his_path(_hdr_p * _gv) for _gl, _gv in _bg.items()}
        return (_out_c, 0, 0, _out_r, _out_g), idx

    if _tok == 'do':
        idx += 1
        if idx < limit:
            (_bc, _bb, _bk, _br, _bg), idx = _parse_his_stmt(tokens, idx, limit)
        else:
            _bc, _bb, _bk, _br, _bg = 1, 0, 0, 0, {}
        _cond_p     = 1
        _cond_slice = []
        if idx < limit and tokens[idx] == 'while':
            idx += 1
            if idx < limit and tokens[idx] == '(':
                _close_p    = _find_matching_delim(tokens, idx, limit, '(', ')')
                _cond_slice = tokens[idx + 1:_close_p]
                _cond_p     = _expr_his_paths(_cond_slice)
                idx         = _close_p + 1
            else:
                # do-while missing condition parens
                pass
            if idx < limit and tokens[idx] == ';':
                idx += 1
            else:
                # missing semicolon after do-while
                pass
        else:
            # malformed do without while
            pass
        _iter_end = _bc + _bk
        if _is_always_false_cond(_cond_slice):
            _out_c = _cap_his_path(_iter_end + _bb)
        elif _iter_end > 0:
            _out_c = _cap_his_path(_cond_p * (_iter_end + 1) + _bb)
        else:
            _out_c = _bb
        return (_out_c, 0, 0, _br, _bg), idx

    if _tok == 'switch':
        idx += 1
        _expr_p = 1
        if idx < limit and tokens[idx] == '(':
            _close_p = _find_matching_delim(tokens, idx, limit, '(', ')')
            _expr_p  = _expr_his_paths(tokens[idx + 1:_close_p])
            idx      = _close_p + 1
        else:
            # switch without parens
            pass

        if idx >= limit or tokens[idx] != '{':
            if idx < limit:
                (_sc, _sb, _sk, _sr, _sg), idx = _parse_his_stmt(tokens, idx, limit)
                return (
                    _cap_his_path(_expr_p * (_sc + _sb)),
                    0,
                    _cap_his_path(_expr_p * _sk),
                    _cap_his_path(_expr_p * _sr),
                    {_gl: _cap_his_path(_expr_p * _gv) for _gl, _gv in _sg.items()}
                ), idx
            return (_expr_p, 0, 0, 0, {}), idx

        _close_b = _find_matching_delim(tokens, idx, limit, '{', '}')
        _body    = tokens[idx + 1:_close_b]
        idx      = _close_b + 1

        _groups      = []
        _cur_tokens  = []
        _in_group    = False
        _has_default = False
        _b_depth     = 0
        _p_depth     = 0
        _j           = 0
        _body_len    = len(_body)

        while _j < _body_len:
            _btok = _body[_j]
            if _b_depth == 0 and _p_depth == 0 and _btok == 'case':
                if _in_group and len(_cur_tokens) > 0:
                    _groups.append(_cur_tokens)
                    _cur_tokens = []
                else:
                    # stacked empty case labels share the same handler block
                    pass
                _in_group = True
                _j        = _skip_case_label(_body, _j + 1, _body_len)
                continue
            elif _b_depth == 0 and _p_depth == 0 and _btok == 'default' and _j + 1 < _body_len and _body[_j + 1] == ':':
                _has_default = True
                if _in_group and len(_cur_tokens) > 0:
                    _groups.append(_cur_tokens)
                    _cur_tokens = []
                else:
                    # stacked default label shares the same handler block
                    pass
                _in_group = True
                _j += 2
                continue
            else:
                if _btok == '{':
                    _b_depth += 1
                elif _btok == '}' and _b_depth > 0:
                    _b_depth -= 1
                elif _btok == '(':
                    _p_depth += 1
                elif _btok == ')' and _p_depth > 0:
                    _p_depth -= 1
                else:
                    # regular token inside switch body
                    pass
                if _in_group:
                    _cur_tokens.append(_btok)
                else:
                    # declaration before first case label
                    pass
                _j += 1

        if _in_group:
            _groups.append(_cur_tokens)
        else:
            # switch with no case or default labels
            pass

        _sw_cont     = 0
        _sw_k        = 0
        _sw_r        = 0
        _sw_gotos    = {}
        _fallthrough = 0

        for _grp in _groups:
            _entering               = _cap_his_path(1 + _fallthrough)
            _gc, _gb, _gk, _gr, _gg = _parse_his_seq(_grp)
            _sw_cont                = _cap_his_path(_sw_cont + _entering * _gb)
            _sw_k                   = _cap_his_path(_sw_k + _entering * _gk)
            _sw_r                   = _cap_his_path(_sw_r + _entering * _gr)
            for _gl, _gv in _gg.items():
                _sw_gotos[_gl] = _cap_his_path(_sw_gotos.get(_gl, 0) + _entering * _gv)
            _fallthrough            = _cap_his_path(_entering * _gc)

        _sw_cont = _cap_his_path(_sw_cont + _fallthrough)
        if not _has_default:
            _sw_cont = _cap_his_path(_sw_cont + 1)
        else:
            # explicit default branch already accounted for
            pass

        return (
            _cap_his_path(_expr_p * _sw_cont),
            0,
            _cap_his_path(_expr_p * _sw_k),
            _cap_his_path(_expr_p * _sw_r),
            {_gl: _cap_his_path(_expr_p * _gv) for _gl, _gv in _sw_gotos.items()}
        ), idx

    if _tok == 'try':
        idx += 1
        if idx < limit:
            (_tc, _tb, _tk, _tr, _tg), idx = _parse_his_stmt(tokens, idx, limit)
        else:
            _tc, _tb, _tk, _tr, _tg = 1, 0, 0, 0, {}
        while idx < limit and tokens[idx] == 'catch':
            idx += 1
            if idx < limit and tokens[idx] == '(':
                _close_p = _find_matching_delim(tokens, idx, limit, '(', ')')
                idx      = _close_p + 1
            else:
                # catch without parens
                pass
            if idx < limit:
                (_cc, _cb, _ck, _cr, _cg), idx = _parse_his_stmt(tokens, idx, limit)
                _tc = _cap_his_path(_tc + _cc)
                _tb = _cap_his_path(_tb + _cb)
                _tk = _cap_his_path(_tk + _ck)
                _tr = _cap_his_path(_tr + _cr)
                for _gl, _gv in _cg.items():
                    _tg[_gl] = _cap_his_path(_tg.get(_gl, 0) + _gv)
            else:
                break
        return (_tc, _tb, _tk, _tr, _tg), idx

    if _tok in ('return', 'throw'):
        _expr, idx = _scan_simple_expr(tokens, idx + 1, limit)
        _ep        = _expr_his_paths(_expr)
        return (0, 0, 0, _ep, {}), idx

    if _tok == 'break':
        idx += 1
        if idx < limit and tokens[idx] == ';':
            idx += 1
        else:
            # missing semicolon
            pass
        return (0, 1, 0, 0, {}), idx

    if _tok == 'continue':
        idx += 1
        if idx < limit and tokens[idx] == ';':
            idx += 1
        else:
            # missing semicolon
            pass
        return (0, 0, 1, 0, {}), idx

    if _tok == 'goto':
        idx += 1
        _target = None
        if idx < limit and isinstance(tokens[idx], str) and tokens[idx].isidentifier():
            _target = tokens[idx]
        else:
            # computed goto
            pass
        _, idx = _scan_simple_expr(tokens, idx, limit)
        if _target is not None:
            return (0, 0, 0, 0, {_target: 1}), idx
        return (0, 0, 0, 1, {}), idx

    if _tok == 'else':
        idx += 1
        if idx < limit:
            return _parse_his_stmt(tokens, idx, limit)
        return (1, 0, 0, 0, {}), idx

    if _tok == 'case':
        idx = _skip_case_label(tokens, idx + 1, limit)
        return (1, 0, 0, 0, {}), idx

    if _tok == 'default':
        idx += 1
        if idx < limit and tokens[idx] == ':':
            idx += 1
        else:
            # stray default token
            pass
        return (1, 0, 0, 0, {}), idx

    _expr, idx = _scan_simple_expr(tokens, idx, limit)
    _ep        = _expr_his_paths(_expr)
    return (_ep, 0, 0, 0, {}), idx


def compute_his_path(func_tokens):
    if not func_tokens:
        return 1
    _norm_tokens           = _normalize_pp_blocks(func_tokens)
    _c, _b, _k, _r, _gotos = _parse_his_seq(_norm_tokens)
    _total                 = _cap_his_path(_c + _b + _k + _r + sum(_gotos.values()))
    return _total if _total >= 1 else 1


_C_TYPE_SPECIFIERS = {
    'void', 'char', 'short', 'int', 'long', 'float', 'double',
    'signed', 'unsigned', 'bool', '_Bool', 'boolean',
    'const', 'volatile', 'restrict', '__restrict', '__restrict__',
    'inline', '__inline', '__inline__', 'register', 'auto',
    'struct', 'union', 'enum', 'class', 'typename',
    'size_t', 'ssize_t', 'ptrdiff_t', 'intptr_t', 'uintptr_t',
    'int8_t', 'int16_t', 'int32_t', 'int64_t',
    'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
    'sint8', 'sint16', 'sint32', 'sint64',
    'uint8', 'uint16', 'uint32', 'uint64',
    'float32', 'float64', 'Std_ReturnType'
}

_RESERVED_DECL_KEYWORDS = {
    'void', 'char', 'short', 'int', 'long', 'float', 'double',
    'signed', 'unsigned', 'bool', '_Bool', '_Complex', '_Imaginary', '_Atomic',
    'wchar_t', 'char8_t', 'char16_t', 'char32_t',
    'const', 'volatile', 'restrict', '__restrict', '__restrict__',
    'inline', '__inline', '__inline__', '_Noreturn', 'register', 'auto', 'mutable',
    'struct', 'union', 'enum', 'class', 'typename',
    'constexpr', 'consteval', 'constinit', 'decltype', 'typeof', '__typeof__',
    '__attribute__', '__declspec', '_Alignas', 'alignas',
    'P2FUNC', 'CONSTP2FUNC'
}

_NON_EXEC_DECL_KEYWORDS = {
    'typedef', 'extern', 'static', 'using', 'namespace',
    'template', 'static_assert', '_Static_assert',
    'thread_local', '_Thread_local', '__thread'
}

_DECL_ATTR_KEYWORDS = {
    '__attribute__', '__declspec', '_Alignas', 'alignas',
    'sizeof', 'typeof', '__typeof__', 'alignof', '_Alignof', 'decltype',
    'P2FUNC', 'CONSTP2FUNC'
}


def _is_type_like_token(tok):
    if not isinstance(tok, str) or not tok:
        return False
    if tok in _C_TYPE_SPECIFIERS:
        return True
    if tok.endswith(('_t', '_type', 'Type', '_T')):
        return True
    return False


def _expand_expr_brackets(expr_tokens):
    _out = []
    for _tok in expr_tokens:
        if isinstance(_tok, str) and len(_tok) > 1 and _tok[0] == ']':
            _rest = _tok.lstrip(']')
            _cnt  = len(_tok) - len(_rest)
            for _ in range(_cnt):
                _out.append(']')
            if _rest:
                _out.append(_rest)
            else:
                # pure closing bracket sequence
                pass
        else:
            _out.append(_tok)
    return _out


def _is_plain_assign_token(tok):
    if not isinstance(tok, str) or not tok or tok[0] in ('"', "'"):
        return False
    _stripped = tok.lstrip(']')
    if _stripped.startswith('=') and not _stripped.startswith('=='):
        return True
    return False


def _is_prototype_param_list(param_tokens):
    if len(param_tokens) == 0:
        return True
    if param_tokens == ['void']:
        return True

    _parts   = []
    _cur     = []
    _p_depth = 0
    _a_depth = 0
    for _ptok in param_tokens:
        if _ptok == '(':
            _p_depth += 1
            _cur.append(_ptok)
        elif _ptok == ')' and _p_depth > 0:
            _p_depth -= 1
            _cur.append(_ptok)
        elif _ptok == '<' and _p_depth == 0:
            _a_depth += 1
            _cur.append(_ptok)
        elif _ptok == '>' and _p_depth == 0 and _a_depth > 0:
            _a_depth -= 1
            _cur.append(_ptok)
        elif _ptok == ',' and _p_depth == 0 and _a_depth == 0:
            _parts.append(_cur)
            _cur = []
        else:
            _cur.append(_ptok)
    _parts.append(_cur)

    _expr_ops = {
        '+', '-', '/', '%', '==', '!=', '<=', '>=',
        '&&', '||', '.', '->', '?'
    }
    for _part in _parts:
        if _part == ['...']:
            return True
        _id_cnt  = 0
        _p_d     = 0
        _a_d     = 0
        _s_d     = 0
        _has_op  = False
        _prev_tk = None
        for _tk in _part:
            if _tk == '(':
                _p_d += 1
            elif _tk == ')' and _p_d > 0:
                _p_d -= 1
            elif _tk == '[' and _p_d == 0:
                _s_d += 1
            elif isinstance(_tk, str) and _tk.startswith(']') and _p_d == 0 and _s_d > 0:
                _s_d -= 1
            elif _tk == '<' and _p_d == 0 and _s_d == 0:
                _a_d += 1
            elif _tk == '>' and _p_d == 0 and _s_d == 0 and _a_d > 0:
                _a_d -= 1
            elif _p_d == 0 and _s_d == 0 and _a_d == 0:
                if _is_type_like_token(_tk):
                    return True
                if _tk in _expr_ops:
                    _has_op = True
                elif isinstance(_tk, str) and _tk.isidentifier() and _prev_tk != '::':
                    _id_cnt += 1
                else:
                    # pointer/reference or scope token
                    pass
            else:
                # token nested inside brackets/parens/template
                pass
            _prev_tk = _tk
        if not _has_op and _id_cnt >= 2:
            return True
        if not _has_op and len(_part) >= 2 and isinstance(_part[0], str) and _part[0].isidentifier() and _part[-1] in ('*', '&'):
            return True
    return False


def _is_decl_lhs_tokens(lhs_tokens, has_eq=True):
    if not lhs_tokens:
        return False
    if lhs_tokens[0] in ('*', '**', '('):
        return False

    _has_decl_kw = False
    _has_brace   = False
    _qual_id_cnt = 0
    _chain_open  = False
    _just_saw_id = False
    _p_d         = 0
    _b_d         = 0
    _s_d         = 0
    _a_d         = 0

    for _idx_l, _ltok in enumerate(lhs_tokens):
        if _ltok == '(':
            _p_d += 1
        elif _ltok == ')' and _p_d > 0:
            _p_d -= 1
            if _p_d == 0 and _b_d == 0 and _s_d == 0 and _a_d == 0:
                _chain_open  = False
                _just_saw_id = False
            else:
                # nested paren close
                pass
        elif _ltok == '{' and _p_d == 0:
            _b_d += 1
        elif _ltok == '}' and _p_d == 0 and _b_d > 0:
            _b_d -= 1
            if _b_d == 0 and _s_d == 0 and _a_d == 0:
                _has_brace   = True
                _chain_open  = False
                _just_saw_id = False
            else:
                # nested brace close
                pass
        elif _p_d == 0 and _b_d == 0:
            if _ltok == '[':
                _s_d += 1
            elif _ltok == ']' and _s_d > 0:
                _s_d -= 1
            elif (
                _ltok == '<'
                and _s_d == 0
                and _just_saw_id
                and '>' in lhs_tokens[_idx_l + 1:]
            ):
                _a_d += 1
            elif _ltok == '>' and _s_d == 0 and _a_d > 0:
                _a_d -= 1
            elif _s_d == 0 and _a_d == 0:
                if _ltok in _RESERVED_DECL_KEYWORDS:
                    _has_decl_kw = True
                else:
                    # non-reserved token
                    pass

                if isinstance(_ltok, str) and _ltok.isidentifier():
                    if not _chain_open:
                        _qual_id_cnt += 1
                    else:
                        # continuation of scope-qualified identifier chain
                        pass
                    _chain_open  = False
                    _just_saw_id = True
                elif _ltok == '::':
                    if _just_saw_id:
                        _chain_open = True
                    else:
                        # leading global scope ::
                        pass
                    _just_saw_id = False
                elif _ltok in ('*', '**') or (has_eq and _ltok in ('&', '&&', '...')):
                    _chain_open  = False
                    _just_saw_id = False
                else:
                    return False
            else:
                # token inside array subscript or template arguments
                pass
        else:
            # token inside parens or braces
            pass

    if _has_decl_kw:
        if (
            not has_eq
            and len(lhs_tokens) >= 3
            and lhs_tokens[0] in (
                'void', 'char', 'short', 'int', 'long', 'float', 'double',
                'bool', '_Bool', 'wchar_t', 'char8_t', 'char16_t', 'char32_t'
            )
            and lhs_tokens[1] == '('
            and _find_matching_delim(lhs_tokens, 1, len(lhs_tokens), '(', ')') == len(lhs_tokens) - 1
        ):
            # C++ functional cast expression e.g. void(foo())
            return False
        return True

    if _has_brace:
        return True

    if _qual_id_cnt >= 2:
        return True

    if has_eq and _qual_id_cnt == 1 and '(' in lhs_tokens:
        _first_p = lhs_tokens.index('(')
        _close_p = _find_matching_delim(lhs_tokens, _first_p, len(lhs_tokens), '(', ')')
        _inner_p = lhs_tokens[_first_p + 1:_close_p]
        if len(_inner_p) >= 2 and _inner_p[0] in ('*', '**', '^'):
            if _close_p + 1 < len(lhs_tokens) and lhs_tokens[_close_p + 1] == '(':
                _close_p2 = _find_matching_delim(lhs_tokens, _close_p + 1, len(lhs_tokens), '(', ')')
                if _is_prototype_param_list(lhs_tokens[_close_p + 2:_close_p2]):
                    return True
            elif _close_p + 1 < len(lhs_tokens) and lhs_tokens[_close_p + 1] == '[' and _is_type_like_token(lhs_tokens[0]):
                return True
            else:
                # not a function-pointer or array-pointer declarator
                pass
        else:
            # regular function call returning lvalue e.g. get_ref(i) = 1
            pass

    return False


def _simple_expr_stmt_count(expr_tokens):
    if not expr_tokens:
        return 0

    _tokens     = _expand_expr_brackets(expr_tokens)
    _top_tokens = []
    _segments   = []
    _cur_seg    = []
    _seg_assign = False
    _prev_id    = False
    _p_depth    = 0
    _b_depth    = 0
    _s_depth    = 0
    _a_depth    = 0

    for _idx_t, _tok in enumerate(_tokens):
        if _tok == '(':
            _p_depth += 1
            _cur_seg.append(_tok)
        elif _tok == ')' and _p_depth > 0:
            _p_depth -= 1
            _cur_seg.append(_tok)
            if _p_depth == 0 and _b_depth == 0:
                _prev_id = False
            else:
                # nested paren close
                pass
        elif _tok == '{':
            _b_depth += 1
            _cur_seg.append(_tok)
        elif _tok == '}' and _b_depth > 0:
            _b_depth -= 1
            _cur_seg.append(_tok)
            if _p_depth == 0 and _b_depth == 0:
                _top_tokens.append('{}')
                _prev_id = False
            else:
                # nested brace close
                pass
        elif _p_depth == 0 and _b_depth == 0:
            _top_tokens.append(_tok)
            if _tok == '[':
                _s_depth += 1
                _cur_seg.append(_tok)
            elif _tok == ']' and _s_depth > 0:
                _s_depth -= 1
                _cur_seg.append(_tok)
            elif (
                _tok == '<'
                and _s_depth == 0
                and not _seg_assign
                and _prev_id
                and '>' in _tokens[_idx_t + 1:]
            ):
                _a_depth += 1
                _cur_seg.append(_tok)
            elif _tok == '>' and _s_depth == 0 and _a_depth > 0:
                _a_depth -= 1
                _cur_seg.append(_tok)
            elif _tok == ',' and _s_depth == 0 and _a_depth == 0:
                _segments.append(_cur_seg)
                _cur_seg    = []
                _seg_assign = False
                _prev_id    = False
            else:
                if _s_depth == 0 and _a_depth == 0:
                    if _is_assign_token(_tok):
                        _seg_assign = True
                    else:
                        # non-assignment token
                        pass
                    _prev_id = isinstance(_tok, str) and _tok.isidentifier()
                else:
                    # token inside subscript or template arguments
                    pass
                _cur_seg.append(_tok)
        else:
            _cur_seg.append(_tok)

    _segments.append(_cur_seg)

    if any(_tok in _NON_EXEC_DECL_KEYWORDS for _tok in _top_tokens):
        return 0

    _first = _tokens[0]
    if _first in ('asm', '__asm', '__asm__', 'delete', 'co_await', 'co_yield'):
        return 1

    # Exclude all variable/type declarations (ISO C99 6.8: declarations are not statements)
    _seg0      = _segments[0]
    _eq_idx    = None
    _has_comp  = False
    _p_d       = 0
    _b_d       = 0
    _s_d       = 0
    _a_d       = 0
    _prev_s_id = False
    for _i0, _t0 in enumerate(_seg0):
        if _t0 == '(':
            _p_d += 1
        elif _t0 == ')' and _p_d > 0:
            _p_d -= 1
            if _p_d == 0 and _b_d == 0:
                _prev_s_id = False
            else:
                pass
        elif _t0 == '{':
            _b_d += 1
        elif _t0 == '}' and _b_d > 0:
            _b_d -= 1
            if _p_d == 0 and _b_d == 0:
                _prev_s_id = False
            else:
                pass
        elif _p_d == 0 and _b_d == 0:
            if _t0 == '[':
                _s_d += 1
            elif _t0 == ']' and _s_d > 0:
                _s_d -= 1
            elif (
                _t0 == '<'
                and _s_d == 0
                and _prev_s_id
                and '>' in _seg0[_i0 + 1:]
            ):
                _a_d += 1
            elif _t0 == '>' and _s_d == 0 and _a_d > 0:
                _a_d -= 1
            elif _s_d == 0 and _a_d == 0:
                if _is_assign_token(_t0):
                    if _is_plain_assign_token(_t0):
                        _eq_idx = _i0
                    else:
                        _has_comp = True
                    break
                _prev_s_id = isinstance(_t0, str) and _t0.isidentifier()
            else:
                # subscript or template token
                pass
        else:
            # nested paren or brace token
            pass

    if not _has_comp:
        if _eq_idx is not None:
            if _is_decl_lhs_tokens(_seg0[:_eq_idx], True):
                return 0
        else:
            if _is_decl_lhs_tokens(_seg0, False):
                return 0
    else:
        # compound assignment is always an executable expression statement
        pass

    # Count comma-separated top-level segments that perform executable assignment
    _assign_segs = 0
    for _seg in _segments:
        _p_d = 0
        _b_d = 0
        _s_d = 0
        for _st in _seg:
            if _st == '(':
                _p_d += 1
            elif _st == ')' and _p_d > 0:
                _p_d -= 1
            elif _st == '{':
                _b_d += 1
            elif _st == '}' and _b_d > 0:
                _b_d -= 1
            elif _p_d == 0 and _b_d == 0:
                if _st == '[':
                    _s_d += 1
                elif _st == ']' and _s_d > 0:
                    _s_d -= 1
                elif _s_d == 0 and _is_assign_token(_st):
                    _assign_segs += 1
                    break
                else:
                    pass
            else:
                pass

    if _assign_segs > 0:
        return _assign_segs

    if any(_is_inc_dec_token(_tok) for _tok in _tokens):
        return 1

    if _first == '(':
        return 1

    if '?' in _top_tokens:
        return 1

    if '(' not in _tokens or _tokens[-1] != ')':
        return 0

    if any(_tok in _DECL_ATTR_KEYWORDS for _tok in _top_tokens):
        return 0

    _first_p = _tokens.index('(')
    _close_p = _find_matching_delim(_tokens, _first_p, len(_tokens), '(', ')')
    _inner_p = _tokens[_first_p + 1:_close_p]

    # Uninitialized function pointer declaration: Type (*fp)(params)
    if _close_p + 1 < len(_tokens) and _tokens[_close_p + 1] == '(':
        if len(_inner_p) >= 2 and _inner_p[0] in ('*', '**', '^'):
            return 0
        else:
            # chained call expression e.g. get_fn(id)(arg)
            pass

    # Macro-prefixed prototype declaration: FUNC(void, CODE) helper(void)
    if _close_p + 1 < len(_tokens):
        _after_p = _tokens[_close_p + 1]
        if isinstance(_after_p, str) and _after_p.isidentifier():
            return 0
        else:
            # member access or binary operator following call
            pass

    _prefix = _tokens[:_first_p]
    if '.' in _prefix or any(isinstance(_t, str) and _t.startswith('->') for _t in _prefix):
        return 1
    if any(_t in ('&&', '||') for _t in _prefix):
        return 1

    _qual_id_cnt = 0
    _a_depth     = 0
    _s_depth     = 0
    _prev_ptok   = None
    for _ptok in _prefix:
        if _ptok == '[':
            _s_depth += 1
        elif _ptok == ']' and _s_depth > 0:
            _s_depth -= 1
        elif _ptok == '<' and _s_depth == 0:
            _a_depth += 1
        elif _ptok == '>' and _s_depth == 0 and _a_depth > 0:
            _a_depth -= 1
        elif _s_depth == 0 and _a_depth == 0:
            if isinstance(_ptok, str) and _ptok.isidentifier() and _prev_ptok != '::':
                _qual_id_cnt += 1
            else:
                # operator or scope separator
                pass
        else:
            # template or subscript token
            pass
        _prev_ptok = _ptok

    if _qual_id_cnt >= 2:
        return 0

    return 1


def _count_his_stmt_seq(tokens, start_idx=0, end_idx=None):
    _limit = len(tokens) if end_idx is None else end_idx
    _total = 0
    _idx   = start_idx

    while _idx < _limit:
        if tokens[_idx] == '}':
            _idx += 1
            continue

        _stmt_cnt, _next_idx = _count_his_stmt_node(tokens, _idx, _limit)
        if _next_idx <= _idx:
            _next_idx = _idx + 1
        else:
            # parser advanced
            pass
        _total += _stmt_cnt
        _idx    = _next_idx

    return _total


def _count_his_stmt_node(tokens, idx, limit):
    while idx < limit:
        _ltok = tokens[idx]
        if _ltok == 'case':
            idx = _skip_case_label(tokens, idx + 1, limit)
            continue
        elif _ltok == 'default' and idx + 1 < limit and tokens[idx + 1] == ':':
            idx += 2
            continue
        elif (
            idx + 1 < limit
            and isinstance(_ltok, str)
            and _ltok not in _STMT_BOUNDARY_KEYWORDS
            and _ltok.isidentifier()
            and tokens[idx + 1] == ':'
        ):
            idx += 2
            continue
        else:
            break

    if idx >= limit or tokens[idx] == '}':
        return 0, idx

    _tok = tokens[idx]

    if isinstance(_tok, tuple) and _tok[0] == '#PP_BRANCHES':
        _best_cnt = 0
        for _br_slice in _tok[1]:
            _cnt = _count_his_stmt_seq(list(_br_slice))
            if _cnt > _best_cnt:
                _best_cnt = _cnt
            else:
                # branch does not exceed max statements
                pass
        return _best_cnt, idx + 1

    if _tok == '{':
        _close_b = _find_matching_delim(tokens, idx, limit, '{', '}')
        _cnt     = _count_his_stmt_seq(tokens, idx + 1, _close_b)
        return _cnt, _close_b + 1

    if _tok == ';':
        return 0, idx + 1

    if _tok == 'if':
        # iterative parsing of if / else if / else ladders to avoid deep recursion
        _total = 0
        while True:
            _total += 1
            idx    += 1
            if idx < limit and tokens[idx] == '(':
                _close_p = _find_matching_delim(tokens, idx, limit, '(', ')')
                idx      = _close_p + 1
            else:
                # malformed if without condition parens
                pass

            if idx < limit:
                _then_cnt, idx = _count_his_stmt_node(tokens, idx, limit)
                _total        += _then_cnt
            else:
                # trailing if
                pass

            if idx < limit and tokens[idx] == 'else':
                idx += 1
                if idx < limit and tokens[idx] == 'if':
                    continue
                elif idx < limit:
                    _else_cnt, idx = _count_his_stmt_node(tokens, idx, limit)
                    _total        += _else_cnt
                    break
                else:
                    break
            else:
                break
        return _total, idx

    if _tok in ('while', 'for', 'switch'):
        _total = 1
        idx   += 1
        if idx < limit and tokens[idx] == '(':
            _close_p = _find_matching_delim(tokens, idx, limit, '(', ')')
            idx      = _close_p + 1
        else:
            # control keyword without parens
            pass
        if idx < limit:
            _body_cnt, idx = _count_his_stmt_node(tokens, idx, limit)
            _total        += _body_cnt
        else:
            # trailing control keyword
            pass
        return _total, idx

    if _tok == 'do':
        _total = 1
        idx   += 1
        if idx < limit:
            _body_cnt, idx = _count_his_stmt_node(tokens, idx, limit)
            _total        += _body_cnt
        else:
            # trailing do
            pass
        if idx < limit and tokens[idx] == 'while':
            idx += 1
            if idx < limit and tokens[idx] == '(':
                _close_p = _find_matching_delim(tokens, idx, limit, '(', ')')
                idx      = _close_p + 1
            else:
                # do-while missing parens
                pass
            if idx < limit and tokens[idx] == ';':
                idx += 1
            else:
                # missing semicolon after do-while
                pass
        else:
            # malformed do without while
            pass
        return _total, idx

    if _tok == 'try':
        _total = 1
        idx   += 1
        if idx < limit:
            _try_cnt, idx = _count_his_stmt_node(tokens, idx, limit)
            _total       += _try_cnt
        else:
            # trailing try
            pass
        while idx < limit and tokens[idx] == 'catch':
            idx += 1
            if idx < limit and tokens[idx] == '(':
                _close_p = _find_matching_delim(tokens, idx, limit, '(', ')')
                idx      = _close_p + 1
            else:
                # catch without parens
                pass
            if idx < limit:
                _catch_cnt, idx = _count_his_stmt_node(tokens, idx, limit)
                _total         += _catch_cnt
            else:
                break
        return _total, idx

    if _tok in ('return', 'throw', 'goto'):
        _, idx = _scan_simple_expr(tokens, idx + 1, limit)
        return 1, idx

    if _tok in ('break', 'continue'):
        idx += 1
        if idx < limit and tokens[idx] == ';':
            idx += 1
        else:
            # missing semicolon
            pass
        return 1, idx

    if _tok == 'else':
        idx += 1
        if idx < limit:
            return _count_his_stmt_node(tokens, idx, limit)
        return 0, idx

    _expr, idx = _scan_simple_expr(tokens, idx, limit)
    _stmt_cnt  = _simple_expr_stmt_count(_expr)
    return _stmt_cnt, idx


def compute_his_stmt(func_tokens):
    if not func_tokens:
        return 0
    _norm_tokens = _normalize_pp_blocks(func_tokens)
    _total       = _count_his_stmt_seq(_norm_tokens)
    return _total if _total >= 0 else 0


_C_VOCF_TOK_PATTERN = re.compile(
    r'<<=|>>=|->\*|\.\.\.|==|!=|<=|>=|&&|\|\||\+\+|--|<<|>>|'
    r'\+=|-=|\*=|/=|%=|&=|\|=|\^=|->|\.\*|::|##|\w+|[^\s]'
)


def _flatten_pp_for_vocf(norm_tokens):
    _out = []
    for _item in norm_tokens:
        if isinstance(_item, tuple) and len(_item) == 2 and _item[0] == '#PP_BRANCHES':
            _best_branch = []
            for _br in _item[1]:
                _flat_br = _flatten_pp_for_vocf(_br)
                if len(_flat_br) > len(_best_branch):
                    _best_branch = _flat_br
            _out.extend(_best_branch)
        elif isinstance(_item, str) and not _item.startswith('#'):
            _out.append(_item)
    return _out


def _has_unclosed_float_exponent(num_tok):
    if not num_tok:
        return False
    _low = num_tok.lower()
    if _low.startswith('0x'):
        return len(num_tok) > 2 and num_tok[-1] in ('p', 'P')
    return (num_tok[0].isdigit() or (num_tok[0] == '.' and len(num_tok) > 1 and num_tok[1].isdigit())) and num_tok[-1] in ('e', 'E')


def _lex_c_tokens_for_vocf(raw_tokens):
    _split = []
    for _tok in raw_tokens:
        if not _tok:
            continue
        if _tok[0] in ('"', "'"):
            _split.append(_tok)
        elif _tok.startswith('/*') or _tok.startswith('//') or _tok.startswith('#'):
            continue
        else:
            _split.extend(_C_VOCF_TOK_PATTERN.findall(_tok))

    _merged = []
    _n      = len(_split)
    _i      = 0
    while _i < _n:
        _t = _split[_i]
        # String/character encoding prefix: L"...", u"...", U"...", u8"..."
        if _t in ('L', 'u', 'U', 'u8') and (_i + 1) < _n and _split[_i + 1][0] in ('"', "'"):
            _merged.append(_t + _split[_i + 1])
            _i += 2
            continue
        # Variadic ellipsis '...'
        if _t == '.' and (_i + 2) < _n and _split[_i + 1] == '.' and _split[_i + 2] == '.':
            _merged.append('...')
            _i += 3
            continue
        # Right-shift operators '>>=' and '>>' split by hfcca's '|>' rule
        if _t == '>' and (_i + 1) < _n:
            if _split[_i + 1] == '>=':
                _merged.append('>>=')
                _i += 2
                continue
            if _split[_i + 1] == '>':
                _merged.append('>>')
                _i += 2
                continue
        # Floating-point literals: digits + '.' (+ frac) or '.' + digits
        if _t[0].isdigit() and (_i + 1) < _n and _split[_i + 1] == '.':
            if (_i + 2) < _n and (_split[_i + 2][0].isalnum() or _split[_i + 2][0] == '_'):
                _num = _t + '.' + _split[_i + 2]
                _i  += 3
            else:
                _num = _t + '.'
                _i  += 2
            if _has_unclosed_float_exponent(_num) and (_i + 1) < _n and _split[_i] in ('+', '-') and _split[_i + 1][0].isdigit():
                _num = _num + _split[_i] + _split[_i + 1]
                _i  += 2
            _merged.append(_num)
            continue
        if _t == '.' and (_i + 1) < _n and _split[_i + 1][0].isdigit():
            _num = '.' + _split[_i + 1]
            _i  += 2
            if _has_unclosed_float_exponent(_num) and (_i + 1) < _n and _split[_i] in ('+', '-') and _split[_i + 1][0].isdigit():
                _num = _num + _split[_i] + _split[_i + 1]
                _i  += 2
            _merged.append(_num)
            continue
        # Integer mantissa with scientific exponent, e.g. 1e-5 or 0x1p+2
        if _has_unclosed_float_exponent(_t) and (_i + 2) < _n and _split[_i + 1] in ('+', '-') and _split[_i + 2][0].isdigit():
            _merged.append(_t + _split[_i + 1] + _split[_i + 2])
            _i += 3
            continue
        _merged.append(_t)
        _i += 1
    return _merged


def _strip_compiler_attributes(tokens):
    _out = []
    _n   = len(tokens)
    _i   = 0
    while _i < _n:
        if tokens[_i] in ('__attribute__', '__attribute', '__declspec') and (_i + 1) < _n and tokens[_i + 1] == '(':
            _depth = 1
            _j     = _i + 2
            while _j < _n and _depth > 0:
                if tokens[_j] == '(':
                    _depth += 1
                elif tokens[_j] == ')':
                    _depth -= 1
                _j += 1
            if _depth == 0:
                _i = _j
                continue
        _out.append(tokens[_i])
        _i += 1
    return _out


_AUTOSAR_VOCF_MACROS_2 = frozenset(['FUNC', 'CONST', 'VAR'])
_AUTOSAR_VOCF_MACROS_3 = frozenset([
    'FUNC_P2CONST', 'FUNC_P2VAR',
    'P2VAR', 'P2CONST', 'CONSTP2VAR', 'CONSTP2CONST',
    'P2FUNC', 'CONSTP2FUNC',
])


def _expand_autosar_macros(tokens):
    _out = []
    _n   = len(tokens)
    _i   = 0
    while _i < _n:
        _tok = tokens[_i]
        if (_tok in _AUTOSAR_VOCF_MACROS_2 or _tok in _AUTOSAR_VOCF_MACROS_3) and (_i + 1) < _n and tokens[_i + 1] == '(':
            _depth = 1
            _j     = _i + 2
            _args  = [[]]
            while _j < _n and _depth > 0:
                _cur = tokens[_j]
                if _cur == '(':
                    _depth += 1
                    _args[-1].append(_cur)
                elif _cur == ')':
                    _depth -= 1
                    if _depth > 0:
                        _args[-1].append(_cur)
                elif _cur == ',' and _depth == 1:
                    _args.append([])
                else:
                    _args[-1].append(_cur)
                _j += 1
            if _depth == 0:
                _exp_args = [_expand_autosar_macros(_a) for _a in _args]
                if _tok in _AUTOSAR_VOCF_MACROS_2 and len(_exp_args) == 2:
                    if _tok == 'CONST':
                        _out.extend(['const'] + _exp_args[0])
                    else:
                        _out.extend(_exp_args[0])
                    _i = _j
                    continue
                if _tok in _AUTOSAR_VOCF_MACROS_3 and len(_exp_args) == 3:
                    if _tok in ('FUNC_P2CONST', 'P2CONST'):
                        _out.extend(['const'] + _exp_args[0] + ['*'])
                    elif _tok in ('FUNC_P2VAR', 'P2VAR'):
                        _out.extend(_exp_args[0] + ['*'])
                    elif _tok == 'CONSTP2VAR':
                        _out.extend(_exp_args[0] + ['*', 'const'])
                    elif _tok == 'CONSTP2CONST':
                        _out.extend(['const'] + _exp_args[0] + ['*', 'const'])
                    elif _tok == 'P2FUNC':
                        _out.extend(_exp_args[0] + ['(', '*'] + _exp_args[2] + [')'])
                    elif _tok == 'CONSTP2FUNC':
                        _out.extend(_exp_args[0] + ['(', '*', 'const'] + _exp_args[2] + [')'])
                    _i = _j
                    continue
        if _tok == 'STATIC':
            _out.append('static')
            _i += 1
            continue
        if _tok == 'INLINE':
            _out.append('inline')
            _i += 1
            continue
        if _tok == 'LOCAL_INLINE':
            _out.extend(['static', 'inline'])
            _i += 1
            continue
        _out.append(_tok)
        _i += 1
    return _out


def compute_his_vocf(header_tokens, body_tokens):
    ''' Compute true HIS VOCF (Sprachumfang / Language Scope):
        VOCF = (N1 + N2) / (n1 + n2)
        where N1 + N2 is total C/C++ lexical tokens in the function definition
        and n1 + n2 is the count of distinct lexical tokens in the function definition.
    '''
    _flat_body = _flatten_pp_for_vocf(_normalize_pp_blocks(body_tokens or []))
    _raw_all   = list(header_tokens or []) + ['{'] + _flat_body + ['}']
    _lexed     = _lex_c_tokens_for_vocf(_raw_all)
    _clean     = _expand_autosar_macros(_strip_compiler_attributes(_lexed))
    if not _clean:
        return 0.0
    _unique_cnt = len(set(_clean))
    if _unique_cnt <= 0:
        return 0.0
    return round(float(len(_clean)) / float(_unique_cnt), 2)


_C_COMMENT_OR_LIT_PATTERN = re.compile(
    r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')|/\*[\s\S]*?\*/|//[^\n]*'
)
_C_STATIC_LEX_PATTERN = re.compile(
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|'
    r'<<=|>>=|->\*|\.\.\.|==|!=|<=|>=|&&|\|\||\+\+|--|<<|>>|'
    r'\+=|-=|\*=|/=|%=|&=|\|=|\^=|->|\.\*|::|##|\w+|[^\s]'
)
_STATIC_DECL_PURE_QUALS = frozenset([
    'static', 'STATIC', 'extern', 'auto', 'register',
    'const', 'volatile', 'restrict', '__restrict', '__restrict__',
    'inline', 'INLINE', 'LOCAL_INLINE', '__inline', '__inline__', '_Inline',
    'constexpr', 'constinit', 'consteval',
    'thread_local', '_Thread_local', 'mutable',
    '__far', '__near',
])


def _find_matching_open_delim(tokens, close_idx, open_tok, close_tok):
    _depth = 0
    _idx   = close_idx
    while _idx >= 0:
        _tok = tokens[_idx]
        if _tok == close_tok:
            _depth += 1
        elif _tok == open_tok:
            _depth -= 1
            if _depth <= 0:
                return _idx
        _idx -= 1
    return 0


def _strip_static_decl_attrs(tokens):
    _out = []
    _n   = len(tokens)
    _i   = 0
    while _i < _n:
        _tok = tokens[_i]
        if (
            isinstance(_tok, str)
            and _tok in ('__attribute__', '__attribute', '__declspec', '__asm__', '__asm', 'asm')
            and (_i + 1) < _n
            and tokens[_i + 1] == '('
        ):
            _depth = 1
            _j     = _i + 2
            while _j < _n and _depth > 0:
                if tokens[_j] == '(':
                    _depth += 1
                elif tokens[_j] == ')':
                    _depth -= 1
                _j += 1
            if _depth == 0:
                _i = _j
                continue
        _out.append(_tok)
        _i += 1
    return _out


def _normalize_static_decl_segment(tokens):
    return _expand_autosar_macros(_strip_static_decl_attrs(tokens))


def _tokenize_and_structure_for_static_decls(source_code):
    _spliced   = re.sub(r'\\\r?\n', ' ', source_code)
    _clean_src = _C_COMMENT_OR_LIT_PATTERN.sub(
        lambda _m: _m.group(1) if _m.group(1) is not None else ' ',
        _spliced,
    )
    _stack = [[(None, [])]]
    for _line in _clean_src.splitlines():
        _stripped = _line.lstrip()
        if _stripped.startswith('#'):
            _rest  = _stripped[1:].lstrip()
            _m_dir = re.match(r'^([A-Za-z_]\w*)(.*)', _rest)
            if not _m_dir:
                continue
            _dir_name = _m_dir.group(1)
            _dir_tail = _m_dir.group(2).strip()
            if _dir_name == 'if':
                _stack.append([(_C_STATIC_LEX_PATTERN.findall(_dir_tail), [])])
            elif _dir_name in ('ifdef', 'ifndef'):
                _stack.append([([_dir_name] + _C_STATIC_LEX_PATTERN.findall(_dir_tail), [])])
            elif _dir_name == 'elif':
                if len(_stack) > 1:
                    _stack[-1].append((_C_STATIC_LEX_PATTERN.findall(_dir_tail), []))
            elif _dir_name == 'else':
                if len(_stack) > 1:
                    _stack[-1].append((None, []))
            elif _dir_name == 'endif':
                if len(_stack) > 1:
                    _clauses          = _stack.pop()
                    _live             = []
                    _saw_else_or_true = False
                    for _cond, _body in _clauses:
                        if _saw_else_or_true:
                            continue
                        if _cond is None:
                            _live.append(_body)
                            _saw_else_or_true = True
                        elif _is_always_false_cond(_cond):
                            continue
                        elif _is_always_true_cond(_cond):
                            _live.append(_body)
                            _saw_else_or_true = True
                        else:
                            _live.append(_body)
                    if not _live:
                        continue
                    _norm_live = [tuple(_normalize_static_decl_segment(_br)) for _br in _live]
                    if all(_is_balanced_slice(_br) for _br in _norm_live):
                        if not _saw_else_or_true:
                            _norm_live.append(())
                        _stack[-1][-1][1].append(('#PP_BRANCHES', tuple(_norm_live)))
                    else:
                        _stack[-1][-1][1].extend(_norm_live[0])
            else:
                # #define, #include, #pragma, #undef, #error, #warning, #line ignored
                pass
        else:
            _stack[-1][-1][1].extend(_C_STATIC_LEX_PATTERN.findall(_line))

    while len(_stack) > 1:
        _unclosed = _stack.pop()
        for _cond, _body in _unclosed:
            if _cond is None or not _is_always_false_cond(_cond):
                _stack[-1][-1][1].extend(_body)
                break

    return _normalize_static_decl_segment(_stack[0][0][1])


def _extract_grouped_declarator_name(group_tokens):
    _cur = list(group_tokens)
    while _cur:
        _i = 0
        while _i < len(_cur):
            _t = _cur[_i]
            if _t in ('*', '&', '&&') or _t in _STATIC_DECL_PURE_QUALS:
                _i += 1
            elif (_i + 1) < len(_cur) and _cur[_i + 1] == '::':
                _i += 2
            else:
                break
        _cur = _cur[_i:]
        if not _cur:
            return None
        if _cur[0] == '(':
            _c   = _find_matching_delim(_cur, 0, len(_cur), '(', ')')
            _cur = _cur[1:_c]
            continue
        _ident = _cur[0]
        if _ident == 'operator':
            _op_toks = []
            for _ot in _cur[1:]:
                if _ot == '(':
                    break
                _op_toks.append(str(_ot))
            return 'operator' + ''.join(_op_toks)
        if not isinstance(_ident, str) or not (_ident[0].isalpha() or _ident[0] == '_'):
            return None
        return _ident
    return None


def _extract_var_name_from_declarator(lhs_tokens):
    _cur = list(lhs_tokens)
    while _cur and _cur[-1] == ']':
        _open_s = _find_matching_open_delim(_cur, len(_cur) - 1, '[', ']')
        _cur    = _cur[:_open_s]
    if _cur and _cur[-1] == ')':
        _open_p   = _find_matching_open_delim(_cur, len(_cur) - 1, '(', ')')
        _before_p = _cur[:_open_p]
        if _before_p and _before_p[-1] == ')':
            _g_open = _find_matching_open_delim(_before_p, len(_before_p) - 1, '(', ')')
            _fp_nm  = _extract_grouped_declarator_name(_before_p[_g_open + 1:-1])
            if _fp_nm:
                return _fp_nm
        elif not _before_p or all(_t in _STATIC_DECL_PURE_QUALS or _t in ('int', 'char', 'short', 'long', 'float', 'double', 'signed', 'unsigned', 'bool', '_Bool', 'void') for _t in _before_p):
            _cur = _cur[_open_p + 1:-1]
        else:
            _cur = _before_p
    for _idx_c, _tok in enumerate(_cur):
        if _tok == 'operator':
            return 'operator' + ''.join(str(_x) for _x in _cur[_idx_c + 1:])
    for _tok in reversed(_cur):
        if isinstance(_tok, str) and (_tok[0].isalpha() or _tok[0] == '_') and _tok not in _STATIC_DECL_PURE_QUALS and _tok != '__AGGREGATE_BODY__':
            return _tok
    return None


def _extract_declarator_var_name(item_tokens, is_first_item):
    _item = list(item_tokens)
    if is_first_item and '__AGGREGATE_BODY__' in _item:
        _last_agg = len(_item) - 1 - _item[::-1].index('__AGGREGATE_BODY__')
        _item     = _item[_last_agg + 1:]
        _has_type = True
    else:
        _has_type = not is_first_item

    if not _item:
        return None

    # Check for top-level '=' initializer
    _p_depth = 0
    _b_depth = 0
    _s_depth = 0
    _eq_idx  = -1
    for _i, _tok in enumerate(_item):
        if _tok == '(':
            _p_depth += 1
        elif _tok == ')' and _p_depth > 0:
            _p_depth -= 1
        elif _tok == '{':
            _b_depth += 1
        elif _tok == '}' and _b_depth > 0:
            _b_depth -= 1
        elif _tok == '[':
            _s_depth += 1
        elif _tok == ']' and _s_depth > 0:
            _s_depth -= 1
        elif _tok == '=' and _p_depth == 0 and _b_depth == 0 and _s_depth == 0:
            if _i == 0 or _item[_i - 1] != 'operator':
                _eq_idx = _i
                break

    if _eq_idx != -1:
        _lhs = _item[:_eq_idx]
        _rhs = _item[_eq_idx + 1:]
        if _rhs == ['delete']:
            return None
        return _extract_var_name_from_declarator(_lhs)

    # Strip C++ trailing return type: static auto f(int) -> int
    _p_depth = 0
    _b_depth = 0
    _s_depth = 0
    _saw_rp  = False
    for _i, _tok in enumerate(_item):
        if _tok == '(':
            _p_depth += 1
        elif _tok == ')' and _p_depth > 0:
            _p_depth -= 1
            if _p_depth == 0:
                _saw_rp = True
        elif _tok == '{':
            _b_depth += 1
        elif _tok == '}' and _b_depth > 0:
            _b_depth -= 1
        elif _tok == '[':
            _s_depth += 1
        elif _tok == ']' and _s_depth > 0:
            _s_depth -= 1
        elif _tok == '->' and _saw_rp and _p_depth == 0 and _b_depth == 0 and _s_depth == 0:
            _item = _item[:_i]
            break

    # Strip trailing C++ post-parameter function qualifiers: const, volatile, noexcept(...), override, final, throw(...)
    while len(_item) >= 2:
        if _item[-1] == ')':
            _op = _find_matching_open_delim(_item, len(_item) - 1, '(', ')')
            if _op >= 1 and _item[_op - 1] in ('noexcept', 'throw'):
                _item = _item[:_op - 1]
                continue
        if _item[-1] in ('const', 'volatile', 'noexcept', 'override', 'final') and _item[-2] == ')':
            _item = _item[:-1]
            continue
        break

    if not _item:
        return None

    _last = _item[-1]
    if _last == ']':
        return _extract_var_name_from_declarator(_item)

    if _last == '}':
        _open_b = _find_matching_open_delim(_item, len(_item) - 1, '{', '}')
        _lhs    = _item[:_open_b]
        if _lhs:
            return _extract_var_name_from_declarator(_lhs)
        return None

    if _last == ')':
        _open_p   = _find_matching_open_delim(_item, len(_item) - 1, '(', ')')
        _before_p = _item[:_open_p]
        if not _before_p:
            return None
        if _before_p[-1] == ')':
            _g_open = _find_matching_open_delim(_before_p, len(_before_p) - 1, '(', ')')
            if _g_open == 0 or _before_p[_g_open - 1] not in ('decltype', 'typeof', '__typeof__', 'alignas', '_Alignas'):
                return _extract_grouped_declarator_name(_before_p[_g_open + 1:-1])
            return None
        return _extract_var_name_from_declarator(_before_p)

    if not isinstance(_last, str) or not (_last[0].isalpha() or _last[0] == '_') or _last in _STATIC_DECL_PURE_QUALS:
        return None

    # Plain / pointer variable declarator without '=' or '()' (e.g. static uint8 x; or static struct Tag s;)
    _units = []
    _i     = 0
    _n     = len(_item)
    while _i < _n:
        _t = _item[_i]
        if _t in _STATIC_DECL_PURE_QUALS:
            _i += 1
            continue
        if _t in ('struct', 'union', 'enum', 'class'):
            if (_i + 1) < _n and isinstance(_item[_i + 1], str) and (_item[_i + 1][0].isalpha() or _item[_i + 1][0] == '_'):
                _units.append(_t + ' ' + _item[_i + 1])
                _i += 2
                continue
            _units.append(_t)
            _i += 1
            continue
        if _t == '(' and _units:
            _cp = _find_matching_delim(_item, _i, _n, '(', ')')
            _units[-1] = _units[-1] + '(...)'
            _i = _cp + 1
            continue
        if _t == '<' and _units and _units[-1] != 'operator':
            _ca = _find_matching_delim(_item, _i, _n, '<', '>')
            _units[-1] = _units[-1] + '<...>'
            _i = _ca + 1
            continue
        if _t == '::' and _units and (_i + 1) < _n:
            _units[-1] = _units[-1] + '::' + str(_item[_i + 1])
            _i += 2
            continue
        _units.append(_t)
        _i += 1

    if not _units:
        return None
    if _has_type:
        return _last
    if len(_units) >= 2:
        return _last
    return None


def _count_static_vars_in_decl(decl_tokens, scope_seen):
    _items       = []
    _cur         = []
    _p_depth     = 0
    _b_depth     = 0
    _s_depth     = 0
    _angle_depth = 0
    _in_init     = False

    for _i, _tok in enumerate(decl_tokens):
        if _tok == '(':
            _p_depth += 1
            _cur.append(_tok)
        elif _tok == ')' and _p_depth > 0:
            _p_depth -= 1
            _cur.append(_tok)
        elif _tok == '{':
            _b_depth += 1
            _cur.append(_tok)
        elif _tok == '}' and _b_depth > 0:
            _b_depth -= 1
            _cur.append(_tok)
        elif _tok == '[':
            _s_depth += 1
            _cur.append(_tok)
        elif _tok == ']' and _s_depth > 0:
            _s_depth -= 1
            _cur.append(_tok)
        elif not _in_init and _p_depth == 0 and _b_depth == 0 and _s_depth == 0 and _tok == '<' and (_i == 0 or decl_tokens[_i - 1] != 'operator'):
            _angle_depth += 1
            _cur.append(_tok)
        elif not _in_init and _p_depth == 0 and _b_depth == 0 and _s_depth == 0 and _tok == '>' and _angle_depth > 0:
            _angle_depth -= 1
            _cur.append(_tok)
        elif _tok == '=' and _p_depth == 0 and _b_depth == 0 and _s_depth == 0 and (_i == 0 or decl_tokens[_i - 1] != 'operator'):
            _in_init     = True
            _angle_depth = 0
            _cur.append(_tok)
        elif _tok == ',' and _p_depth == 0 and _b_depth == 0 and _s_depth == 0 and _angle_depth == 0:
            _items.append(_cur)
            _cur     = []
            _in_init = False
        else:
            _cur.append(_tok)
    if _cur:
        _items.append(_cur)

    _cnt = 0
    for _idx_item, _item in enumerate(_items):
        _vname = _extract_declarator_var_name(_item, _idx_item == 0)
        if _vname is not None and _vname not in scope_seen:
            scope_seen.add(_vname)
            _cnt += 1
    return _cnt


def _count_static_vars_in_seq(tokens, scope_seen=None):
    if scope_seen is None:
        scope_seen = set()
    _limit = len(tokens)
    _idx   = 0
    _total = 0

    while _idx < _limit:
        _tok = tokens[_idx]

        if isinstance(_tok, tuple) and len(_tok) == 2 and _tok[0] == '#PP_BRANCHES':
            _best_cnt  = -1
            _best_seen = set(scope_seen)
            for _br in _tok[1]:
                _br_seen = set(scope_seen)
                _br_cnt  = _count_static_vars_in_seq(_br, _br_seen)
                if _br_cnt > _best_cnt:
                    _best_cnt  = _br_cnt
                    _best_seen = _br_seen
            if _best_cnt > 0:
                _total += _best_cnt
            scope_seen.clear()
            scope_seen.update(_best_seen)
            _idx += 1
            continue

        if _tok in (';', '}'):
            _idx += 1
            continue

        if _tok == '{':
            _close_b = _find_matching_delim(tokens, _idx, _limit, '{', '}')
            _total  += _count_static_vars_in_seq(tokens[_idx + 1:_close_b], set())
            _idx     = _close_b + 1
            continue

        if _tok in ('if', 'while', 'for', 'switch', 'catch'):
            _idx += 1
            if _idx < _limit and tokens[_idx] == '(':
                _idx = _find_matching_delim(tokens, _idx, _limit, '(', ')') + 1
            continue

        if _tok in ('else', 'do', 'try'):
            _idx += 1
            continue

        if _tok in ('return', 'goto', 'break', 'continue', 'throw'):
            while _idx < _limit and tokens[_idx] != ';':
                if tokens[_idx] == '(':
                    _idx = _find_matching_delim(tokens, _idx, _limit, '(', ')') + 1
                elif tokens[_idx] == '{':
                    _idx = _find_matching_delim(tokens, _idx, _limit, '{', '}') + 1
                else:
                    _idx += 1
            if _idx < _limit and tokens[_idx] == ';':
                _idx += 1
            continue

        if _tok == 'case':
            _idx = _skip_case_label(tokens, _idx + 1, _limit)
            continue

        if _tok == 'default' and (_idx + 1) < _limit and tokens[_idx + 1] == ':':
            _idx += 2
            continue

        if (
            isinstance(_tok, str)
            and _tok not in ('static', 'STATIC')
            and (_tok[0].isalpha() or _tok[0] == '_')
            and (_idx + 1) < _limit
            and tokens[_idx + 1] == ':'
        ):
            _idx += 2
            continue

        _decl_toks       = []
        _has_static_spec = False
        _has_typedef     = False
        _saw_eq          = False
        _saw_top_comma   = False
        _saw_agg_kw      = None
        _paren_after_agg = False
        _ended_with_body = False

        while _idx < _limit:
            _t = tokens[_idx]
            if isinstance(_t, tuple):
                if not _decl_toks:
                    break
                if len(_t) == 2 and _t[0] == '#PP_BRANCHES' and len(_t[1]) > 0:
                    tokens = list(tokens[:_idx]) + list(_t[1][0]) + list(tokens[_idx + 1:])
                    _limit = len(tokens)
                    continue
                _idx += 1
                continue
            if _t == ';':
                _idx += 1
                break
            if _t == '}':
                break
            if _t == '(':
                _close_p = _find_matching_delim(tokens, _idx, _limit, '(', ')')
                if _saw_agg_kw and not _saw_eq:
                    _paren_after_agg = True
                _decl_toks.extend(tokens[_idx:_close_p + 1])
                _idx = _close_p + 1
                continue
            if _t == '[':
                _close_s = _find_matching_delim(tokens, _idx, _limit, '[', ']')
                _decl_toks.extend(tokens[_idx:_close_s + 1])
                _idx = _close_s + 1
                continue
            if _t == '{':
                _close_b = _find_matching_delim(tokens, _idx, _limit, '{', '}')
                _after_b = tokens[_close_b + 1] if (_close_b + 1) < _limit else None
                if _saw_eq:
                    _decl_toks.extend(tokens[_idx:_close_b + 1])
                    _idx = _close_b + 1
                    continue
                if _decl_toks and (
                    _decl_toks[0] == 'namespace'
                    or (_decl_toks[0] == 'extern' and len(_decl_toks) >= 2 and isinstance(_decl_toks[1], str) and _decl_toks[1].startswith('"'))
                ):
                    _inner_seen      = scope_seen if _decl_toks[0] == 'extern' else set()
                    _total          += _count_static_vars_in_seq(tokens[_idx + 1:_close_b], _inner_seen)
                    _idx             = _close_b + 1
                    _ended_with_body = True
                    break
                if _saw_agg_kw and not _paren_after_agg:
                    if _saw_agg_kw != 'enum':
                        _total += _count_static_vars_in_seq(tokens[_idx + 1:_close_b], set())
                    _decl_toks.append('__AGGREGATE_BODY__')
                    _saw_agg_kw      = None
                    _paren_after_agg = False
                    _idx             = _close_b + 1
                    continue
                _post_fn_quals = {'const', 'volatile', 'noexcept', 'override', 'final'}
                if (
                    _decl_toks
                    and _decl_toks[-1] != ')'
                    and _decl_toks[-1] not in _post_fn_quals
                    and '->' not in _decl_toks
                    and _after_b in (';', ',')
                ):
                    _decl_toks.extend(tokens[_idx:_close_b + 1])
                    _idx = _close_b + 1
                    continue
                if _has_static_spec and not _has_typedef and _decl_toks:
                    _total += _count_static_vars_in_decl(_decl_toks, scope_seen)
                _total          += _count_static_vars_in_seq(tokens[_idx + 1:_close_b], set())
                _idx             = _close_b + 1
                _ended_with_body = True
                break

            if not _saw_eq and not _saw_top_comma:
                if _t in ('static', 'STATIC'):
                    _has_static_spec = True
                elif _t == 'typedef':
                    _has_typedef = True
                elif _t in ('struct', 'union', 'enum', 'class'):
                    if _saw_agg_kw != 'enum':
                        _saw_agg_kw = _t
                    _paren_after_agg = False
            if _t == '=' and (not _decl_toks or _decl_toks[-1] != 'operator'):
                _saw_eq = True
            elif _t == ',':
                _saw_top_comma = True
                _saw_eq        = False
            _decl_toks.append(_t)
            _idx += 1

        if not _ended_with_body and _has_static_spec and not _has_typedef and _decl_toks:
            _total += _count_static_vars_in_decl(_decl_toks, scope_seen)

    return _total


def compute_static_var_declarations(source_code):
    ''' Count unique static declarations (variables and functions) in a C/C++ translation unit,
        deduplicating forward prototypes and tentative declarations against definitions in the same scope,
        skipping inactive #if 0 blocks, and taking the max across mutually exclusive #if/#else branches.
    '''
    if not source_code or ('static' not in source_code and 'STATIC' not in source_code and 'LOCAL_INLINE' not in source_code):
        return 0
    _tokens = _tokenize_and_structure_for_static_decls(source_code)
    return _count_static_vars_in_seq(_tokens, set())


def _count_non_empty_comment_lines(text):
    _cnt = 0
    for _line in text.split('\n'):
        _cleaned = _line.replace('*', '').replace('/', '').replace(' ', '').replace('\t', '').replace('\r', '')
        if len(_cleaned) > 0:
            _cnt += 1
        else:
            # empty comment delimiter line
            pass
    return _cnt


def _is_file_doc_comment(text, at_top_of_file=False):
    _lower = text.lower()
    if '@file' in _lower or '\\file' in _lower:
        return True
    if at_top_of_file and 'copyright' in _lower:
        return True
    return False


def _is_doxygen_func_comment(text):
    _stripped = text.lstrip()
    if _stripped.startswith('/**') or _stripped.startswith('/*!') or _stripped.startswith('///') or _stripped.startswith('//!'):
        if not _is_file_doc_comment(_stripped, False):
            return True
    return False


"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
class UniversalAnalyzer(list):
    """
        UniversalCode is the code that is unrelated to any programming
        languages. The code could be:
        START_NEW_FUNCTION
            ADD_TO_FUNCTION_NAME
            ADD_TO_LONG_FUNCTION_NAME
                PARAMETER
            CONDITION
            TOKEN
        END_OF_FUNCTION

        A TokenTranslator will generate UniversalCode.
    """
    def __init__(self):
        self.current_function       = None
        self.newline                = True
        self.nloc                   = 0
        self.comment_count          = 0
        self.nesting_depth          = 0
        self.prev_token             = None
        self.prev_prev_token        = None
        self.pending_exit           = False
        self.has_unconditional_exit = False
        self.exit_depth             = 0
        self.if_stack               = []
        self.awaiting_if_body       = False
        self.expecting_else_for     = None
        self.func_declared_vars     = {}
        self.stmt_tokens            = []
        self.in_for                 = False
        self.for_paren              = 0
        self.jump_active            = False
        self.func_body_tokens       = []
        self.decl_prefix_tokens     = []
        self.func_header_tokens     = []
        self.in_pp_line             = False
        self.in_function_body       = False
        self.in_decl_prefix         = False
        self.pending_comment_lines  = 0
        self.pending_comment_end    = -1
        self.pending_is_doxygen     = False
        self.sig_comment_lines      = 0
        self.last_finished_function = None
        self.last_func_end_line     = -1
        self.last_global_term_line  = -1
        self.at_top_of_file         = True

    def analyze(self, parsed_code, filename):
        fileInfo = FileInformation(filename)
        for fun in self._functions(parsed_code):
            fileInfo.append(fun)
        if self.in_function_body and self.current_function is not None:
            self.comment_count += self.current_function.comment_count
            self.in_function_body = False
        self.FLUSH_PENDING_COMMENTS(None)
        fileInfo.summarize(self.nloc, self.comment_count)
        return fileInfo

    def _check_decl_prefix_start(self, line):
        self.at_top_of_file = False
        if not self.in_decl_prefix:
            if self.pending_comment_lines > 0:
                _gap = line - self.pending_comment_end - 1
                if _gap <= 0 or (_gap == 1 and self.pending_is_doxygen):
                    # keep pending header comment for candidate function
                    pass
                else:
                    self.comment_count += self.pending_comment_lines
                    self.pending_comment_lines = 0
                    self.pending_comment_end   = -1
                    self.pending_is_doxygen    = False
            self.in_decl_prefix = True
        else:
            # already inside declaration prefix
            pass

    def BEGIN_DECL_PREFIX(self, line):
        self._check_decl_prefix_start(line)

    def DECL_PREFIX_TOKENS(self, tokens):
        if tokens:
            self.decl_prefix_tokens.extend(tokens)

    def FLUSH_PENDING_COMMENTS(self, _unused=None):
        if self.pending_comment_lines > 0 or self.sig_comment_lines > 0:
            self.comment_count += self.pending_comment_lines + self.sig_comment_lines
            self.pending_comment_lines = 0
            self.sig_comment_lines     = 0
            self.pending_comment_end   = -1
            self.pending_is_doxygen    = False
        self.in_decl_prefix     = False
        self.decl_prefix_tokens = []

    def FLUSH_GLOBAL_TERM(self, line):
        self.at_top_of_file = False
        self.FLUSH_PENDING_COMMENTS(None)
        if line is not None:
            self.last_global_term_line = line

    def GLOBAL_PP_DIRECTIVE(self, line):
        self.at_top_of_file = False
        if not self.in_decl_prefix and self.pending_comment_lines > 0 and line is not None:
            if line <= self.pending_comment_end + 1:
                self.pending_comment_end = line

    def FILE_COMMENT(self, text):
        self.comment_count += _count_non_empty_comment_lines(text)

    def ENTER_FUNCTION_BODY(self, _unused=None):
        self.at_top_of_file        = False
        self.in_function_body      = True
        self.in_decl_prefix        = False
        self.func_header_tokens    = list(self.decl_prefix_tokens)
        self.decl_prefix_tokens    = []
        _header_comments           = self.pending_comment_lines + self.sig_comment_lines
        self.pending_comment_lines = 0
        self.sig_comment_lines     = 0
        self.pending_comment_end   = -1
        self.pending_is_doxygen    = False
        if self.current_function is not None and _header_comments > 0:
            self.current_function.add_comment(_header_comments)

    def RESET_AND_START_NEW_FUNCTION(self, name_and_line):
        self.FLUSH_PENDING_COMMENTS(None)
        self.START_NEW_FUNCTION(name_and_line)

    def AFTER_DEC_START_NEW_FUNCTION(self, name_and_line):
        if name_and_line[0] != ')' and not any(_t in ('__attribute__', '__attribute', '__declspec') for _t in self.decl_prefix_tokens):
            self.decl_prefix_tokens = []
        self.START_NEW_FUNCTION(name_and_line)

    def START_NEW_FUNCTION(self, name_and_line):
        self._check_decl_prefix_start(name_and_line[1])
        if name_and_line[0]:
            self.decl_prefix_tokens.append(name_and_line[0])
        self.current_function       = FunctionInfo(*name_and_line)
        self.nesting_depth          = 0
        self.prev_token             = None
        self.prev_prev_token        = None
        self.pending_exit           = False
        self.has_unconditional_exit = False
        self.exit_depth             = 0
        self.if_stack               = []
        self.awaiting_if_body       = False
        self.expecting_else_for     = None
        self.func_declared_vars     = {}
        self.stmt_tokens            = []
        self.in_for                 = False
        self.for_paren              = 0
        self.jump_active            = False
        self.func_body_tokens       = []
        self.func_header_tokens     = []
        self.in_pp_line             = False

    def CONDITION(self, token):
        self.TOKEN(token)
        self.current_function.add_condition()

    def TOKEN(self, text):
        if text.startswith('#'):
            self.in_pp_line = True
            if text in ('#if', '#elif', '#else', '#endif'):
                self.func_body_tokens.append(text)
            else:
                # other preprocessor directive ignored for CFG path analysis
                pass
        elif not self.in_pp_line:
            self.func_body_tokens.append(text)
        else:
            # token on non-conditional preprocessor directive line
            pass

        if self.newline:
            self.current_function.add_non_comment_line()
            self.newline = False
        else:
            # continue on line
            pass

        if text == 'for':
            self.in_for    = True
            self.for_paren = 0
        elif self.in_for:
            if text == '(':
                self.for_paren += 1
            elif text == ')':
                self.for_paren -= 1
                if self.for_paren <= 0:
                    self.in_for = False
                else:
                    # still inside for header parens
                    pass
            else:
                # token inside for header
                pass
        else:
            # not in for header
            pass

        if text in CONTROL_FLOW_KEYWORDS:
            self.current_function.add_sloc()
            self.current_function.add_eloc()
            self.stmt_tokens = []
            self.jump_active = False
        elif text in JUMP_FLOW_KEYWORDS:
            self.current_function.add_sloc()
            self.current_function.add_eloc()
            self.jump_active = True
            self.stmt_tokens = []
        elif text in ('case', 'default') or (text.endswith(':') and not text.startswith('::')):
            self.current_function.add_sloc()
            self.current_function.add_eloc()
            self.stmt_tokens = []
            self.jump_active = False
        elif text == ';':
            if self.in_for:
                # semicolon inside for loop header is not a separate statement
                pass
            elif self.jump_active:
                self.jump_active = False
                self.stmt_tokens = []
            else:
                if len(self.stmt_tokens) > 0:
                    self.current_function.add_sloc()
                    _has_assign  = any(_tok in ASSIGN_OPERATORS for _tok in self.stmt_tokens)
                    _has_inc_dec = any(_tok in INC_DEC_OPERATORS for _tok in self.stmt_tokens)
                    _has_call    = False
                    for _tok_idx in range(1, len(self.stmt_tokens)):
                        if self.stmt_tokens[_tok_idx] == '(' and self.stmt_tokens[_tok_idx - 1].isidentifier():
                            if self.stmt_tokens[_tok_idx - 1] not in {'sizeof', 'typeof', 'alignof', 'decltype'}:
                                _has_call = True
                                break
                            else:
                                # sizeof or typeof operator
                                pass
                        else:
                            # not call pattern
                            pass
                    if _has_assign or _has_inc_dec or _has_call:
                        self.current_function.add_eloc()
                    else:
                        # declaration without initialization
                        pass
                    self.stmt_tokens = []
                else:
                    # empty statement
                    pass
        elif text in ('{', '}'):
            self.stmt_tokens = []
        else:
            self.stmt_tokens.append(text)

        if self.expecting_else_for is not None:
            if text == 'else':
                self.expecting_else_for = None
            else:
                self.current_function.add_if_without_else()
                self.expecting_else_for = None
        else:
            # not expecting else
            pass

        if text == 'if':
            if self.prev_token == 'else':
                self.awaiting_if_body = True
            else:
                self.awaiting_if_body = True
                self.if_stack.append({'depth': self.nesting_depth, 'has_brace': False})
        else:
            # other token
            pass

        if text == '{':
            self.nesting_depth += 1
            self.current_function.update_nesting_depth(self.nesting_depth)
            if self.awaiting_if_body and len(self.if_stack) > 0:
                self.if_stack[-1]['has_brace'] = True
                self.if_stack[-1]['brace_depth'] = self.nesting_depth
                self.awaiting_if_body = False
            else:
                # standard block
                pass
        elif text == '}':
            if self.nesting_depth > 0:
                self.nesting_depth -= 1
            else:
                # nesting depth already at base
                pass
            if (self.has_unconditional_exit or self.pending_exit) and self.nesting_depth < self.exit_depth:
                self.has_unconditional_exit = False
                self.pending_exit = False
            else:
                # retain exit state
                pass
            if len(self.if_stack) > 0 and self.if_stack[-1].get('has_brace', False) and self.if_stack[-1].get('brace_depth', -1) == self.nesting_depth + 1:
                self.expecting_else_for = self.if_stack.pop()
            else:
                # not closing if block
                pass
        elif text == 'return':
            self.current_function.add_return()
            self.pending_exit = True
            self.exit_depth = self.nesting_depth
        elif text == 'goto':
            self.current_function.add_goto()
            self.pending_exit = True
            self.exit_depth = self.nesting_depth
        elif text in ('break', 'continue'):
            self.pending_exit = True
            self.exit_depth = self.nesting_depth
        elif text in (';', 'if', 'for', 'while', 'switch', 'do'):
            if text == ';':
                if self.awaiting_if_body and len(self.if_stack) > 0 and not self.if_stack[-1].get('has_brace', False):
                    self.expecting_else_for = self.if_stack.pop()
                    self.awaiting_if_body = False
                else:
                    # normal statement
                    pass
                if self.has_unconditional_exit:
                    self.current_function.add_dead_code()
                elif self.pending_exit:
                    self.pending_exit = False
                    self.has_unconditional_exit = True
                else:
                    # normal statement termination
                    pass
            else:
                if self.has_unconditional_exit:
                    self.current_function.add_dead_code()
                else:
                    # normal control statement
                    pass
        elif text in ('case', 'default') or text.endswith(':'):
            self.has_unconditional_exit = False
            self.pending_exit = False
        else:
            # regular token
            pass

        if text == '(' and self.prev_token is not None:
            _c_keywords = {
                'if', 'for', 'while', 'switch', 'return', 'sizeof',
                'catch', 'case', 'typeof', 'alignof', 'decltype'
            }
            if self.prev_token not in _c_keywords and self.prev_token.isidentifier():
                self.current_function.add_called_function(self.prev_token)
            else:
                # keyword or non-identifier
                pass
        else:
            # not a call parenthesis
            pass

        _type_names = {
            'int', 'char', 'short', 'long', 'float', 'double', 'unsigned', 'signed',
            'void', 'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t', 'int8_t', 'int16_t',
            'int32_t', 'int64_t', 'boolean', 'bool', 'size_t', 'Std_ReturnType'
        }
        if self.prev_token in _type_names or (self.prev_token is not None and (self.prev_token.endswith('_t') or self.prev_token.endswith('_type') or self.prev_token.endswith('Type'))):
            if text.isidentifier() and text not in _type_names and text not in ('const', 'volatile', 'static', 'STATIC', 'auto', 'register'):
                if self.prev_prev_token != 'extern' and self.nesting_depth >= 0:
                    self.func_declared_vars[text] = 0
                else:
                    # external or file scope
                    pass
            else:
                # non-identifier or keyword
                pass
        else:
            # not after type
            pass

        if text in self.func_declared_vars:
            self.func_declared_vars[text] += 1
        else:
            # not in declared vars
            pass

        self.prev_prev_token = self.prev_token
        self.prev_token = text
        self.current_function.add_token()

    def COMMENT(self, payload):
        if isinstance(payload, tuple):
            _text, _start_line, _end_line = payload
        else:
            _text       = payload
            _start_line = -1
            _end_line   = -1

        _cnt = _count_non_empty_comment_lines(_text)
        if self.in_function_body and self.current_function is not None:
            if _cnt > 0:
                self.current_function.add_comment(_cnt)
        elif _start_line < 0:
            if _cnt > 0:
                if self.current_function is not None:
                    self.current_function.add_comment(_cnt)
                else:
                    self.comment_count += _cnt
        elif self.last_finished_function is not None and _start_line == self.last_func_end_line:
            if _cnt > 0:
                self.last_finished_function.add_comment(_cnt)
                self.last_finished_function.update_cdrp()
        elif not self.in_decl_prefix and _start_line == self.last_global_term_line:
            self.comment_count += _cnt
        elif self.in_decl_prefix:
            self.sig_comment_lines += _cnt
        else:
            if _is_file_doc_comment(_text, self.at_top_of_file):
                self.FLUSH_PENDING_COMMENTS(None)
                self.comment_count += _cnt
            else:
                self.at_top_of_file = False
                if self.pending_comment_lines > 0 and _start_line > self.pending_comment_end + 1:
                    self.comment_count += self.pending_comment_lines
                    self.pending_comment_lines = 0
                    self.pending_is_doxygen    = False
                self.pending_comment_lines += _cnt
                self.pending_comment_end    = _end_line
                if _is_doxygen_func_comment(_text):
                    self.pending_is_doxygen = True

    def NEW_LINE(self, token):
        self.nloc += 1
        self.newline = True
        self.in_pp_line = False

    def ADD_TO_LONG_FUNCTION_NAME(self, app):
        if self.current_function is not None:
            self.current_function.add_to_long_name(app)
        if not self.in_function_body:
            _tok = app.strip()
            if _tok:
                self.decl_prefix_tokens.append(_tok)

    def ADD_TO_FUNCTION_NAME(self, app):
        if self.current_function is not None:
            self.current_function.add_to_function_name(app)
        if not self.in_function_body:
            _tok = app.strip()
            if _tok.startswith('::'):
                self.decl_prefix_tokens.append('::')
                _rest = _tok[2:].strip()
                if _rest:
                    self.decl_prefix_tokens.append(_rest)
            elif _tok:
                self.decl_prefix_tokens.append(_tok)

    def PARAMETER(self, token):
        self.current_function.add_parameter(token)
        self.ADD_TO_LONG_FUNCTION_NAME(" " + token)

    END_OF_FUNCTION = 1

    def _functions(self, parsed_code):
        for code, text in parsed_code:
            if code is UniversalAnalyzer.END_OF_FUNCTION:
                _finished_fun         = self.current_function
                self.in_function_body = False
                self.in_decl_prefix   = False
                if _finished_fun is not None:
                    if self.expecting_else_for is not None:
                        _finished_fun.add_if_without_else()
                        self.expecting_else_for = None
                    else:
                        # no pending if check
                        pass
                    while len(self.if_stack) > 0:
                        self.if_stack.pop()
                        _finished_fun.add_if_without_else()
                    for _vname, _vcnt in self.func_declared_vars.items():
                        if _vcnt <= 1:
                            _finished_fun.add_unused_variable()
                        else:
                            # variable referenced in function body
                            pass
                    _finished_fun.set_path_count(compute_his_path(self.func_body_tokens))
                    _finished_fun.set_statement_count(compute_his_stmt(self.func_body_tokens))
                    _finished_fun.set_vocf(compute_his_vocf(self.func_header_tokens, self.func_body_tokens))
                    _finished_fun.finalize_metrics()
                    self.last_finished_function = _finished_fun
                    self.last_func_end_line     = text if isinstance(text, int) else -1
                else:
                    # no function object
                    pass
                self.decl_prefix_tokens = []
                self.func_header_tokens = []
                self.current_function   = None
                yield _finished_fun
            else:
                code(self, text)

class TokenTranslatorBase:

    def __init__(self):
        self._state             = self._GLOBAL
        self._current_line      = 0
        self._in_global_pp_line = False

    def get_current_line(self):
        return self._current_line

    def _make_comment(self, token):
        _end_line   = self._current_line
        _start_line = _end_line - token.count('\n')
        return (UniversalAnalyzer.COMMENT, (token, _start_line, _end_line))

    def getFunctions(self, tokens):
        for token, self._current_line in tokens:
            fun = self._read_token(token)
            if fun: yield fun

    def _read_token(self, token):
        if token.isspace():
            self._in_global_pp_line = False
            return UniversalAnalyzer.NEW_LINE, None
        elif getattr(self, '_IMP', None) is not None and self._state != self._IMP:
            if token == '#define' or token in ('#include', '#undef', '#error', '#warning', '#line', '#import'):
                self._in_global_pp_line = True
                self._state = self._GLOBAL
                return UniversalAnalyzer.FLUSH_GLOBAL_TERM, self._current_line
            elif token.startswith('#'):
                self._in_global_pp_line = True
                return UniversalAnalyzer.GLOBAL_PP_DIRECTIVE, self._current_line
            elif self._in_global_pp_line:
                if token.startswith('/*') or token.startswith('//'):
                    return UniversalAnalyzer.FILE_COMMENT, token
                else:
                    return None
            else:
                return self._state(token)
        else:
            if token == '#define':
                return None
            return self._state(token)
    def remove_hash_if(self):
        self.conditions.discard("#if")


class CTokenTranslator(TokenTranslatorBase):

    def __init__(self):
        TokenTranslatorBase.__init__(self)
        # classic McCabe cyclomatic complexity: M = 1 + decision points (excludes &&, ||, #if)
        self.conditions            = set(['if', 'for', 'while', 'case', '?', 'catch'])
        self.bracket_level         = 0
        self.br_count              = 0
        self.last_preprocessor     = None
        self._macro_bracket_level  = 0
        self._macro_name           = ""
        self._macro_arg0_tokens    = []
        self._macro_arg_idx        = 0
        self._dec_end_line         = -1

    def _is_condition(self, token):
        _matched = token in self.conditions
        return _matched

    def _is_func_macro(self, token):
        _is_macro = False
        if token in ('FUNC', 'FUNC_P2CONST', 'FUNC_P2VAR'):
            _is_macro = True
        elif token.endswith('_FUNC') or token.startswith('FUNC_'):
            _is_macro = True
        else:
            # token is not a recognized function macro
            pass
        return _is_macro

    def _GLOBAL(self, token):
        _result = None
        if self._is_func_macro(token):
            self._macro_name          = token
            self._macro_arg0_tokens   = []
            self._macro_arg_idx       = 0
            self._state               = self._FUNC_MACRO_WAIT_OPEN
            _result                   = (UniversalAnalyzer.BEGIN_DECL_PREFIX, self._current_line)
        elif token == '(':
            if self.bracket_level == 0:
                pass
            self.bracket_level += 1
            self._state = self._DEC
            _result = (UniversalAnalyzer.ADD_TO_LONG_FUNCTION_NAME, token)
        elif token == '::':
            self._state = self._NAMESPACE
        elif token.startswith('/*') or token.startswith('//'):
            _result = self._make_comment(token)
        elif token in (';', '=', '{', '}', ':'):
            _result = (UniversalAnalyzer.FLUSH_GLOBAL_TERM, self._current_line)
        else:
            if token == 'operator':
                self._state = self._OPERATOR
            else:
                # normal token outside operator
                pass
            _result = (UniversalAnalyzer.START_NEW_FUNCTION, (token, self._current_line))
        return _result

    def _FUNC_MACRO_WAIT_OPEN(self, token):
        _result = None
        if token == '(':
            self._macro_bracket_level = 1
            self._state = self._FUNC_MACRO_ARGS
        elif token.startswith('/*') or token.startswith('//'):
            _result = self._make_comment(token)
        elif token.isspace():
            # whitespace ignored while waiting for macro opening bracket
            pass
        else:
            # token is not opening bracket, revert back to global state
            self._state = self._GLOBAL
            _result = self._GLOBAL(token)
        return _result

    def _FUNC_MACRO_ARGS(self, token):
        _result = None
        if token.startswith('/*') or token.startswith('//'):
            _result = self._make_comment(token)
        elif token in ('(', '<'):
            if self._macro_arg_idx == 0:
                self._macro_arg0_tokens.append(token)
            self._macro_bracket_level += 1
        elif token in (')', '>'):
            self._macro_bracket_level -= 1
            if self._macro_bracket_level == 0:
                self._state = self._GLOBAL
                if self._macro_name == 'FUNC_P2CONST':
                    _exp_toks = ['const'] + list(self._macro_arg0_tokens) + ['*']
                elif self._macro_name == 'FUNC_P2VAR':
                    _exp_toks = list(self._macro_arg0_tokens) + ['*']
                else:
                    _exp_toks = list(self._macro_arg0_tokens)
                _result = (UniversalAnalyzer.DECL_PREFIX_TOKENS, _exp_toks)
            elif self._macro_arg_idx == 0:
                self._macro_arg0_tokens.append(token)
        elif token == ',' and self._macro_bracket_level == 1:
            self._macro_arg_idx += 1
        elif self._macro_arg_idx == 0:
            self._macro_arg0_tokens.append(token)
        else:
            # non-return-type macro argument token
            pass
        return _result

    def _OPERATOR(self, token):
        if token.startswith('/*') or token.startswith('//'):
            return self._make_comment(token)
        if token != '(':
            self._state = self._GLOBAL
        return UniversalAnalyzer.ADD_TO_FUNCTION_NAME, ' ' + token

    def _NAMESPACE(self, token):
        if token.startswith('/*') or token.startswith('//'):
            return self._make_comment(token)
        self._state = self._OPERATOR if token == 'operator'  else self._GLOBAL
        return UniversalAnalyzer.ADD_TO_FUNCTION_NAME, "::" + token

    def _DEC(self, token):
        if token in ('(', "<"):
            self.bracket_level += 1
        elif token in (')', ">"):
            self.bracket_level -= 1
            if (self.bracket_level == 0):
                self._state        = self._DEC_TO_IMP
                self._dec_end_line = self._current_line
        elif token.startswith('/*') or token.startswith('//'):
            return self._make_comment(token)
        elif self.bracket_level == 1:
            return UniversalAnalyzer.PARAMETER, token
        return UniversalAnalyzer.ADD_TO_LONG_FUNCTION_NAME, " " + token

    def _DEC_TO_IMP(self, token):
        if token in ('const', 'noexcept', 'override', 'final', 'volatile'):
            return UniversalAnalyzer.ADD_TO_LONG_FUNCTION_NAME, " " + token
        elif token == '{':
            self.br_count += 1
            self._state = self._IMP
            return UniversalAnalyzer.ENTER_FUNCTION_BODY, None
        elif token.startswith('/*') or token.startswith('//'):
            return self._make_comment(token)
        elif token in (';', '='):
            self._state = self._GLOBAL
            return UniversalAnalyzer.FLUSH_GLOBAL_TERM, self._current_line
        else:
            self._state = self._GLOBAL
            if self._current_line > self._dec_end_line + 1:
                return UniversalAnalyzer.RESET_AND_START_NEW_FUNCTION, (token, self._current_line)
            else:
                return UniversalAnalyzer.AFTER_DEC_START_NEW_FUNCTION, (token, self._current_line)

    def _IMP(self, token):
        if token in ("#else", "#if", "#endif"):
            self.last_preprocessor = token
        # will ignore the braces in a #else branch            
        if self.last_preprocessor != '#else':
            if token == '{':
                self.br_count += 1
            elif token == '}':
                self.br_count -= 1
                if self.br_count == 0:
                    self._state = self._GLOBAL
                    return UniversalAnalyzer.END_OF_FUNCTION, self._current_line
        if self._is_condition(token):
            return UniversalAnalyzer.CONDITION, token
        elif token.startswith('/*') or token.startswith('//'):
            return self._make_comment(token)
        return UniversalAnalyzer.TOKEN, token

class ObjCTokenTranslator(CTokenTranslator):
    def __init__(self):
        CTokenTranslator.__init__(self)

    def _DEC_TO_IMP(self, token):
        if token in ("+", "-"):
            self._state = self._GLOBAL
            return UniversalAnalyzer.FLUSH_PENDING_COMMENTS, None
        else:
            _res = CTokenTranslator._DEC_TO_IMP(self, token)
            if self._state == self._GLOBAL and token not in (';', '='):
                self._state = self._OBJC_DEC_BEGIN
            return _res
    def _OBJC_DEC_BEGIN(self, token):
        if token == ':':
            self._state = self._OBJC_DEC
            return UniversalAnalyzer.ADD_TO_FUNCTION_NAME, token
        elif token == '{':
            self.br_count += 1
            self._state = self._IMP
            return UniversalAnalyzer.ENTER_FUNCTION_BODY, None
        elif token.startswith('/*') or token.startswith('//'):
            return self._make_comment(token)
        else:
            self._state = self._GLOBAL
            return UniversalAnalyzer.FLUSH_PENDING_COMMENTS, None
    def _OBJC_DEC(self, token):
        if token == '(':
            self._state = self._OBJC_PARAM_TYPE
            return UniversalAnalyzer.ADD_TO_LONG_FUNCTION_NAME, token
        elif token == ',':
            pass
        elif token == '{':
            self.br_count += 1
            self._state = self._IMP
            return UniversalAnalyzer.ENTER_FUNCTION_BODY, None
        elif token.startswith('/*') or token.startswith('//'):
            return self._make_comment(token)
        else:
            self._state = self._OBJC_DEC_BEGIN
            return UniversalAnalyzer.ADD_TO_FUNCTION_NAME, " " + token

    def _OBJC_PARAM_TYPE(self, token):
        if token == ')':
            self._state = self._OBJC_PARAM
        return UniversalAnalyzer.ADD_TO_LONG_FUNCTION_NAME, " " + token
    def _OBJC_PARAM(self, token):
        self._state = self._OBJC_DEC

#c_pattern = re.compile(r".*\.(c|C|cpp|CPP|CC|cc|mm)$")
c_pattern = re.compile(r".*\.(c|C|h|cpp|CPP|CC|cc|mm)$")
java_pattern = re.compile(r".*\.(java)$")
objc_pattern = re.compile(r".*\.(m)$")

hfcca_language_infos = {
                 'c/c++': {
                  'name_pattern': c_pattern,
                  'creator':CTokenTranslator},
                 'Java': {
                  'name_pattern': java_pattern,
                  'creator':CTokenTranslator},
                  'objC' : {
                  'name_pattern': objc_pattern,
                  'creator':ObjCTokenTranslator}
            }

def get_parser_by_file_name(filename):
    for lan in hfcca_language_infos:
        info = hfcca_language_infos[lan]
        if info['name_pattern'].match(filename):
            return info['creator']

def get_parser_by_file_name_otherwise_default(filename):
    for lan in hfcca_language_infos:
        info = hfcca_language_infos[lan]
        if info['name_pattern'].match(filename):
            return info['creator']()
    return hfcca_language_infos['c/c++']['creator']()

"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
class FileAnalyzer:
    ''' A FileAnalyzer works as a function. It takes filename as parameter.
        Returns a list of function infos in this file.
    '''

    open = open

    def __init__(self, noCountPre=False):
        self.noCountPre = noCountPre

    def __call__(self, filename):
        return self.analyze(filename)


    def analyze_source_code_with_parser1(self, filename, code, parser):
        _tokens                 = list(generate_tokens(code))
        _static_decls_cnt       = compute_static_var_declarations(code)
        result                  = self.analyze_source_code_with_parser(filename, parser, _tokens)
        result.static_declarations_count = _static_decls_cnt
        result.line_count       = len(code.splitlines())
        result.unreachable_statements_count = sum(_f.dead_code_count for _f in result)
        for _f in result:
            _f.filename         = filename
        return result

    def analyze(self, filename):
        code = self._readFileContent(filename)
        parser = get_parser_by_file_name_otherwise_default(filename)
        if self.noCountPre:
            parser.remove_hash_if()
        result = self.analyze_source_code_with_parser1(filename, code, parser)
        return result


    def analyze_source_code_with_parser(self, filename, parser, tokens):
        result = UniversalAnalyzer().analyze(
                            parser.getFunctions(tokens), filename)
        return result

    def _readFileContent(self, filename):
        try:
            f = self.open(filename,'r')
            code = f.read()
            f.close()
        except:
            try:
                f = self.open(filename,'r', encoding='utf-8')
                code = f.read()
                f.close()
            except:
                f = self.open(filename,'r', encoding='latin-1')
                code = f.read()
                f.close()
        return code

token_pattern = re.compile(r"(\w+|/\*|//|:=|::|>=|\*=|\*\*|\*|>"+
                           r"|&=|&&|&"+
                           r"|#\s*define|#\s*if|#\s*else|#\s*endif|#\s*\w+"+
                           r"|[!%^&\*\-=+\|\\<>/\]\+]+|.)", re.M | re.S)

_pp_comment_pattern = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|(/\*.*?\*/|//[^\n]*)', re.S)

def generate_tokens(source_code):
    for t, l in generate_tokens_from_code(source_code):
        if t.startswith('#'):
            _norm_pp = '#' + t[1:].lstrip()
            if _norm_pp.startswith('#define'):
                yield '#define', l
                for _cm in _pp_comment_pattern.finditer(t):
                    if _cm.group(1) is not None:
                        yield _cm.group(1), l
            elif _norm_pp.startswith('#endif'):
                yield '#endif', l
                for _cm in _pp_comment_pattern.finditer(t):
                    if _cm.group(1) is not None:
                        yield _cm.group(1), l
            elif _norm_pp.startswith('#if'):
                yield '#if', l
                for _cm in _pp_comment_pattern.finditer(t):
                    if _cm.group(1) is not None:
                        yield _cm.group(1), l
            else:
                yield t, l
        else:
            yield t, l

def generate_tokens_from_code(source_code):
    in_middle_of_empty_lines = True
    last_line = 1
    for (token, line) in tokens_from_code_with_multiple_newlines(source_code):
        last_line = line
        _is_comment = token.startswith('/*') or token.startswith('//')
        if _is_comment:
            yield token, line
            if '\n' in token and not in_middle_of_empty_lines:
                yield '\n', line
                in_middle_of_empty_lines = True
        else:
            if token != '\n' or not in_middle_of_empty_lines:
                yield token, line
            in_middle_of_empty_lines = (token == '\n')
    if not in_middle_of_empty_lines:
        yield '\n', last_line

def tokens_from_code_with_multiple_newlines(source_code):
    index = 0
    line = 1
    while 1:
        m = token_pattern.match(source_code, index)
        if not m:
            break
        token = m.group(0)
        if token == '\n': line += 1

        if token.startswith("#"):
            token = "#" + token[1:].strip()

        if token == "#define":
            while(1):
                bindex = index + 1
                index = source_code.find('\n', bindex)
                if index == -1:
                    break
                if not source_code[bindex:index].rstrip().endswith('\\'):
                    break
            if index == -1:
                index = len(source_code)
            token = source_code[m.start(0):index]
        elif token == '/*':
            index = source_code.find("*/", index + 2)
            if index == -1:
                break
            index += 2
            token = source_code[m.start(0):index]
        elif token == '//':
            index = source_code.find('\n', index)
            if index == -1:
                index = len(source_code)
            token = source_code[m.start(0):index]
        elif token in ('#if', '#endif'):
            index = source_code.find('\n', index)
            if index == -1:
                index = len(source_code)
            token = source_code[m.start(0):index]
        elif token == '"' or token == '\'':
            while(1):
                index += 1
                index = source_code.find(token, index)
                if index == -1:
                    break
                if source_code[index - 1] == '\\':
                    if source_code[index - 2] != '\\':
                        continue
                break
            if index == -1:
                break
            token = source_code[m.start(0):index + 1]
            index = index + 1
        else:
            index = m.end(0)
        line += (len(token.splitlines()) - 1)
        if not token.isspace() or token == '\n':
            yield token, line

def print_function_info_header():
    print("==============================================================")
    print("  nloc    CCN  token  param    function@line@file")
    print("--------------------------------------------------------------")

def print_function_info(fun, filename, option):
    output_params = {
        'nloc': fun.nloc,
        'CCN': fun.cyclomatic_complexity,
        'token': fun.token_count,
        'param': fun.parameter_count,
        'name': fun.name,
        'line': fun.start_line,
        'file': filename
    }
    output_format = "%(nloc)6d %(CCN)6d %(token)6d %(param)6d    %(name)s@%(line)s@%(file)s"
    if option.verbose:
        output_params['name'] = fun.long_name()
    if option.warnings_only:
        output_format = "%(file)s:%(line)s: warning: %(name)s has %(CCN)d CCN and %(param)d params (%(nloc)d NLOC, %(token)d tokens)"
    print(output_format % output_params)

def print_warnings(option, saved_result):
    warning_count = 0
    if not option.warnings_only:
        print(("\n" +
              "======================================\n" +
              "!!!! Warnings (CCN > %d) !!!!\n" +
              "======================================") % option.CCN)
    for f in saved_result:
        for fun in f:
            if fun.cyclomatic_complexity > option.CCN or \
                    fun.parameter_count > option.arguments:
                warning_count += 1
                print_function_info(fun, f.filename, option)

    if warning_count == 0:
        print("No warning found. Excellent!")

    return warning_count

def print_total(warning_count, saved_result, option):
    all_fun = list(itertools.chain(*saved_result))
    cnt = len(all_fun)
    if (cnt == 0):
        cnt = 1
    tNLOC = sum([f.nloc for f in all_fun])
    if (tNLOC == 0):
        tNLOC = 1
    total_info = (
                  tNLOC, tNLOC / cnt,
                  float(sum([f.cyclomatic_complexity for f in all_fun])) / cnt,
                  float(sum([f.token_count for f in all_fun])) / cnt,
                  cnt,
                  warning_count,
                  float(warning_count) / cnt,
                  float(sum([f.nloc for f in all_fun if f.cyclomatic_complexity > option.CCN])) / tNLOC
                  )

    if not option.warnings_only:
        print("=================================================================================")
        print("Total nloc  Avg.nloc  Avg CCN  Avg token  Fun Cnt  Warning cnt   Fun Rt   nloc Rt  ")
        print("--------------------------------------------------------------------------------")
        print("%10d%10d%9.2f%11.2f%9d%13d%10.2f%8.2f" % total_info)

def print_and_save_detail_information(allStatistics, option):
    saved_result = []
    if (option.warnings_only):
        saved_result = allStatistics
    else:
        print_function_info_header()
        for fileStatistics in allStatistics:
            saved_result.append(fileStatistics)
            for fun in fileStatistics:
                print_function_info(fun, fileStatistics.filename, option)

        print("--------------------------------------------------------------")
        print("%d file analyzed." % (len(saved_result)))
        print("==============================================================")
        print("NLOC    Avg.NLOC AvgCCN Avg.ttoken  function_cnt    file")
        print("--------------------------------------------------------------")
        for fileStatistics in saved_result:
            print("%7d%7d%7d%10d%10d     %s" % (fileStatistics.nloc, fileStatistics.average_NLOC, fileStatistics.average_CCN, fileStatistics.average_token, len(fileStatistics), fileStatistics.filename))

    return saved_result

def print_result(r, option):
    saved_result = print_and_save_detail_information(r, option)
    warning_count = print_warnings(option, saved_result)
    print_total(warning_count, saved_result, option)
    if option.number > warning_count:
        sys.exit(1)

"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
class YAMLFormatter(object):
    def xml_output(self, result, options):
        _yaml_output = yaml.dump(
            result,
            default_flow_style = False)
        return _yaml_output

"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
class XMLFormatter(object):
    def xml_output(self, result, options):
        _code_metrics_el = etree.Element("Code_metrics")
        _functions_el    = etree.SubElement(_code_metrics_el, "Functions")
        _sources_el      = etree.SubElement(_code_metrics_el, "Source_files")
        for _source_file in result:
            _source_el = etree.SubElement(_sources_el, "Source")
            for _attr_name, _attr_value in vars(_source_file).items():
                if not _attr_name.startswith('_'):
                    etree.SubElement(_source_el, _attr_name).text = str(_attr_value)
                else:
                    # private attribute
                    pass

            for _func in _source_file:
                _function_el = etree.SubElement(_functions_el, "Function")
                for _attr_name, _attr_value in vars(_func).items():
                    if not _attr_name.startswith('_'):
                        etree.SubElement(_function_el, _attr_name).text = str(_attr_value)
                    else:
                        # private attribute
                        pass
        _xml_result = etree.tostring(
            _code_metrics_el,
            pretty_print = True)
        return _xml_result

"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
class XMLLFormatter(object):
    
    def xml_output(self, result, options):
        ''' Thanks for Holy Wen from Nokia Siemens Networks to let me use his code
            to put the result into xml file that is compatible with cppncss.
            Jenkens has plugin for cppncss format result to display the diagram.
        '''
        import xml.dom.minidom
    
        impl = xml.dom.minidom.getDOMImplementation()
        doc = impl.createDocument(None, "cppncss", None)
        root = doc.documentElement
    
        measure = doc.createElement("measure")
        measure.setAttribute("type", "Function")
        measure.appendChild(self._createLabels(doc, ["Nr.", "NCSS", "CCN"]))
    
        Nr = 0
        total_func_ncss = 0
        total_func_ccn = 0
    
        for source_file in result:
            file_name = source_file.filename
            for func in source_file:
                Nr += 1
                total_func_ncss += func.nloc
                total_func_ccn += func.cyclomatic_complexity
                measure.appendChild(self._createFunctionItem(doc, Nr, file_name, func))
    
            if Nr != 0:
                measure.appendChild(self._createLabeledValueItem(doc, 'average', "NCSS", str(total_func_ncss / Nr)))
                measure.appendChild(self._createLabeledValueItem(doc, 'average', "CCN", str(total_func_ccn / Nr)))
    
        root.appendChild(measure)
    
        measure = doc.createElement("measure")
        measure.setAttribute("type", "File")
        measure.appendChild(self._createLabels(doc, ["Nr.", "NCSS", "CCN", "Functions"]))
    
        file_NR = 0
        file_total_ncss = 0
        file_total_ccn = 0
        file_total_funcs = 0
    
        for source_file in result:
            file_NR += 1
            file_total_ncss += source_file.nloc
            file_total_ccn += source_file.CCN
            file_total_funcs += len(source_file)
            measure.appendChild(self._createFileNode(doc, source_file, file_NR))
    
        if file_NR != 0:
            fileSummary = [("NCSS", file_total_ncss / file_NR),
                           ("CCN", file_total_ccn / file_NR),
                           ("Functions", file_total_funcs / file_NR)]
            for k, v in fileSummary:
                measure.appendChild(self._createLabeledValueItem(doc, 'average', k, v))
    
        summary = [("NCSS", file_total_ncss),
                       ("CCN", file_total_ccn ),
                       ("Functions", file_total_funcs)]
        for k, v in summary:
            measure.appendChild(self._createLabeledValueItem(doc, 'sum', k, v))
    
        root.appendChild(measure)
    
        xmlString = doc.toprettyxml()
        return xmlString

    def _createLabel(self, doc, name):
        label = doc.createElement("label")
        text1 = doc.createTextNode(name)
        label.appendChild(text1)
        return label

    def _createLabels(self, doc, labelNames):
        labels = doc.createElement("labels")
        for label in labelNames:
            labels.appendChild(self._createLabel(doc, label))
        
        return labels

    def _createFunctionItem(self, doc, Nr, file_name, func):
        item = doc.createElement("item")
        item.setAttribute("name", "%s(...) at %s:0" % (func.name, file_name))
        value1 = doc.createElement("value")
        text1 = doc.createTextNode(str(Nr))
        value1.appendChild(text1)
        item.appendChild(value1)
        value2 = doc.createElement("value")
        text2 = doc.createTextNode(str(func.nloc))
        value2.appendChild(text2)
        item.appendChild(value2)
        value3 = doc.createElement("value")
        text3 = doc.createTextNode(str(func.cyclomatic_complexity))
        value3.appendChild(text3)
        item.appendChild(value3)
        return item


    def _createLabeledValueItem(self, doc, name, label, value):
        average_ncss = doc.createElement(name)
        average_ncss.setAttribute("lable", label)
        average_ncss.setAttribute("value", str(value))
        return average_ncss


    def _createFileNode(self, doc, source_file, file_NR):
        item = doc.createElement("item")
        item.setAttribute("name", source_file.filename)
        value1 = doc.createElement("value")
        text1 = doc.createTextNode(str(file_NR))
        value1.appendChild(text1)
        item.appendChild(value1)
        value2 = doc.createElement("value")
        text2 = doc.createTextNode(str(source_file.nloc))
        value2.appendChild(text2)
        item.appendChild(value2)
        value3 = doc.createElement("value")
        text3 = doc.createTextNode(str(source_file.CCN))
        value3.appendChild(text3)
        item.appendChild(value3)
        value4 = doc.createElement("value")
        text4 = doc.createTextNode(str(len(source_file)))
        value4.appendChild(text4)
        item.appendChild(value4)
        return item

def createHfccaCommandLineParser():
    from optparse import OptionParser
    parser = OptionParser(version=VERSION)
    parser.add_option("-v", "--verbose",
            help="Output in verbose mode (long function name)",
            action="store_true",
            dest="verbose",
            default=False)
    parser.add_option("-C", "--CCN",
            help =  "Threshold for cyclomatic complexity number warning. "+
                    "The default value is %d. Functions with CCN bigger than this number will generate warning" % DEFAULT_CCN_THRESHOLD,
            action="store",
            type="int",
            dest="CCN",
            default=DEFAULT_CCN_THRESHOLD)
    parser.add_option("-a", "--arguments",
            help="Limit for number of parameters",
            action="store",
            type="int",
            dest="arguments",
            default=100)
    parser.add_option("-w", "--warnings_only",
            help="Show warnings only, using clang/gcc's warning format for printing warnings. http://clang.llvm.org/docs/UsersManual.html#cmdoption-fdiagnostics-format",
            action="store_true",
            dest="warnings_only",
            default=False)
    parser.add_option("-i", "--ignore_warnings",
            help="If the number of warnings is equal or less than the number, the tool will exit normally, otherwize it will generate error. Useful in makefile when improving legacy code.",
            action="store",
            type="int",
            dest="number",
            default=0)
    parser.add_option("-x", "--exclude",
            help="Exclude files that match this pattern. * matches everything, ? matches any single characoter, \"./folder/*\" exclude everything in the folder, recursively. Multiple patterns can be specified. Don't forget to add \"\" around the pattern.",
            action="append",
            dest="exclude",
            default=[])
    parser.add_option("-X", "--xml",
            help="Generate XML in cppncss style instead of the normal tabular output. Useful to generate report in Jenkins server",
            dest="xml",
            default=None)
    parser.add_option("-P", "--no_preprocessor_count",
            help="Ignore preprocessor #if directives in complexity calculation (ignored by default in classic McCabe mode)",
            action="store_true",
            dest="no_preprocessor_count",
            default=False)
    parser.add_option("-t", "--working_threads",
            help="number of working threads. The default value is 1.",
            action="store",
            type="int",
            dest="working_threads",
            default=1)
    parser.add_option("-n", "--input",
            help="file with a list of sources",
            action="store",
            type="str",
            dest="input",
            default=1)

    parser.usage = "hfcca [options] [PATH or FILE] [PATH] ... "
    parser.description = __doc__
    return parser

def mapFilesToAnalyzer(files, fileAnalyzer, working_threads):
    try:
        # python 2.6 cannot work properly with multiple threading
        if sys.version_info[0:2] == (2, 6):
            raise
        import multiprocessing
        it = multiprocessing.Pool(processes=working_threads)
        mapFun = it.imap_unordered
    except:
        try:
            mapFun = itertools.imap
        except:
            mapFun = map
    r = mapFun(fileAnalyzer, files)
    return r

import os
import fnmatch

def _notExluded(str_to_match, patterns):
    return get_parser_by_file_name(str_to_match) and \
        all(not fnmatch.fnmatch(str_to_match, p) for p in patterns)

def getSourceFiles(SRC_DIRs, exclude_patterns):
    for SRC_DIR in SRC_DIRs:
        if os.path.isfile(SRC_DIR) and get_parser_by_file_name(SRC_DIR):
            yield SRC_DIR
        else:
            for root, _, files in os.walk(SRC_DIR, topdown=False):
                for filename in files:
                    full_path_name = os.path.join(root, filename)
                    if _notExluded(full_path_name, exclude_patterns):
                        yield full_path_name

def analyze(paths, options):
    ''' This is the most important function of hfcca.
        It analyze the given paths with the options.
        Can be used directly by other Python application.
    '''
    files = getSourceFiles(paths, options.exclude)
    fileAnalyzer = FileAnalyzer(options.no_preprocessor_count)
    _analyzed_files = list(mapFilesToAnalyzer(files, fileAnalyzer, options.working_threads))

    # cross-file call graph resolution (calling_functions_count / fan-in and call_depth)
    _callers_map = {}
    _callees_map = {}
    for _file_info in _analyzed_files:
        for _func in _file_info:
            _callees_map[_func.name] = set(_func._called_functions)
            for _callee in _func._called_functions:
                if _callee not in _callers_map:
                    _callers_map[_callee] = set()
                else:
                    # callee already present
                    pass
                _callers_map[_callee].add(_func.name)

    for _file_info in _analyzed_files:
        for _func in _file_info:
            if _func.name in _callers_map:
                _func.calling_functions_count = len(_callers_map[_func.name])
            else:
                _func.calling_functions_count = 0

    _depth_memo = {}
    def _compute_call_depth(func_name, visited=None):
        _depth_result = 1
        if func_name in _depth_memo:
            _depth_result = _depth_memo[func_name]
        else:
            _active_visited = visited.copy() if visited is not None else set()
            if func_name in _active_visited or func_name not in _callees_map or not _callees_map[func_name]:
                _depth_result = 1
            else:
                _active_visited.add(func_name)
                _max_child = 0
                for _callee in _callees_map[func_name]:
                    if _callee not in _active_visited:
                        _child_d = _compute_call_depth(_callee, _active_visited)
                        if _child_d > _max_child:
                            _max_child = _child_d
                        else:
                            # not greater than current max
                            pass
                    else:
                        # cycle avoidance
                        pass
                _depth_result = 1 + _max_child
            _depth_memo[func_name] = _depth_result
        return _depth_result

    for _file_info in _analyzed_files:
        for _func in _file_info:
            _func.call_depth = _compute_call_depth(_func.name)

    return _analyzed_files

def hfcca_main(argv):
    options, args = createHfccaCommandLineParser().parse_args(args=argv)
    paths = ["."] if len(args) + len(options.__dict__) == 1 else args[1:]
    if options.input:
        with open(options.input) as f:
            paths.extend(f.read().splitlines()) 

    r = analyze(paths, options)
    if options.xml:
        with open(options.xml, 'w') as f:
            f.write(XMLFormatter().xml_output(list(r), options).decode('utf-8'))
    else:
        print_result(r, options)

def main():
    hfcca_main(sys.argv)

if __name__ == "__main__":
#     sys.path.append(r'c:\_work\eclipse\plugins\org.python.pydev_3.0.0.201311051910\pysrc')
#     import pydevd
#     pydevd.settrace(suspend=False)
    main()
