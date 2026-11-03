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

    def add_comment(self):
        self.comment_count += 1

    def add_return(self):
        self.return_count += 1

    def add_statement(self):
        self.statement_count += 1

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

    def add_path_branch(self):
        if self.path_count < 100000:
            self.path_count = self.path_count * 2
        else:
            # cap path count to avoid integer overflow
            pass

    def add_dead_code(self):
        self.dead_code_count += 1

    def add_if_without_else(self):
        self.if_without_else_count += 1

    def add_unused_variable(self):
        self.unused_variables_count += 1

    def finalize_metrics(self):
        self.called_count = len(self._called_functions)
        if self.statement_count > 0:
            self.average_statement_size = round(float(self.token_count) / float(self.statement_count), 2)
        else:
            self.average_statement_size = float(self.token_count)

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
        self.ccrp    = (_comment_count / (NLOC + _comment_count)) * 100 if (NLOC + _comment_count) != 0 else 0
        self.CCN     = _ccn
        self.token   = _token
        self.sloc    = _sloc
        self.eloc    = _eloc

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

    def analyze(self, parsed_code, filename):
        fileInfo = FileInformation(filename)
        for fun in self._functions(parsed_code):
            fileInfo.append(fun)
        fileInfo.summarize(self.nloc, self.comment_count)
        return fileInfo

    def START_NEW_FUNCTION(self, name_and_line):
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

    def CONDITION(self, token):
        self.TOKEN(token)
        self.current_function.add_condition()
        self.current_function.add_path_branch()

    def TOKEN(self, text):
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
            self.current_function.add_statement()
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
            if text.isidentifier() and text not in _type_names and text not in ('const', 'volatile', 'static', 'auto', 'register'):
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

    def COMMENT(self, text):
        lines = text.split('\n')
        for line in lines:
            _line = line.replace('*', '').replace('/', '').replace(' ', '').replace('\t', '')
            if len(_line):
                if self.current_function is not None:
                    self.current_function.add_comment()
                else:
                    self.comment_count += 1
            else:
                # empty comment line
                pass

    def NEW_LINE(self, token):
        self.nloc += 1
        self.newline = True

    def ADD_TO_LONG_FUNCTION_NAME(self, app):
        self.current_function.add_to_long_name(app)

    def ADD_TO_FUNCTION_NAME(self, app):
        self.current_function.add_to_function_name(app)

    def PARAMETER(self, token):
        self.current_function.add_parameter(token)
        self.ADD_TO_LONG_FUNCTION_NAME(" " + token)

    END_OF_FUNCTION = 1

    def _functions(self, parsed_code):
        for code, text in parsed_code:
            if code is UniversalAnalyzer.END_OF_FUNCTION:
                if self.current_function is not None:
                    if self.expecting_else_for is not None:
                        self.current_function.add_if_without_else()
                        self.expecting_else_for = None
                    else:
                        # no pending if check
                        pass
                    while len(self.if_stack) > 0:
                        self.if_stack.pop()
                        self.current_function.add_if_without_else()
                    for _vname, _vcnt in self.func_declared_vars.items():
                        if _vcnt <= 1:
                            self.current_function.add_unused_variable()
                        else:
                            # variable referenced in function body
                            pass
                    self.current_function.finalize_metrics()
                else:
                    # no function object
                    pass
                yield self.current_function
            else:
                code(self, text)

class TokenTranslatorBase:

    def __init__(self):
        self._state = self._GLOBAL
        self._current_line = 0

    def get_current_line(self):
        return self._current_line

    def getFunctions(self, tokens):
        for token, self._current_line in tokens:
            fun = self._read_token(token)
            if fun: yield fun

    def _read_token(self, token):
        if token.isspace():
            return UniversalAnalyzer.NEW_LINE, None
        else:
            return self._state(token)
    def remove_hash_if(self):
        self.conditions.remove("#if")


class CTokenTranslator(TokenTranslatorBase):

    def __init__(self):
        TokenTranslatorBase.__init__(self)
        self.conditions            = set(['if', 'for', 'while', '&&', '||', 'case', '?', '#if', 'catch'])
        self.bracket_level         = 0
        self.br_count              = 0
        self.last_preprocessor     = None
        self._macro_bracket_level  = 0

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
            self._state = self._FUNC_MACRO_WAIT_OPEN
        elif token == '(':
            self.bracket_level += 1
            self._state = self._DEC
            _result = (UniversalAnalyzer.ADD_TO_LONG_FUNCTION_NAME, token)
        elif token == '::':
            self._state = self._NAMESPACE
        elif token.startswith('/*') or token.startswith('//'):
            _result = (UniversalAnalyzer.COMMENT, token)
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
            _result = (UniversalAnalyzer.COMMENT, token)
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
        if token in ('(', '<'):
            self._macro_bracket_level += 1
        elif token in (')', '>'):
            self._macro_bracket_level -= 1
            if self._macro_bracket_level == 0:
                self._state = self._GLOBAL
            else:
                # still nested inside macro brackets
                pass
        elif token.startswith('/*') or token.startswith('//'):
            _result = (UniversalAnalyzer.COMMENT, token)
        else:
            # argument token within macro definition
            pass
        return _result

    def _OPERATOR(self, token):
        if token != '(':
            self._state = self._GLOBAL
        elif token.startswith('/*') or token.startswith('//'):
            return UniversalAnalyzer.COMMENT, token
        return UniversalAnalyzer.ADD_TO_FUNCTION_NAME, ' ' + token

    def _NAMESPACE(self, token):
        self._state = self._OPERATOR if token == 'operator'  else self._GLOBAL
        return UniversalAnalyzer.ADD_TO_FUNCTION_NAME, "::" + token

    def _DEC(self, token):
        if token in ('(', "<"):
            self.bracket_level += 1
        elif token in (')', ">"):
            self.bracket_level -= 1
            if (self.bracket_level == 0):
                self._state = self._DEC_TO_IMP
        elif self.bracket_level == 1:
            return UniversalAnalyzer.PARAMETER, token
        elif token.startswith('/*') or token.startswith('//'):
            return UniversalAnalyzer.COMMENT, token
        return UniversalAnalyzer.ADD_TO_LONG_FUNCTION_NAME, " " + token

    def _DEC_TO_IMP(self, token):
        if token == 'const':
            return UniversalAnalyzer.ADD_TO_LONG_FUNCTION_NAME, " " + token
        elif token == '{':
            self.br_count += 1
            self._state = self._IMP
        elif token.startswith('/*') or token.startswith('//'):
            return UniversalAnalyzer.COMMENT, token
        else:
            self._state = self._GLOBAL

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
                    return UniversalAnalyzer.END_OF_FUNCTION, ""
        if self._is_condition(token):
            return UniversalAnalyzer.CONDITION, token
        elif token.startswith('/*') or token.startswith('//'):
            return UniversalAnalyzer.COMMENT, token
        return UniversalAnalyzer.TOKEN, token

class ObjCTokenTranslator(CTokenTranslator):
    def __init__(self):
        CTokenTranslator.__init__(self)

    def _DEC_TO_IMP(self, token):
        if token in ("+", "-"):
            self._state = self._GLOBAL
        else:
            CTokenTranslator._DEC_TO_IMP(self, token)
            if self._state == self._GLOBAL:
                self._state = self._OBJC_DEC_BEGIN
                return UniversalAnalyzer.START_NEW_FUNCTION,\
                        (token, self._current_line)
    def _OBJC_DEC_BEGIN(self, token):
        if token == ':':
            self._state = self._OBJC_DEC
            return UniversalAnalyzer.ADD_TO_FUNCTION_NAME, token
        elif token == '{':
            self.br_count += 1
            self._state = self._IMP
        else:
            self._state = self._GLOBAL
    def _OBJC_DEC(self, token):
        if token == '(':
            self._state = self._OBJC_PARAM_TYPE
            return UniversalAnalyzer.ADD_TO_LONG_FUNCTION_NAME, token
        elif token == ',':
            pass
        elif token == '{':
            self.br_count += 1
            self._state = self._IMP
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
        _static_decls_cnt       = sum(1 for _tok, _ln in _tokens if _tok == 'static')
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

def generate_tokens(source_code):
    for t, l in generate_tokens_from_code(source_code):
        if not any(t.startswith(x) for x in ('#define',)): #, '/*', '//')) :
            yield t, l

def generate_tokens_from_code(source_code):
    in_middle_of_empty_lines = False
    for (token, line) in tokens_from_code_with_multiple_newlines(source_code):
        if token != '\n' or not in_middle_of_empty_lines:
            yield token, line
        in_middle_of_empty_lines = (token == '\n')

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
                break
            token = source_code[m.start(0):index]
        elif token == '/*':
            index = source_code.find("*/", index + 2)
            if index == -1:
                break
            index += 2
            token = source_code[m.start(0):index]
        elif token in( '//', '#if','#endif'):
            index = source_code.find('\n', index)
            if index == -1:
                break
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
            help="By default, a #if will also increase the complexity. Adding this option to ignore them",
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
