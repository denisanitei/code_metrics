from xml2html import xml2html
import waflib
from waflib.Task import Task
from waflib import Node
from waflib import Logs
try:
    from waflib import Options
except ImportError:
    Options = None
from waflib.TaskGen import feature
from waflib.TaskGen import before_method
from waflib.TaskGen import after_method
from lxml import etree
import ast
import json
from json import dumps
from jinja2 import Template
import xml.etree.ElementTree as ET
import xml.dom.minidom
import sys
import os
import tempfile
import subprocess
from pprint import pprint
from tw_time import get_current_date_time
from tw_time import get_date_time_from_timestamp
import zlib
from pathlib import Path
import configparser
import urllib.parse


CODE_METRICS_SAVED_MAPPING = {}
_CODE_METRICS_CFG = {

                        "source_ext":['c','cxx']
                    }

##### CODE METRICS THRESHOLDS #####
# Cyclomatic Complexity Threshold
CC_THRESHOLD = 20

# Non-Comment of Lines of Code Threshold
NLOC_THRESHOLD = 200

# logical lines of code threshold
SLOC_THRESHOLD = 70

# executable lines of code threshold
ELOC_THRESHOLD = 50

# minimum function comment density ratio (cdrp) threshold (%)
MIN_COMMENT_RATIO = 10

# minimum file comment density ratio (cdrp) threshold (%)
MIN_FILE_COMMENT_RATIO = 10

# maximum function parameters threshold (his stability)
PARAM_THRESHOLD = 5

# maximum function return points threshold (his stability)
RETURN_THRESHOLD = 1

# maximum control structure nesting depth threshold (his testability)
NESTING_DEPTH_THRESHOLD = 4

# maximum executable statements per function (his analysability)
STMT_THRESHOLD = 50

# maximum language scope / vocabulary frequency (his analysability vocf)
VOCF_THRESHOLD = 4.0

# maximum goto statements (his changeability)
GOTO_THRESHOLD = 0

# maximum calling functions / fan-in (his stability)
CALLING_THRESHOLD = 10

# maximum execution paths (his stability)
PATH_THRESHOLD = 1000

# maximum recursions (his stability)
REC_THRESHOLD = 0

# maximum dead code / unused statements (his stability)
DEAD_CODE_THRESHOLD = 0

# maximum called functions / fan-out (his testability)
CALLS_THRESHOLD = 7

# maximum call graph depth (oem audit)
CALL_DEPTH_THRESHOLD = 6

# maximum lines in a file (oem audit)
FILE_LINES_THRESHOLD = 1200

# maximum static declarations in a file (oem audit)
STATIC_DECLS_THRESHOLD = 20

# maximum if statements without else branch (misra c rule 15.7)
IF_WITHOUT_ELSE_THRESHOLD = 0

_THRESHOLD_YAML_KEYS = (
    'cc_threshold',
    'nloc_threshold',
    'sloc_threshold',
    'eloc_threshold',
    'min_comment_ratio',
    'min_file_comment_ratio',
    'param_threshold',
    'return_threshold',
    'nesting_depth_threshold',
    'stmt_threshold',
    'vocf_threshold',
    'goto_threshold',
    'calling_threshold',
    'calls_threshold',
    'path_threshold',
    'rec_threshold',
    'unreachable_statements_threshold',
    'dead_code_threshold',
    'call_depth_threshold',
    'file_lines_threshold',
    'static_declarations_threshold',
    'if_without_else_threshold',
)

_BLOCKER_TRUE_VALUES = frozenset((
    '1',
    'true',
    'yes',
    'on',
    'blocker',
    'block',
    'fail',
    'error',
))

_BLOCKER_FALSE_VALUES = frozenset((
    '0',
    'false',
    'no',
    'off',
    'non_blocker',
    'non-blocker',
    'nonblocker',
    'pass',
    'warn',
    'warning',
    'none',
    '',
))

_GLOBAL_BLOCKER_KEYS = (
    'code_metrics_blocker',
    'all_thresholds_blocker',
)


def _has_configured_thresholds(yaml_opts):
    if not yaml_opts:
        return False
    return any(yaml_opts.get(_key) is not None for _key in _THRESHOLD_YAML_KEYS)


def _get_opt(yaml_opts, key, default):
    _val = yaml_opts.get(key) if yaml_opts else None
    return _val if _val is not None else default


def _parse_bool_blocker(value):
    # parse a --params value into True (blocker), False (non-blocker), or None (unspecified)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        _norm = value.strip().lower()
        if _norm in _BLOCKER_TRUE_VALUES:
            return True
        if _norm in _BLOCKER_FALSE_VALUES:
            return False
        return False
    return False


def _parse_params_dict(raw_params):
    # normalize Waf --params (dict, sequence, or string) into a lowercase-keyed flat dict
    if not raw_params:
        return {}
    _parsed = None
    if isinstance(raw_params, dict):
        _parsed = raw_params
    elif isinstance(raw_params, (list, tuple)):
        _merged_seq = {}
        for _item in raw_params:
            _merged_seq.update(_parse_params_dict(_item))
        return _merged_seq
    elif isinstance(raw_params, str):
        _text = raw_params.strip()
        if not _text:
            return {}
        for _loader in (json.loads, ast.literal_eval):
            try:
                _candidate = _loader(_text)
                if isinstance(_candidate, dict):
                    _parsed = _candidate
                    break
            except Exception:
                pass
        if _parsed is None:
            _parsed = {}
            _inner = _text[1:-1].strip() if (_text.startswith('{') and _text.endswith('}')) else _text
            for _chunk in _inner.replace(';', ',').split(','):
                _chunk = _chunk.strip()
                if not _chunk:
                    continue
                if '=' in _chunk:
                    _k, _v = _chunk.split('=', 1)
                elif ':' in _chunk:
                    _k, _v = _chunk.split(':', 1)
                else:
                    continue
                _parsed[_k.strip().strip('\'"')] = _v.strip().strip('\'"')
    else:
        return {}

    _norm_map = {}
    for _k, _v in _parsed.items():
        _k_norm = str(_k).strip().lower()
        if _k_norm in ('code_metrics', 'code_metrics_blockers', 'blockers') and isinstance(_v, dict):
            for _sub_k, _sub_v in _v.items():
                _norm_map[str(_sub_k).strip().lower()] = _sub_v
        else:
            _norm_map[_k_norm] = _v
    return _norm_map


def _extract_waf_params(context_obj):
    # merge --params dictionaries from general (CLI Options / env / bld) to specific (tgen / task)
    _candidates = []
    if context_obj is not None:
        _candidates.append(getattr(context_obj, 'init_waf_params', None))

    _opt_mod = Options if Options is not None else getattr(waflib, 'Options', None)
    if _opt_mod is not None:
        _opt_obj = getattr(_opt_mod, 'options', None)
        if _opt_obj is not None:
            _candidates.append(getattr(_opt_obj, 'params', None))

    if context_obj is not None:
        _tgen = getattr(context_obj, 'generator', None)
        _bld = getattr(_tgen, 'bld', None) if _tgen is not None else getattr(context_obj, 'bld', None)
        if _bld is not None:
            _env = getattr(_bld, 'env', None)
            if _env is not None:
                for _env_key in ('PARAMS', 'params'):
                    try:
                        if _env_key in _env:
                            _candidates.append(_env[_env_key])
                    except Exception:
                        pass
            _bld_opts = getattr(_bld, 'options', None)
            if _bld_opts is not None:
                _candidates.append(getattr(_bld_opts, 'params', None))
            _candidates.append(getattr(_bld, 'params', None))
        if _tgen is not None:
            _candidates.append(getattr(_tgen, 'params', None))
            _candidates.append(getattr(_tgen, 'waf_params', None))
        _candidates.append(getattr(context_obj, 'params', None))
        _candidates.append(getattr(context_obj, 'waf_params', None))

    _merged = {}
    for _cand in _candidates:
        if _cand is not None:
            _merged.update(_parse_params_dict(_cand))
    return _merged


def _is_suite_blocker(suite_cfg, waf_params):
    # return True only if this metric suite is explicitly configured as a blocker in --params
    if not waf_params:
        return False
    for _pkey in suite_cfg.get('param_keys', ()):
        _k_lower = _pkey.lower()
        if _k_lower in waf_params:
            _decision = _parse_bool_blocker(waf_params[_k_lower])
            if _decision is not None:
                return _decision
    for _gkey in _GLOBAL_BLOCKER_KEYS:
        if _gkey in waf_params and not isinstance(waf_params[_gkey], dict):
            _decision = _parse_bool_blocker(waf_params[_gkey])
            if _decision is not None:
                return _decision
    return False


"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
def nodes2paths(mixed_nodes):
    # convert mixed nodes or paths to canonical case-sensitive paths on disk (deduplicated)
    _paths = []
    _seen  = set()
    for _node in mixed_nodes:
        try:
            _raw_path = _node.abspath()
        except AttributeError:
            _raw_path = str(_node)
        try:
            _resolved_path = str(Path(_raw_path).resolve())
        except Exception:
            _resolved_path = _raw_path
        if _resolved_path not in _seen:
            _seen.add(_resolved_path)
            _paths.append(_resolved_path)
    return _paths

"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
def get_git_commit_hash(project_path):
    # get current git commit hash
    _git_hash    = "N/A"
    _command     = ["git", "rev-parse", "HEAD"]
    try:
        _output      = subprocess.check_output(
            _command,
            cwd=project_path,
            stderr=subprocess.DEVNULL)
        _decoded     = _output.decode("utf-8").strip()
        if len(_decoded) > 0:
            _git_hash    = _decoded
        else:
            # fallback if output is empty
            _git_hash    = "unknown"
    except Exception:
        # fallback if git command fails or repository not present
        _git_hash    = "N/A"
    return _git_hash

"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
def get_git_commit_date(project_path):
    # retrieve commit date for repository or fallback to current datetime
    _commit_date = ""
    _timestamp   = None
    _command     = [
                    "git",
                    "log",
                    "-1",
                    "--format=%ct"
                   ]
    try:
        _output      = subprocess.check_output(
            _command,
            cwd=project_path,
            stderr=subprocess.DEVNULL)
        _decoded     = _output.decode("utf-8").strip()
        if len(_decoded) > 0:
            _timestamp   = int(_decoded)
        else:
            # empty output from git command
            _timestamp   = None
    except Exception:
        # fallback if git command fails or git executable not in path
        _timestamp   = None

    if _timestamp is None:
        try:
            _head_file_path = os.path.join(project_path, ".git", "HEAD")
            if os.path.exists(_head_file_path):
                with open(_head_file_path, "r", encoding = "utf-8", errors = "ignore") as _head_file:
                    _head_content = _head_file.read().strip()
                if _head_content.startswith("ref: "):
                    _ref_path = _head_content.split(" ")[1]
                    _ref_file = os.path.join(project_path, ".git", _ref_path.replace("/", os.sep))
                    if os.path.exists(_ref_file):
                        with open(_ref_file, "r", encoding = "utf-8", errors = "ignore") as _ref_file_handle:
                            _commit_sha = _ref_file_handle.read().strip()
                    else:
                        _commit_sha = None
                else:
                    _commit_sha = _head_content
                if _commit_sha and len(_commit_sha) >= 4:
                    _object_path = os.path.join(project_path, ".git", "objects", _commit_sha[:2], _commit_sha[2:])
                    if os.path.exists(_object_path):
                        with open(_object_path, "rb") as _object_file:
                            _decompressed = zlib.decompress(_object_file.read()).decode("latin-1")
                            for _line in _decompressed.splitlines():
                                if _line.startswith("committer "):
                                    _committer_parts = _line.split(" ")
                                    _timestamp       = int(_committer_parts[-2])
                                    break
                                else:
                                    # not committer header line
                                    pass
                    else:
                        # object file does not exist
                        pass
                else:
                    # commit sha invalid or empty
                    pass
            else:
                # git head not found in project path
                pass
        except Exception:
            # error reading git object directly
            _timestamp   = None
    else:
        # timestamp already obtained from git command
        pass

    if _timestamp is not None:
        _commit_date = get_date_time_from_timestamp(_timestamp)
    else:
        # fallback to current datetime if commit date cannot be resolved
        _commit_date = get_current_date_time()

    return _commit_date

"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
def get_git_branch(project_path):
    # determine current git branch from git command or git head reference file
    _branch   = ""
    _command  = [
        "git",
        "rev-parse",
        "--abbrev-ref",
        "HEAD"
    ]
    try:
        _output   = subprocess.check_output(
            _command,
            cwd = project_path,
            stderr = subprocess.DEVNULL)
        _decoded  = _output.decode("utf-8").strip()
        if _decoded and _decoded != "HEAD":
            _branch = _decoded
        else:
            # detached head or empty output
            _branch = ""
    except Exception:
        # git command failed or not in path
        _branch   = ""

    if not _branch:
        _head_file_path = os.path.join(
            project_path,
            ".git",
            "HEAD")
        if not os.path.exists(_head_file_path):
            _git_file_path = os.path.join(
                project_path,
                ".git")
            if os.path.isfile(_git_file_path):
                try:
                    with open(_git_file_path, "r", encoding = "utf-8", errors = "ignore") as _git_file_handle:
                        _git_content = _git_file_handle.read().strip()
                    if _git_content.startswith("gitdir:"):
                        _git_dir_rel    = _git_content.split(":", 1)[1].strip()
                        _head_file_path = os.path.normpath(os.path.join(
                            project_path,
                            _git_dir_rel,
                            "HEAD"))
                    else:
                        # unrecognised git file format
                        pass
                except Exception:
                    # error reading gitlink file
                    pass
            else:
                # git path is not a file
                pass
        else:
            # git head file exists directly
            pass

        if os.path.exists(_head_file_path):
            try:
                with open(_head_file_path, "r", encoding = "utf-8", errors = "ignore") as _head_file:
                    _head_content = _head_file.read().strip()
                    if _head_content.startswith("ref: refs/heads/"):
                        _branch = _head_content.replace("ref: refs/heads/", "").strip()
                    else:
                        # head points to commit sha or detached state
                        _branch = "master"
            except Exception:
                # error reading git head file
                _branch = "master"
        else:
            # git head file does not exist
            _branch = "master"
    else:
        # branch resolved from git command
        pass

    if not _branch:
        _branch = "master"
    else:
        # valid branch found
        pass

    return _branch


"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
def get_git_remote_url(project_path):
    # retrieve git remote repository url for project or submodule
    _remote_url = ""
    _command    = [
        "git",
        "config",
        "--get",
        "remote.origin.url"
    ]
    try:
        _output     = subprocess.check_output(
            _command,
            cwd = project_path,
            stderr = subprocess.DEVNULL)
        _decoded    = _output.decode("utf-8").strip()
        if len(_decoded) > 0:
            _remote_url = _decoded
        else:
            # empty output from git config
            _remote_url = ""
    except Exception:
        # git command failed or not in path
        _remote_url = ""

    if not _remote_url:
        try:
            _git_config_path = os.path.join(
                project_path,
                ".git",
                "config")
            if not os.path.exists(_git_config_path):
                _git_file_path = os.path.join(
                    project_path,
                    ".git")
                if os.path.isfile(_git_file_path):
                    with open(_git_file_path, "r", encoding = "utf-8", errors = "ignore") as _git_file_handle:
                        _git_content = _git_file_handle.read().strip()
                    if _git_content.startswith("gitdir:"):
                        _git_dir_rel     = _git_content.split(":", 1)[1].strip()
                        _git_config_path = os.path.normpath(os.path.join(
                            project_path,
                            _git_dir_rel,
                            "config"))
                    else:
                        # unrecognised git file format
                        pass
                else:
                    # git path is not a file
                    pass
            else:
                # git config exists directly
                pass

            if os.path.exists(_git_config_path):
                _cfg = configparser.ConfigParser()
                _cfg.read(
                    _git_config_path,
                    encoding = "utf-8")
                if _cfg.has_section('remote "origin"') and _cfg.has_option('remote "origin"', 'url'):
                    _remote_url = _cfg.get('remote "origin"', 'url').strip()
                else:
                    for _sec in _cfg.sections():
                        if _sec.startswith('remote ') and _cfg.has_option(_sec, 'url'):
                            _remote_url = _cfg.get(_sec, 'url').strip()
                            break
                        else:
                            # section is not a remote
                            pass
            else:
                # git config file not found
                pass
        except Exception:
            # error parsing git config file directly
            _remote_url = ""
    else:
        # remote url already resolved from git command
        pass

    return _remote_url


"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
def git_url_to_gitlab_web_url(git_url, default_server):
    # convert git remote repository url to gitlab web url
    _web_url = ""
    if git_url:
        _clean_url = str(git_url).strip()
        if _clean_url.endswith(".git"):
            _clean_url = _clean_url[:-4]
        else:
            # url does not end with dot git
            pass

        if _clean_url.startswith("http://") or _clean_url.startswith("https://"):
            _web_url = _clean_url
        elif "@" in _clean_url:
            _after_at   = _clean_url.split("@", 1)[1]
            if ":" in _after_at:
                _host_part = _after_at.split(":", 1)[0]
                _path_part = _after_at.split(":", 1)[1].lstrip("/")
            else:
                _host_part = _after_at.split("/", 1)[0]
                _path_part = _after_at.split("/", 1)[1].lstrip("/") if "/" in _after_at else ""

            if default_server:
                _base_server = str(default_server).rstrip("/")
                _web_url     = f"{_base_server}/{_path_part}"
            elif _host_part == "172.28.17.13":
                _web_url     = f"http://172.28.17.13:11011/{_path_part}"
            else:
                _web_url     = f"https://{_host_part}/{_path_part}"
        else:
            # unrecognized url format
            _web_url = _clean_url
    else:
        # empty git url
        _web_url = ""
    return _web_url


"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
def load_git_submodules(project_path, default_server, default_branch):
    # load submodule mappings from gitmodules configuration
    _submodules      = []
    _gitmodules_path = os.path.join(
        project_path,
        ".gitmodules")
    if os.path.exists(_gitmodules_path):
        try:
            _parser = configparser.ConfigParser()
            _parser.read(
                _gitmodules_path,
                encoding = "utf-8")
            for _section in _parser.sections():
                _sub_rel_path = _parser.get(
                    _section,
                    "path",
                    fallback = "").strip()
                _sub_git_url  = _parser.get(
                    _section,
                    "url",
                    fallback = "").strip()
                _sub_branch   = _parser.get(
                    _section,
                    "branch",
                    fallback = "").strip()
                if _sub_rel_path and _sub_git_url:
                    _sub_abs_path = os.path.normpath(os.path.join(
                        project_path,
                        _sub_rel_path))
                    try:
                        _resolved_sub_path = str(Path(_sub_abs_path).resolve())
                    except Exception:
                        _resolved_sub_path = _sub_abs_path
                    if not _sub_branch:
                        _sub_branch = get_git_branch(_resolved_sub_path)
                    else:
                        # branch specified explicitly in gitmodules
                        pass
                    if not _sub_branch:
                        _sub_branch = default_branch if default_branch else "master"
                    else:
                        # valid branch found
                        pass
                    _sub_web_url = git_url_to_gitlab_web_url(
                        _sub_git_url,
                        default_server)
                    _submodules.append({
                        "path"     : _sub_rel_path,
                        "abs_path" : _resolved_sub_path,
                        "web_url"  : _sub_web_url,
                        "branch"   : _sub_branch
                    })
                else:
                    # missing path or url in submodule section
                    pass
        except Exception:
            # error parsing gitmodules file
            _submodules = []
    else:
        # gitmodules file does not exist
        _submodules = []

    _submodules.sort(
        key = lambda _sub_item: len(_sub_item["abs_path"]),
        reverse = True)
    return _submodules


"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
def get_gitlab_url(abs_filepath, start_line, project_path, gitlab_base_url, branch, submodules = None):
    # construct gitlab url from xml filename and optional start_line
    _result_url = ""
    if abs_filepath and (gitlab_base_url or submodules):
        try:
            _resolved_file    = Path(str(abs_filepath).strip()).resolve()
        except Exception:
            _resolved_file    = Path(os.path.normpath(str(abs_filepath).strip()))
        try:
            _resolved_project = Path(str(project_path).strip()).resolve()
        except Exception:
            _resolved_project = Path(os.path.normpath(str(project_path).strip()))

        _matched_submodule = None
        _rel_path          = ""
        _target_base_url   = ""
        _target_branch     = ""

        if submodules:
            for _sub_item in submodules:
                try:
                    _sub_path_obj = Path(_sub_item["abs_path"])
                    _rel_to_sub   = _resolved_file.relative_to(_sub_path_obj).as_posix()
                    if _rel_to_sub and not _rel_to_sub.startswith(".."):
                        _matched_submodule = _sub_item
                        _rel_path          = _rel_to_sub
                        _target_base_url   = _sub_item["web_url"]
                        _target_branch     = _sub_item["branch"]
                        break
                    else:
                        # file not inside this submodule
                        pass
                except Exception:
                    _norm_file_path = str(_resolved_file).lower()
                    _norm_sub_path  = str(_sub_item["abs_path"]).lower()
                    if _norm_file_path.startswith(_norm_sub_path + os.sep) or _norm_file_path.startswith(_norm_sub_path + "/"):
                        _matched_submodule = _sub_item
                        _rel_path          = str(_resolved_file)[len(_sub_item["abs_path"]) + 1:].replace("\\", "/")
                        _target_base_url   = _sub_item["web_url"]
                        _target_branch     = _sub_item["branch"]
                        break
                    else:
                        # path does not start with submodule path
                        pass
        else:
            # no submodules provided
            pass

        if _matched_submodule is None:
            _target_base_url = gitlab_base_url
            _target_branch   = branch
            try:
                _rel_path    = _resolved_file.relative_to(_resolved_project).as_posix()
            except Exception:
                _norm_file    = str(_resolved_file)
                _norm_project = str(_resolved_project)
                if _norm_file.lower().startswith(_norm_project.lower() + os.sep):
                    _rel_path = _norm_file[len(_norm_project) + 1:].replace("\\", "/")
                else:
                    try:
                        _rel_path = os.path.relpath(
                            _norm_file,
                            _norm_project).replace("\\", "/")
                    except Exception:
                        _rel_path = _norm_file.replace("\\", "/")
        else:
            # file matched inside a submodule
            pass

        if _rel_path.startswith("./"):
            _rel_path = _rel_path[2:]
        else:
            # relative path does not start with dot slash
            pass

        _clean_base = _target_base_url.rstrip("/") if _target_base_url else ""
        if _rel_path and not _rel_path.startswith("..") and _clean_base:
            if start_line is not None and str(start_line).strip() and int(start_line) > 0:
                _line_num   = str(start_line).strip()
                _result_url = f"{_clean_base}/-/blob/{_target_branch}/{_rel_path}#L{_line_num}"
            else:
                # file level url without line anchor
                _result_url = f"{_clean_base}/-/blob/{_target_branch}/{_rel_path}"
        else:
            # path is outside project root or missing base url
            _result_url = ""
    else:
        # missing filepath or gitlab base url
        _result_url = ""
    return _result_url


def get_relative_source_path(file_path, project_path, path_cache):
    _rel_path = path_cache.get(file_path)
    if _rel_path is None:
        try:
            _resolved_path = str(Path(file_path).resolve())
            _rel_path      = os.path.relpath(
                _resolved_path,
                project_path).replace('\\', '/')
        except Exception:
            _rel_path      = file_path.replace('\\', '/')
        path_cache[file_path] = _rel_path
    else:
        # relative path already in cache
        pass
    return _rel_path


"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
@before_method('process_source')
@feature('code_metrics')
def code_metrics_filter_mappings(self):
    global CODE_METRICS_SAVED_MAPPING

    #The only way I could find was to bind an ignorer to the .c handling hooks
    def ignorer(tgen, node):
        pass

    #This messes up the following targets in case of a build*
    if self.typ == 'code_metrics':
        #Save the file mappings for backup
        CODE_METRICS_SAVED_MAPPING = { k:v for k,v in self.__class__.mappings.items()}

        self.__class__.mappings['.c'] = ignorer
        self.__class__.mappings['.cpp'] = ignorer
        self.__class__.mappings['.C'] = ignorer
        self.__class__.mappings['.S'] = ignorer
        self.__class__.mappings['.s'] = ignorer
        self.__class__.mappings['.s87'] = ignorer
        self.__class__.mappings['.asm'] = ignorer
        self.__class__.mappings['.ppc'] = ignorer
        self.__class__.mappings['.850'] = ignorer

"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
@feature('code_metrics')
@after_method('process_source')
def process_cc(self):

    global CODE_METRICS_SAVED_MAPPING
    global CC_THRESHOLD
    global NLOC_THRESHOLD
    global SLOC_THRESHOLD
    global ELOC_THRESHOLD
    global MIN_COMMENT_RATIO
    global MIN_FILE_COMMENT_RATIO
    global PARAM_THRESHOLD
    global RETURN_THRESHOLD
    global NESTING_DEPTH_THRESHOLD
    global STMT_THRESHOLD
    global VOCF_THRESHOLD
    global GOTO_THRESHOLD
    global CALLING_THRESHOLD
    global PATH_THRESHOLD
    global REC_THRESHOLD
    global DEAD_CODE_THRESHOLD
    global CALLS_THRESHOLD
    global CALL_DEPTH_THRESHOLD
    global FILE_LINES_THRESHOLD
    global STATIC_DECLS_THRESHOLD
    global IF_WITHOUT_ELSE_THRESHOLD

    #restore to the original file mappings
    #This helps in case multiple targets are run one after another
    if self.typ == 'code_metrics':
        self.__class__.mappings = CODE_METRICS_SAVED_MAPPING
    else:
        # not code_metrics target
        pass

    #get data from yaml
    yaml_opts = getattr(self, 'code_metrics', {})
    report_out_path = yaml_opts.get('report_out_path', None)

    CC_THRESHOLD              = yaml_opts.get('cc_threshold', CC_THRESHOLD)
    NLOC_THRESHOLD            = yaml_opts.get('nloc_threshold', NLOC_THRESHOLD)
    SLOC_THRESHOLD            = yaml_opts.get('sloc_threshold', SLOC_THRESHOLD)
    ELOC_THRESHOLD            = yaml_opts.get('eloc_threshold', ELOC_THRESHOLD)
    MIN_COMMENT_RATIO         = yaml_opts.get('min_comment_ratio', MIN_COMMENT_RATIO)
    MIN_FILE_COMMENT_RATIO    = yaml_opts.get('min_file_comment_ratio', MIN_FILE_COMMENT_RATIO)
    PARAM_THRESHOLD           = yaml_opts.get('param_threshold', PARAM_THRESHOLD)
    RETURN_THRESHOLD          = yaml_opts.get('return_threshold', RETURN_THRESHOLD)
    NESTING_DEPTH_THRESHOLD   = yaml_opts.get('nesting_depth_threshold', NESTING_DEPTH_THRESHOLD)
    STMT_THRESHOLD            = yaml_opts.get('stmt_threshold', STMT_THRESHOLD)
    VOCF_THRESHOLD            = yaml_opts.get('vocf_threshold', VOCF_THRESHOLD)
    GOTO_THRESHOLD            = yaml_opts.get('goto_threshold', GOTO_THRESHOLD)
    CALLING_THRESHOLD         = yaml_opts.get('calling_threshold', CALLING_THRESHOLD)
    PATH_THRESHOLD            = yaml_opts.get('path_threshold', PATH_THRESHOLD)
    REC_THRESHOLD             = yaml_opts.get('rec_threshold', REC_THRESHOLD)
    DEAD_CODE_THRESHOLD       = yaml_opts.get('unreachable_statements_threshold', yaml_opts.get('dead_code_threshold', DEAD_CODE_THRESHOLD))
    CALLS_THRESHOLD           = yaml_opts.get('calls_threshold', CALLS_THRESHOLD)
    CALL_DEPTH_THRESHOLD      = yaml_opts.get('call_depth_threshold', CALL_DEPTH_THRESHOLD)
    FILE_LINES_THRESHOLD      = yaml_opts.get('file_lines_threshold', FILE_LINES_THRESHOLD)
    STATIC_DECLS_THRESHOLD    = yaml_opts.get('static_declarations_threshold', STATIC_DECLS_THRESHOLD)
    IF_WITHOUT_ELSE_THRESHOLD = yaml_opts.get('if_without_else_threshold', IF_WITHOUT_ELSE_THRESHOLD)

    if 'cc_threshold' in yaml_opts:
        Logs.pprint("CYAN", "CC: %s" % CC_THRESHOLD)
    else:
        # cc threshold not configured
        pass

    if 'nloc_threshold' in yaml_opts:
        Logs.pprint("CYAN", "NLOC: %s" % NLOC_THRESHOLD)
    else:
        # nloc threshold not configured
        pass

    if 'sloc_threshold' in yaml_opts:
        Logs.pprint("CYAN", "SLOC: %s" % SLOC_THRESHOLD)
    else:
        # sloc threshold not configured
        pass

    if 'eloc_threshold' in yaml_opts:
        Logs.pprint("CYAN", "ELOC: %s" % ELOC_THRESHOLD)
    else:
        # eloc threshold not configured
        pass

    if 'min_comment_ratio' in yaml_opts:
        Logs.pprint("CYAN", "Minimum Function Comment Ratio (CDRP): %s" % MIN_COMMENT_RATIO)
    else:
        # min comment ratio not configured
        pass

    if 'min_file_comment_ratio' in yaml_opts:
        Logs.pprint("CYAN", "Minimum File Comment Ratio (CDRP): %s" % MIN_FILE_COMMENT_RATIO)
    else:
        # min file comment ratio not configured
        pass

    if 'param_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum Parameters: %s" % PARAM_THRESHOLD)
    else:
        # param threshold not configured
        pass

    if 'return_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum Return Points: %s" % RETURN_THRESHOLD)
    else:
        # return threshold not configured
        pass

    if 'nesting_depth_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum Nesting Depth: %s" % NESTING_DEPTH_THRESHOLD)
    else:
        # nesting depth threshold not configured
        pass

    if 'stmt_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum Statements: %s" % STMT_THRESHOLD)
    else:
        # stmt threshold not configured
        pass

    if 'vocf_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum Language Scope (VOCF): %s" % VOCF_THRESHOLD)
    else:
        # vocf threshold not configured
        pass

    if 'goto_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum GOTO Statements: %s" % GOTO_THRESHOLD)
    else:
        # goto threshold not configured
        pass

    if 'calling_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum Calling Functions: %s" % CALLING_THRESHOLD)
    else:
        # calling threshold not configured
        pass

    if 'path_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum Execution Paths: %s" % PATH_THRESHOLD)
    else:
        # path threshold not configured
        pass

    if 'rec_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum Recursions: %s" % REC_THRESHOLD)
    else:
        # rec threshold not configured
        pass

    if 'unreachable_statements_threshold' in yaml_opts or 'dead_code_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum Dead Code: %s" % DEAD_CODE_THRESHOLD)
    else:
        # dead code threshold not configured
        pass

    if 'calls_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum Called Functions: %s" % CALLS_THRESHOLD)
    else:
        # calls threshold not configured
        pass

    if 'call_depth_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum Call Graph Depth: %s" % CALL_DEPTH_THRESHOLD)
    else:
        # call depth threshold not configured
        pass

    if 'file_lines_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum File Lines: %s" % FILE_LINES_THRESHOLD)
    else:
        # file lines threshold not configured
        pass

    if 'static_declarations_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum Static Declarations: %s" % STATIC_DECLS_THRESHOLD)
    else:
        # static declarations threshold not configured
        pass

    if 'if_without_else_threshold' in yaml_opts:
        Logs.pprint("CYAN", "Maximum IF Without ELSE: %s" % IF_WITHOUT_ELSE_THRESHOLD)
    else:
        # if without else threshold not configured
        pass


    root_node = self.path.parent
    while root_node.parent is not None:
        root_node = root_node.parent

    #Make new node if necessary#
    rep_node = None
    rep_html = None
    if report_out_path is not None:
        if os.path.isabs(report_out_path):
            code_out = os.path.join(report_out_path, self.target + ".xml")

            try:
                os.makedirs(report_out_path)
            except Exception as e:
                pass #Most probably the directory already exists

            rep_node = root_node.make_node(code_out)
            rep_html = root_node.make_node(os.path.splitext(rep_node.abspath())[0] + '.html')
        else:
            #Relative paths are taken from the root of the project#
            code_out = os.path.join(report_out_path, self.target + ".xml")

            try:
                os.makedirs(os.path.join(self.path.abspath(), report_out_path))
            except Exception as e:
                pass #Most probably the directory already exists

            rep_node = self.path.make_node(code_out)
            rep_html = root_node.make_node(os.path.splitext(rep_node.abspath())[0] + '.html')

    else:
        build_dir_root_node = self.path.find_node('/').get_bld()
        rep_node            = build_dir_root_node.find_or_declare('__code_metrics__').find_or_declare(self.target + '.xml')
        rep_html            = build_dir_root_node.find_or_declare('__code_metrics__').find_or_declare(self.target + '.html')

    rep_template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'report_template.html')
    rep_template_node = root_node.make_node(rep_template_path)

    self.create_task(
        'cc_xml',
        self.source,
        rep_node,
        phase=25)
    _task_html            = self.create_task(
        'cc_xml2html',
        rep_node,
        [rep_html, rep_template_node],
        phase=26)
    _task_html.yaml_opts  = yaml_opts
    _task_junit             = self.create_task(
        'cc_xml2junit',
        xml_path=rep_node,
        phase=27)
    _task_junit.yaml_opts   = yaml_opts
    _task_junit.target_name = getattr(self, 'target', 'code_metrics')
    _init_params            = _extract_waf_params(self)
    if _init_params:
        _task_junit.init_waf_params = _init_params

"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
class cc_xml(Task):
    color = 'PINK'
    def sig_vars(self):
        super(cc_xml, self).sig_vars()
        _hfcca_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'hfcca.py')
        try:
            with open(_hfcca_path, 'rb') as _fh:
                self.m.update(_fh.read())
        except Exception:
            pass

    def run(self):
        headers = set()
        for _task in self.generator.tasks:
            for _source_ext in _CODE_METRICS_CFG['source_ext']:
                if _source_ext in waflib.Task.classes.keys():
                    if isinstance(_task, waflib.Task.classes[_source_ext]):
                        headers.update(self.generator.bld.node_deps.get(_task.uid(), []))

        hfcca_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'hfcca.py')
        f          = tempfile.NamedTemporaryFile(delete=False, mode='w')

        f.write('\r\n'.join(nodes2paths(self.inputs + list(headers))))
        f.close()

        result = self.exec_command([sys.executable, hfcca_path, '--xml=%s'%self.outputs[0].abspath(), '--input=%s'%f.name])

        os.unlink(f.name)

        return result

"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
class cc_xml2html(Task):
    color = 'PINK'
    def sig_vars(self):
        super(cc_xml2html, self).sig_vars()
        _tpl_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'report_template.html')
        try:
            with open(_tpl_path, 'rb') as _fh:
                self.m.update(_fh.read())
        except Exception:
            pass
        try:
            _opts = getattr(self, 'yaml_opts', None) or {}
            self.m.update(dumps(_opts, sort_keys=True, default=str).encode('utf-8'))
        except Exception:
            pass

    def run(self):
        _html_path      = self.outputs[0].abspath()
        _html_template  = self.outputs[1].abspath()
        _xml_path       = self.inputs[0].abspath()
        _project_path   = os.getcwd()
        if hasattr(self, "generator") and hasattr(self.generator, "bld") and hasattr(self.generator.bld, "srcnode"):
            _project_path = self.generator.bld.srcnode.abspath()
        else:
            # use current working directory as fallback
            pass
        try:
            _project_path = str(Path(_project_path).resolve())
        except Exception:
            # error resolving project path
            pass

        _yaml_opts      = getattr(self, 'yaml_opts', None)
        if _yaml_opts is None:
            if hasattr(self, 'generator') and hasattr(self.generator, 'code_metrics'):
                _yaml_opts  = self.generator.code_metrics
            else:
                _yaml_opts  = {
                              }
        else:
            # yaml_opts already attached to task
            pass

        _project_remote_url = get_git_remote_url(_project_path)
        _default_server     = ""
        _gitlab_url         = _yaml_opts.get('gitlab_url', '')
        if not _gitlab_url:
            _gitlab_url = _yaml_opts.get('git_url', '')
        else:
            # gitlab url found in yaml options
            pass

        if _gitlab_url:
            try:
                _parsed_url     = urllib.parse.urlsplit(_gitlab_url)
                if _parsed_url.scheme and _parsed_url.netloc:
                    _default_server = f"{_parsed_url.scheme}://{_parsed_url.netloc}"
                else:
                    _default_server = "http://172.28.17.13:11011"
            except Exception:
                _default_server = "http://172.28.17.13:11011"
        elif _project_remote_url:
            if "172.28.17.13" in _project_remote_url:
                _default_server = "http://172.28.17.13:11011"
            else:
                _default_server = ""
            _gitlab_url = git_url_to_gitlab_web_url(
                _project_remote_url,
                _default_server)
        else:
            _default_server = "http://172.28.17.13:11011"
            _gitlab_url     = "http://172.28.17.13:11011/prj_oem_ei_00268_volvo_xdm2/ygr_oem_ei_00268_volvo_xdm2_units"

        if not _default_server:
            _default_server = "http://172.28.17.13:11011"
        else:
            # default server resolved
            pass

        _branch         = get_git_branch(_project_path)
        _build_date     = get_git_commit_date(_project_path)
        _git_hash       = get_git_commit_hash(_project_path)

        _submodules     = load_git_submodules(
            _project_path,
            _default_server,
            _branch)

        _path_cache     = {
                        }
        _func_data      = {
                        }
        _func_files     = {
                        }
        _obj_data       = {
                        }
        _obj_meta       = {
                        }

        _root           = etree.parse(_xml_path).getroot()

        _funcs          = _root.find('Functions')
        if _funcs is not None:
            for _func in _funcs.getchildren():
                _nloc           = int(_func.find("nloc").text)
                _sloc           = int(_func.find("sloc").text) if _func.find("sloc") is not None else 0
                _eloc           = int(_func.find("eloc").text) if _func.find("eloc") is not None else 0
                _com_cnt        = int(_func.find("comment_count").text)
                _cdrp           = (_com_cnt / (_nloc + _com_cnt)) * 100 if _nloc + _com_cnt != 0 else 0
                _param_count    = int(_func.find("parameter_count").text) if _func.find("parameter_count") is not None else 0
                _return_count   = int(_func.find("return_count").text) if _func.find("return_count") is not None else 0
                _max_nesting    = int(_func.find("max_nesting_depth").text) if _func.find("max_nesting_depth") is not None else 0
                _stmt_cnt       = int(_func.find("statement_count").text) if _func.find("statement_count") is not None else 0
                _vocf_el        = _func.find("vocf") if _func.find("vocf") is not None else _func.find("average_statement_size")
                _stmt_size      = float(_vocf_el.text) if _vocf_el is not None else 0.0
                _goto_cnt       = int(_func.find("goto_count").text) if _func.find("goto_count") is not None else 0
                _calls_cnt      = int(_func.find("called_count").text) if _func.find("called_count") is not None else 0
                _calling_cnt    = int(_func.find("calling_functions_count").text) if _func.find("calling_functions_count") is not None else 0
                _path_cnt       = int(_func.find("path_count").text) if _func.find("path_count") is not None else 1
                _rec_cnt        = int(_func.find("recursion_count").text) if _func.find("recursion_count") is not None else 0
                _dead_cnt       = int(_func.find("dead_code_count").text) if _func.find("dead_code_count") is not None else 0
                _call_depth     = int(_func.find("call_depth").text) if _func.find("call_depth") is not None else 1
                _if_no_else     = int(_func.find("if_without_else_count").text) if _func.find("if_without_else_count") is not None else 0
                _unused_vars    = int(_func.find("unused_variables_count").text) if _func.find("unused_variables_count") is not None else 0
                _raw_func_file   = _func.find("filename").text if _func.find("filename") is not None else ""
                try:
                    _func_file   = str(Path(_raw_func_file).resolve()) if _raw_func_file else ""
                except Exception:
                    _func_file   = _raw_func_file
                _is_c_source     = 1 if _func_file.endswith(('.c', '.cpp', '.cxx', '.cc', '.C')) else 0
                _func_name       = _func.find("name").text
                _func_start      = _func.find("start_line").text
                _func_key        = f"{_func_file}:{_func_start}:{_func_name}"
                _func_base       = os.path.basename(_func_file) if _func_file else ""
                _func_gitlab_url = get_gitlab_url(
                    _func_file,
                    _func_start,
                    _project_path,
                    _gitlab_url,
                    _branch,
                    _submodules)
                _func_files[_func_key] = (_func_file or _raw_func_file, _func_base)
                _func_data.update({
                        _func_key : {
                            'name'              : _func_name,
                            'cc'                : _func.find("cyclomatic_complexity").text,
                            'nloc'              : _func.find("nloc").text,
                            'sloc'              : _sloc,
                            'eloc'              : _eloc,
                            'token'             : _func.find("token_count").text,
                            'name_with_params'  : _func.find("function_name_with_param").text,
                            'sline'             : _func.find("start_line").text,
                            'pcnt'              : _param_count,
                            'ccnt'              : _com_cnt,
                            'cdrp'              : "%.2f" % (float(_cdrp),),
                            'ret_cnt'           : _return_count,
                            'nesting'           : _max_nesting,
                            'stmt_cnt'          : _stmt_cnt,
                            'vocf'              : "%.2f" % (float(_stmt_size),),
                            'stmt_size'         : "%.2f" % (float(_stmt_size),),
                            'goto_cnt'          : _goto_cnt,
                            'calls_cnt'         : _calls_cnt,
                            'calling_cnt'       : _calling_cnt,
                            'path_cnt'          : _path_cnt,
                            'rec_cnt'           : _rec_cnt,
                            'dead_cnt'          : _dead_cnt,
                            'call_depth'        : _call_depth,
                            'if_no_else'        : _if_no_else,
                            'unused_vars'       : _unused_vars,
                            'file'              : _func_base,
                            'is_c_source'       : _is_c_source,
                            'gitlab_url'        : _func_gitlab_url
                        }
                    })
        else:
            # no functions found in metrics xml
            pass

        _objs           = _root.find('Source_files')
        if _objs is not None:
            for _obj in _objs.getchildren():
                _raw_file_path      = _obj.find("filename").text if _obj.find("filename") is not None else ""
                try:
                    _file_abs_path  = str(Path(_raw_file_path).resolve()) if _raw_file_path else ""
                except Exception:
                    _file_abs_path  = _raw_file_path
                _file_key           = _file_abs_path or _raw_file_path
                _file_basename      = os.path.split(_file_key)[1]
                _rel_file_path      = get_relative_source_path(
                    _file_key,
                    _project_path,
                    _path_cache)
                _line_count         = int(_obj.find("line_count").text) if _obj.find("line_count") is not None else int(_obj.find("nloc").text)
                _static_decls       = int(_obj.find("static_declarations_count").text) if _obj.find("static_declarations_count") is not None else 0
                _unreachable_stmts  = int(_obj.find("unreachable_statements_count").text) if _obj.find("unreachable_statements_count") is not None else 0
                _sloc_cnt           = int(_obj.find("sloc").text) if _obj.find("sloc") is not None else 0
                _avg_sloc           = float(_obj.find("average_SLOC").text) if _obj.find("average_SLOC") is not None else 0.0
                _eloc_cnt           = int(_obj.find("eloc").text) if _obj.find("eloc") is not None else 0
                _avg_eloc           = float(_obj.find("average_ELOC").text) if _obj.find("average_ELOC") is not None else 0.0
                _obj_cdrp_el        = _obj.find("cdrp") if _obj.find("cdrp") is not None else _obj.find("ccrp")
                _obj_cdrp_val       = float(_obj_cdrp_el.text) if _obj_cdrp_el is not None else 0.0
                _file_gitlab_url    = get_gitlab_url(
                    _file_abs_path,
                    None,
                    _project_path,
                    _gitlab_url,
                    _branch,
                    _submodules)
                _obj_meta[_file_key] = (_file_basename, _rel_file_path)
                _obj_data.update({
                        _file_key : {
                            'filename'          : _file_basename,
                            'nloc'              : _obj.find("nloc").text,
                            'anloc'             : "%.2f" % (float(_obj.find("average_NLOC").text),),
                            'sloc'              : _sloc_cnt,
                            'asloc'             : "%.2f" % (_avg_sloc,),
                            'eloc'              : _eloc_cnt,
                            'aeloc'             : "%.2f" % (_avg_eloc,),
                            'ccn'               : _obj.find("CCN").text,
                            'accn'              : "%.2f" % (float(_obj.find("average_CCN").text),),
                            'tok'               : _obj.find("token").text,
                            'atok'              : "%.2f" % (float(_obj.find("average_token").text),),
                            'ccnt'              : _obj.find("com_cnt").text,
                            'cdrp'              : "%.2f" % (_obj_cdrp_val,),
                            'line_cnt'          : _line_count,
                            'static_decls'      : _static_decls,
                            'unreachable_stmts' : _unreachable_stmts,
                            'gitlab_url'        : _file_gitlab_url
                        }
                    })
        else:
            # no source files found in metrics xml
            pass

        _basename_counts = {}
        for _f_base, _ in _obj_meta.values():
            _basename_counts[_f_base] = _basename_counts.get(_f_base, 0) + 1
        for _file_key, (_f_base, _f_rel) in _obj_meta.items():
            if _basename_counts.get(_f_base, 0) > 1:
                _obj_data[_file_key]['filename'] = _f_rel
        for _func_key, (_f_path, _f_base) in _func_files.items():
            if _f_base and _basename_counts.get(_f_base, 0) > 1:
                _func_data[_func_key]['file'] = get_relative_source_path(
                    _f_path,
                    _project_path,
                    _path_cache)

        _template       = None

        with open(
            _html_template,
            'r',
            encoding='utf-8') as _fin:
            _template   = Template(_fin.read())

        _opts_present       = _has_configured_thresholds(_yaml_opts)
        _has_cc             = (_yaml_opts.get('cc_threshold') is not None) if _opts_present else True
        _has_nloc           = (_yaml_opts.get('nloc_threshold') is not None) if _opts_present else True
        _has_sloc           = (_yaml_opts.get('sloc_threshold') is not None) if _opts_present else False
        _has_eloc           = (_yaml_opts.get('eloc_threshold') is not None) if _opts_present else False
        _has_cr             = (_yaml_opts.get('min_comment_ratio') is not None) if _opts_present else True
        _has_file_cr        = (_yaml_opts.get('min_file_comment_ratio') is not None) if _opts_present else True
        _has_param          = (_yaml_opts.get('param_threshold') is not None) if _opts_present else True
        _has_return         = (_yaml_opts.get('return_threshold') is not None) if _opts_present else True
        _has_nest           = (_yaml_opts.get('nesting_depth_threshold') is not None) if _opts_present else True
        _has_stmt           = (_yaml_opts.get('stmt_threshold') is not None) if _opts_present else True
        _has_vocf           = (_yaml_opts.get('vocf_threshold') is not None) if _opts_present else True
        _has_goto           = (_yaml_opts.get('goto_threshold') is not None) if _opts_present else True
        _has_calling        = (_yaml_opts.get('calling_threshold') is not None) if _opts_present else True
        _has_calls          = (_yaml_opts.get('calls_threshold') is not None) if _opts_present else True
        _has_path           = (_yaml_opts.get('path_threshold') is not None) if _opts_present else True
        _has_rec            = (_yaml_opts.get('rec_threshold') is not None) if _opts_present else True
        _has_dead           = ((_yaml_opts.get('unreachable_statements_threshold') is not None) or (_yaml_opts.get('dead_code_threshold') is not None)) if _opts_present else True
        _has_call_depth     = (_yaml_opts.get('call_depth_threshold') is not None) if _opts_present else True
        _has_file_lines     = (_yaml_opts.get('file_lines_threshold') is not None) if _opts_present else True
        _has_static_decls   = (_yaml_opts.get('static_declarations_threshold') is not None) if _opts_present else True
        _has_if_no_else     = (_yaml_opts.get('if_without_else_threshold') is not None) if _opts_present else False

        if _template is not None:
            with open(
                _html_path,
                'w',
                encoding='utf-8') as _fout:
                _fout.write(
                    _template.render(
                        FUNC_DATA=dumps(list(_func_data.values())),
                        TH_CC=_get_opt(_yaml_opts, 'cc_threshold', CC_THRESHOLD),
                        TH_NLOC=_get_opt(_yaml_opts, 'nloc_threshold', NLOC_THRESHOLD),
                        TH_SLOC=_get_opt(_yaml_opts, 'sloc_threshold', SLOC_THRESHOLD),
                        TH_ELOC=_get_opt(_yaml_opts, 'eloc_threshold', ELOC_THRESHOLD),
                        COMMENT_RATIO=_get_opt(_yaml_opts, 'min_comment_ratio', MIN_COMMENT_RATIO),
                        FILE_COMMENT_RATIO=_get_opt(_yaml_opts, 'min_file_comment_ratio', MIN_FILE_COMMENT_RATIO),
                        TH_PARAM=_get_opt(_yaml_opts, 'param_threshold', PARAM_THRESHOLD),
                        TH_RETURN=_get_opt(_yaml_opts, 'return_threshold', RETURN_THRESHOLD),
                        TH_NESTING=_get_opt(_yaml_opts, 'nesting_depth_threshold', NESTING_DEPTH_THRESHOLD),
                        TH_STMT=_get_opt(_yaml_opts, 'stmt_threshold', STMT_THRESHOLD),
                        TH_VOCF=_get_opt(_yaml_opts, 'vocf_threshold', VOCF_THRESHOLD),
                        TH_GOTO=_get_opt(_yaml_opts, 'goto_threshold', GOTO_THRESHOLD),
                        TH_CALLING=_get_opt(_yaml_opts, 'calling_threshold', CALLING_THRESHOLD),
                        TH_PATH=_get_opt(_yaml_opts, 'path_threshold', PATH_THRESHOLD),
                        TH_REC=_get_opt(_yaml_opts, 'rec_threshold', REC_THRESHOLD),
                        TH_DEAD=_get_opt(_yaml_opts, 'unreachable_statements_threshold', _get_opt(_yaml_opts, 'dead_code_threshold', DEAD_CODE_THRESHOLD)),
                        TH_CALLS=_get_opt(_yaml_opts, 'calls_threshold', CALLS_THRESHOLD),
                        TH_CALL_DEPTH=_get_opt(_yaml_opts, 'call_depth_threshold', CALL_DEPTH_THRESHOLD),
                        TH_FILE_LINES=_get_opt(_yaml_opts, 'file_lines_threshold', FILE_LINES_THRESHOLD),
                        TH_STATIC_DECLS=_get_opt(_yaml_opts, 'static_declarations_threshold', STATIC_DECLS_THRESHOLD),
                        TH_IF_NO_ELSE=_get_opt(_yaml_opts, 'if_without_else_threshold', IF_WITHOUT_ELSE_THRESHOLD),
                        HAS_CC=_has_cc,
                        HAS_NLOC=_has_nloc,
                        HAS_SLOC=_has_sloc,
                        HAS_ELOC=_has_eloc,
                        HAS_COMMENT_RATIO=_has_cr,
                        HAS_FILE_COMMENT_RATIO=_has_file_cr,
                        HAS_PARAM=_has_param,
                        HAS_RETURN=_has_return,
                        HAS_NESTING=_has_nest,
                        HAS_STMT=_has_stmt,
                        HAS_VOCF=_has_vocf,
                        HAS_GOTO=_has_goto,
                        HAS_CALLING=_has_calling,
                        HAS_CALLS=_has_calls,
                        HAS_PATH=_has_path,
                        HAS_REC=_has_rec,
                        HAS_DEAD=_has_dead,
                        HAS_CALL_DEPTH=_has_call_depth,
                        HAS_FILE_LINES=_has_file_lines,
                        HAS_STATIC_DECLS=_has_static_decls,
                        HAS_IF_NO_ELSE=_has_if_no_else,
                        OBJ_DATA=dumps(list(_obj_data.values())),
                        BUILD_DATE=_build_date,
                        GIT_HASH=_git_hash,
                        GITLAB_PROJECT_URL=_gitlab_url))
        else:
            # template could not be loaded
            pass

        return 0


"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
class cc_html(Task):
    color = 'PINK'
    def run(self):
        xml2html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'xml2html.py')
        xslt_path     = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cppncss_html.xsl')
        return self.exec_command([sys.executable, xml2html_path, self.inputs[0].abspath(), self.outputs[0].abspath(), xslt_path])


"""*************************************************************************************************
****************************************************************************************************
*************************************************************************************************"""
class cc_xml2junit(Task):
    color = 'PINK'
    def sig_vars(self):
        super(cc_xml2junit, self).sig_vars()
        _yaml_opts = getattr(self, 'yaml_opts', None)
        if _yaml_opts is None and hasattr(self, 'generator') and hasattr(self.generator, 'code_metrics'):
            _yaml_opts = self.generator.code_metrics
        _waf_params = _extract_waf_params(self)
        self.m.update(json.dumps(_yaml_opts or {}, sort_keys=True, default=str).encode('utf-8'))
        self.m.update(json.dumps(_waf_params or {}, sort_keys=True, default=str).encode('utf-8'))
        if hasattr(self, 'xml_path') and self.xml_path is not None:
            _xml_p = self.xml_path.abspath() if hasattr(self.xml_path, 'abspath') else str(self.xml_path)
            self.m.update(_xml_p.encode('utf-8'))
            try:
                with open(_xml_p, 'rb') as _fh:
                    self.m.update(_fh.read())
            except Exception:
                pass

    def run(self):
        global CC_THRESHOLD
        global NLOC_THRESHOLD
        global SLOC_THRESHOLD
        global ELOC_THRESHOLD
        global MIN_COMMENT_RATIO
        global MIN_FILE_COMMENT_RATIO
        global PARAM_THRESHOLD
        global RETURN_THRESHOLD
        global NESTING_DEPTH_THRESHOLD
        global STMT_THRESHOLD
        global VOCF_THRESHOLD
        global GOTO_THRESHOLD
        global CALLING_THRESHOLD
        global PATH_THRESHOLD
        global REC_THRESHOLD
        global DEAD_CODE_THRESHOLD
        global CALLS_THRESHOLD
        global CALL_DEPTH_THRESHOLD
        global FILE_LINES_THRESHOLD
        global STATIC_DECLS_THRESHOLD
        global IF_WITHOUT_ELSE_THRESHOLD

        _error                = 0
        _xml_path             = self.xml_path.abspath() if hasattr(self.xml_path, 'abspath') else str(self.xml_path)
        _junit_path           = os.path.join(
            os.path.dirname(_xml_path),
            "junit_report.xml")

        _project_path         = os.getcwd()
        if hasattr(self, "generator") and hasattr(self.generator, "bld") and hasattr(self.generator.bld, "srcnode"):
            _project_path     = self.generator.bld.srcnode.abspath()
        else:
            # use current working directory as project path
            pass
        try:
            _project_path     = str(Path(_project_path).resolve())
        except Exception:
            # use unresolved project path
            pass

        _yaml_opts            = getattr(self, 'yaml_opts', None)
        if _yaml_opts is None:
            if hasattr(self, 'generator') and hasattr(self.generator, 'code_metrics'):
                _yaml_opts    = self.generator.code_metrics
            else:
                # no yaml options attached
                _yaml_opts    = {
                                }
        else:
            # yaml options attached
            pass

        _opts_present         = _has_configured_thresholds(_yaml_opts)
        _th_cc                = _get_opt(_yaml_opts, 'cc_threshold', CC_THRESHOLD)
        _th_vocf              = float(_get_opt(_yaml_opts, 'vocf_threshold', VOCF_THRESHOLD))
        _th_stmt              = _get_opt(_yaml_opts, 'stmt_threshold', STMT_THRESHOLD)
        _th_nest              = _get_opt(_yaml_opts, 'nesting_depth_threshold', NESTING_DEPTH_THRESHOLD)
        _th_calling           = _get_opt(_yaml_opts, 'calling_threshold', CALLING_THRESHOLD)
        _th_calls             = _get_opt(_yaml_opts, 'calls_threshold', CALLS_THRESHOLD)
        _th_path              = _get_opt(_yaml_opts, 'path_threshold', PATH_THRESHOLD)
        _th_param             = _get_opt(_yaml_opts, 'param_threshold', PARAM_THRESHOLD)
        _th_return            = _get_opt(_yaml_opts, 'return_threshold', RETURN_THRESHOLD)
        _th_goto              = _get_opt(_yaml_opts, 'goto_threshold', GOTO_THRESHOLD)
        _th_rec               = _get_opt(_yaml_opts, 'rec_threshold', REC_THRESHOLD)
        _th_dead              = _get_opt(_yaml_opts, 'unreachable_statements_threshold', _get_opt(_yaml_opts, 'dead_code_threshold', DEAD_CODE_THRESHOLD))
        _th_call_depth        = _get_opt(_yaml_opts, 'call_depth_threshold', CALL_DEPTH_THRESHOLD)
        _th_cr                = float(_get_opt(_yaml_opts, 'min_comment_ratio', MIN_COMMENT_RATIO))
        _th_file_cr           = float(_get_opt(_yaml_opts, 'min_file_comment_ratio', MIN_FILE_COMMENT_RATIO))
        _th_nloc              = _get_opt(_yaml_opts, 'nloc_threshold', NLOC_THRESHOLD)
        _th_sloc              = _get_opt(_yaml_opts, 'sloc_threshold', SLOC_THRESHOLD)
        _th_eloc              = _get_opt(_yaml_opts, 'eloc_threshold', ELOC_THRESHOLD)
        _th_file_lines        = _get_opt(_yaml_opts, 'file_lines_threshold', FILE_LINES_THRESHOLD)
        _th_static_decls      = _get_opt(_yaml_opts, 'static_declarations_threshold', STATIC_DECLS_THRESHOLD)
        _th_if_no_else        = _get_opt(_yaml_opts, 'if_without_else_threshold', IF_WITHOUT_ELSE_THRESHOLD)

        _path_cache           = {
                                }
        _funcs_map            = {
                                }
        _sources_map          = {
                                }

        _root                 = etree.parse(_xml_path).getroot()
        _funcs                = _root.find('Functions')
        _sources              = _root.find("Source_files")

        if _funcs is not None:
            for _func in _funcs.getchildren():
                _raw_file     = _func.find("filename").text if _func.find("filename") is not None else ""
                try:
                    _abs_file = str(Path(_raw_file).resolve()) if _raw_file else ""
                except Exception:
                    _abs_file = _raw_file
                _rel_file     = get_relative_source_path(
                    _abs_file or _raw_file,
                    _project_path,
                    _path_cache)
                _func_name    = _func.find("name").text if _func.find("name") is not None else ""
                _start_line   = _func.find("start_line").text if _func.find("start_line") is not None else "1"
                _func_key     = f"{_abs_file}:{_start_line}:{_func_name}"
                _nloc_val     = int(_func.find("nloc").text) if _func.find("nloc") is not None else 0
                _com_cnt      = int(_func.find("comment_count").text) if _func.find("comment_count") is not None else 0
                _com_denom    = _nloc_val + _com_cnt
                if 0 == _com_denom:
                    _com_ratio = 0.0
                else:
                    _com_ratio = float("%.2f" % ((float(_com_cnt) / float(_com_denom)) * 100.0))

                _vocf_el      = _func.find("vocf") if _func.find("vocf") is not None else _func.find("average_statement_size")
                _vocf_val     = float("%.2f" % (float(_vocf_el.text) if _vocf_el is not None else 0.0))
                _func_item    = {
                    "name"       : _func_name,
                    "rel_path"   : _rel_file,
                    "line"       : _start_line,
                    "cc"         : int(_func.find("cyclomatic_complexity").text) if _func.find("cyclomatic_complexity") is not None else 0,
                    "nloc"       : _nloc_val,
                    "sloc"       : int(_func.find("sloc").text) if _func.find("sloc") is not None else 0,
                    "eloc"       : int(_func.find("eloc").text) if _func.find("eloc") is not None else 0,
                    "vocf"       : _vocf_val,
                    "stmt"       : int(_func.find("statement_count").text) if _func.find("statement_count") is not None else 0,
                    "nesting"    : int(_func.find("max_nesting_depth").text) if _func.find("max_nesting_depth") is not None else 0,
                    "calling"    : int(_func.find("calling_functions_count").text) if _func.find("calling_functions_count") is not None else 0,
                    "calls"      : int(_func.find("called_count").text) if _func.find("called_count") is not None else 0,
                    "path"       : int(_func.find("path_count").text) if _func.find("path_count") is not None else 1,
                    "param"      : int(_func.find("parameter_count").text) if _func.find("parameter_count") is not None else 0,
                    "return"     : int(_func.find("return_count").text) if _func.find("return_count") is not None else 0,
                    "goto"       : int(_func.find("goto_count").text) if _func.find("goto_count") is not None else 0,
                    "rec"        : int(_func.find("recursion_count").text) if _func.find("recursion_count") is not None else 0,
                    "dead"       : int(_func.find("dead_code_count").text) if _func.find("dead_code_count") is not None else 0,
                    "call_depth" : int(_func.find("call_depth").text) if _func.find("call_depth") is not None else 1,
                    "if_no_else" : int(_func.find("if_without_else_count").text) if _func.find("if_without_else_count") is not None else 0,
                    "cdrp"       : _com_ratio
                }
                _funcs_map[_func_key] = _func_item
        else:
            # no functions found in xml
            pass

        if _sources is not None:
            for _source in _sources.getchildren():
                _raw_file     = _source.find("filename").text if _source.find("filename") is not None else ""
                try:
                    _abs_file = str(Path(_raw_file).resolve()) if _raw_file else ""
                except Exception:
                    _abs_file = _raw_file
                _file_key     = _abs_file or _raw_file
                _rel_file     = get_relative_source_path(
                    _file_key,
                    _project_path,
                    _path_cache)
                _file_name    = os.path.split(_file_key)[1]
                _nloc_val     = int(_source.find("nloc").text) if _source.find("nloc") is not None else 0
                _line_count   = int(_source.find("line_count").text) if _source.find("line_count") is not None else _nloc_val
                _static_decls = int(_source.find("static_declarations_count").text) if _source.find("static_declarations_count") is not None else 0
                _src_cdrp_el  = _source.find("cdrp") if _source.find("cdrp") is not None else _source.find("ccrp")
                _cdrp_val     = float("%.2f" % (float(_src_cdrp_el.text) if _src_cdrp_el is not None else 0.0))

                _source_item  = {
                    "name"         : _file_name,
                    "rel_path"     : _rel_file,
                    "line"         : "1",
                    "nloc"         : _nloc_val,
                    "line_cnt"     : _line_count,
                    "static_decls" : _static_decls,
                    "cdrp"         : _cdrp_val
                }
                _sources_map[_file_key] = _source_item
        else:
            # no source files found in xml
            pass

        _junit_base_counts = {}
        for _src_item in _sources_map.values():
            _bname = _src_item["name"]
            _junit_base_counts[_bname] = _junit_base_counts.get(_bname, 0) + 1
        for _src_item in _sources_map.values():
            if _junit_base_counts.get(_src_item["name"], 0) > 1:
                _src_item["name"] = _src_item["rel_path"]

        _funcs_data           = list(_funcs_map.values())
        _sources_data         = list(_sources_map.values())

        _metric_suites        = [
            {
                "suite_name" : "Cyclomatic Complexity (CC)",
                "param_keys" : ("cc_threshold", "cc_blocker"),
                "is_active"  : (_yaml_opts.get('cc_threshold') is not None) if _opts_present else True,
                "metric_key" : "cc",
                "threshold"  : _th_cc,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Language Scope / Vocabulary Frequency (VOCF)",
                "param_keys" : ("vocf_threshold", "vocf_blocker"),
                "is_active"  : (_yaml_opts.get('vocf_threshold') is not None) if _opts_present else True,
                "metric_key" : "vocf",
                "threshold"  : _th_vocf,
                "operator"   : "<=",
                "is_float"   : True,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Executable Statements (STMT)",
                "param_keys" : ("stmt_threshold", "stmt_blocker"),
                "is_active"  : (_yaml_opts.get('stmt_threshold') is not None) if _opts_present else True,
                "metric_key" : "stmt",
                "threshold"  : _th_stmt,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Control Nesting Depth (LEVEL)",
                "param_keys" : ("nesting_depth_threshold", "nesting_blocker", "level_blocker"),
                "is_active"  : (_yaml_opts.get('nesting_depth_threshold') is not None) if _opts_present else True,
                "metric_key" : "nesting",
                "threshold"  : _th_nest,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Calling Functions (CALLING)",
                "param_keys" : ("calling_threshold", "calling_blocker"),
                "is_active"  : (_yaml_opts.get('calling_threshold') is not None) if _opts_present else True,
                "metric_key" : "calling",
                "threshold"  : _th_calling,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Called Functions (CALLS)",
                "param_keys" : ("calls_threshold", "calls_blocker"),
                "is_active"  : (_yaml_opts.get('calls_threshold') is not None) if _opts_present else True,
                "metric_key" : "calls",
                "threshold"  : _th_calls,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Execution Paths (PATH)",
                "param_keys" : ("path_threshold", "path_blocker"),
                "is_active"  : (_yaml_opts.get('path_threshold') is not None) if _opts_present else True,
                "metric_key" : "path",
                "threshold"  : _th_path,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Transfer Parameters (PARAM)",
                "param_keys" : ("param_threshold", "param_blocker"),
                "is_active"  : (_yaml_opts.get('param_threshold') is not None) if _opts_present else True,
                "metric_key" : "param",
                "threshold"  : _th_param,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Return Points (RETURN)",
                "param_keys" : ("return_threshold", "return_blocker"),
                "is_active"  : (_yaml_opts.get('return_threshold') is not None) if _opts_present else True,
                "metric_key" : "return",
                "threshold"  : _th_return,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "GOTO Statements (GOTO)",
                "param_keys" : ("goto_threshold", "goto_blocker"),
                "is_active"  : (_yaml_opts.get('goto_threshold') is not None) if _opts_present else True,
                "metric_key" : "goto",
                "threshold"  : _th_goto,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Recursions (REC)",
                "param_keys" : ("rec_threshold", "rec_blocker"),
                "is_active"  : (_yaml_opts.get('rec_threshold') is not None) if _opts_present else True,
                "metric_key" : "rec",
                "threshold"  : _th_rec,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Dead Code Statements (DEAD)",
                "param_keys" : ("unreachable_statements_threshold", "dead_code_threshold", "unreachable_statements_blocker", "dead_code_blocker", "dead_blocker"),
                "is_active"  : ((_yaml_opts.get('unreachable_statements_threshold') is not None) or (_yaml_opts.get('dead_code_threshold') is not None)) if _opts_present else True,
                "metric_key" : "dead",
                "threshold"  : _th_dead,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Call Graph Depth (CALL_DEPTH)",
                "param_keys" : ("call_depth_threshold", "call_depth_blocker"),
                "is_active"  : (_yaml_opts.get('call_depth_threshold') is not None) if _opts_present else True,
                "metric_key" : "call_depth",
                "threshold"  : _th_call_depth,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Function Comment Ratio (CDRP)",
                "param_keys" : ("min_comment_ratio", "min_comment_ratio_blocker", "comment_ratio_blocker", "cdrp_blocker"),
                "is_active"  : (_yaml_opts.get('min_comment_ratio') is not None) if _opts_present else True,
                "metric_key" : "cdrp",
                "threshold"  : _th_cr,
                "operator"   : ">=",
                "is_float"   : True,
                "unit"       : "%",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Logical Lines of Code (SLOC)",
                "param_keys" : ("sloc_threshold", "sloc_blocker"),
                "is_active"  : (_yaml_opts.get('sloc_threshold') is not None) if _opts_present else False,
                "metric_key" : "sloc",
                "threshold"  : _th_sloc,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Executable Lines of Code (ELOC)",
                "param_keys" : ("eloc_threshold", "eloc_blocker"),
                "is_active"  : (_yaml_opts.get('eloc_threshold') is not None) if _opts_present else False,
                "metric_key" : "eloc",
                "threshold"  : _th_eloc,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Decisions without Else (IF_NO_ELSE)",
                "param_keys" : ("if_without_else_threshold", "if_without_else_blocker"),
                "is_active"  : (_yaml_opts.get('if_without_else_threshold') is not None) if _opts_present else False,
                "metric_key" : "if_no_else",
                "threshold"  : _th_if_no_else,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "Function",
                "data_items" : _funcs_data
            },
            {
                "suite_name" : "Lines of Code (NLOC)",
                "param_keys" : ("nloc_threshold", "nloc_blocker"),
                "is_active"  : (_yaml_opts.get('nloc_threshold') is not None) if _opts_present else True,
                "metric_key" : "nloc",
                "threshold"  : _th_nloc,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "File",
                "data_items" : _sources_data
            },
            {
                "suite_name" : "Total File Lines (FILE_LINES)",
                "param_keys" : ("file_lines_threshold", "file_lines_blocker"),
                "is_active"  : (_yaml_opts.get('file_lines_threshold') is not None) if _opts_present else True,
                "metric_key" : "line_cnt",
                "threshold"  : _th_file_lines,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "File",
                "data_items" : _sources_data
            },
            {
                "suite_name" : "Minimum File Comment Ratio (CDRP)",
                "param_keys" : ("min_file_comment_ratio", "min_file_comment_ratio_blocker", "file_comment_ratio_blocker", "file_cdrp_blocker"),
                "is_active"  : (_yaml_opts.get('min_file_comment_ratio') is not None) if _opts_present else True,
                "metric_key" : "cdrp",
                "threshold"  : _th_file_cr,
                "operator"   : ">=",
                "is_float"   : True,
                "unit"       : "%",
                "elem_type"  : "File",
                "data_items" : _sources_data
            },
            {
                "suite_name" : "Static Declarations (STATIC_DECLS)",
                "param_keys" : ("static_declarations_threshold", "static_declarations_blocker", "static_decls_blocker"),
                "is_active"  : (_yaml_opts.get('static_declarations_threshold') is not None) if _opts_present else True,
                "metric_key" : "static_decls",
                "threshold"  : _th_static_decls,
                "operator"   : "<=",
                "is_float"   : False,
                "unit"       : "",
                "elem_type"  : "File",
                "data_items" : _sources_data
            }
        ]

        _waf_params           = _extract_waf_params(self)
        _target_label         = getattr(self, 'target_name', None) or getattr(getattr(self, 'generator', None), 'target', 'code_metrics')

        _testsuites_elem      = etree.Element(
            "testsuites",
            name="Code Metrics")
        _total_tests          = 0
        _total_failures       = 0
        _blocking_failures    = 0
        _blocking_suites      = []

        for _suite_cfg in _metric_suites:
            if not _suite_cfg["is_active"]:
                # skip metric suite if not enabled
                continue
            else:
                # process enabled metric suite
                pass

            _suite_elem       = etree.SubElement(
                _testsuites_elem,
                "testsuite",
                name=_suite_cfg["suite_name"],
                errors="0",
                skipped="0",
                time="0.0")
            _suite_tests      = 0
            _suite_failures   = 0
            _th_val           = _suite_cfg["threshold"]
            _is_lte           = (_suite_cfg["operator"] == "<=")
            _is_float         = _suite_cfg["is_float"]
            _unit             = _suite_cfg["unit"]
            _elem_label       = _suite_cfg["elem_type"]
            _metric_key       = _suite_cfg["metric_key"]
            _suite_name       = _suite_cfg["suite_name"]
            _is_blocker       = _is_suite_blocker(_suite_cfg, _waf_params)

            for _data_item in _suite_cfg["data_items"]:
                _suite_tests += 1
                _metric_val   = _data_item[_metric_key]
                if _is_lte:
                    _is_passed = (_metric_val <= _th_val)
                else:
                    _is_passed = (_metric_val >= _th_val)

                _tc_elem      = etree.SubElement(
                    _suite_elem,
                    "testcase",
                    name=_data_item["name"],
                    classname=_data_item["rel_path"],
                    file=_data_item["rel_path"],
                    line=str(_data_item["line"]),
                    time="0.0",
                    status="passed" if _is_passed else "failed")

                if not _is_passed:
                    _suite_failures += 1
                    if _is_float:
                        _val_str     = "%.2f%s" % (_metric_val, _unit)
                        _th_str      = "%.2f%s" % (_th_val, _unit)
                        if _is_lte:
                            _diff_str  = "Exceeded by %.2f%s" % (_metric_val - _th_val, _unit)
                            _short_msg = "%s: [%s], Maximum Allowed: [%s]" % (_suite_name, _val_str, _th_str)
                            _limit_str = "<= %s" % _th_str
                        else:
                            _diff_str  = "Below threshold by %.2f%s" % (_th_val - _metric_val, _unit)
                            _short_msg = "%s: [%s], Minimum Allowed: [%s]" % (_suite_name, _val_str, _th_str)
                            _limit_str = ">= %s" % _th_str
                    else:
                        _val_str     = "%s%s" % (_metric_val, _unit)
                        _th_str      = "%s%s" % (_th_val, _unit)
                        if _is_lte:
                            _diff_str  = "Exceeded by %s%s" % (_metric_val - _th_val, _unit)
                            _short_msg = "%s: [%s], Maximum Allowed: [%s]" % (_suite_name, _val_str, _th_str)
                            _limit_str = "<= %s" % _th_str
                        else:
                            _diff_str  = "Below threshold by %s%s" % (_th_val - _metric_val, _unit)
                            _short_msg = "%s: [%s], Minimum Allowed: [%s]" % (_suite_name, _val_str, _th_str)
                            _limit_str = ">= %s" % _th_str

                    _detail_text     = (
                        f"{_elem_label}: {_data_item['name']} (line {_data_item['line']})\n"
                        f"File: {_data_item['rel_path']}\n"
                        f"Metric: {_suite_name}\n"
                        f"Actual Value: {_val_str}\n"
                        f"Threshold Limit: {_limit_str}\n"
                        f"Violation: {_diff_str}"
                    )

                    _fail_elem       = etree.SubElement(
                        _tc_elem,
                        "failure",
                        message=_short_msg,
                        type="QualityGateViolation")
                    _fail_elem.text  = _detail_text
                else:
                    # testcase passed threshold check
                    pass

            _suite_elem.set("tests", str(_suite_tests))
            _suite_elem.set("failures", str(_suite_failures))
            _total_tests    += _suite_tests
            _total_failures += _suite_failures

            if _suite_failures > 0 and _is_blocker:
                _blocking_failures += _suite_failures
                _rule_th_str        = ("%.2f%s" % (_th_val, _unit)) if _is_float else ("%s%s" % (_th_val, _unit))
                _rule_str           = "%s %s" % (_suite_cfg["operator"], _rule_th_str)
                _blocking_suites.append((
                    _suite_name,
                    _suite_cfg["param_keys"][0],
                    _rule_str,
                    _suite_failures))

        _testsuites_elem.set("tests", str(_total_tests))
        _testsuites_elem.set("failures", str(_total_failures))
        _testsuites_elem.set("errors", "0")
        _testsuites_elem.set("skipped", "0")
        _testsuites_elem.set("time", "0.0")

        self._generate_junit_xml(
            _testsuites_elem,
            _junit_path)

        _error            = _total_failures
        _non_blocking_cnt = _total_failures - _blocking_failures

        if _blocking_failures > 0:
            Logs.pprint(
                'RED',
                f"[code_metrics] Target '{_target_label}' FAILED quality gate: "
                f"{_blocking_failures} blocking violation(s) across {len(_blocking_suites)} blocker threshold(s)"
                + (f" (+ {_non_blocking_cnt} non-blocking finding(s))." if _non_blocking_cnt > 0 else "."))
            for _b_name, _b_key, _b_rule, _b_cnt in _blocking_suites:
                Logs.pprint(
                    'RED',
                    f"  -> [BLOCKER] {_b_name} ({_b_key}: {_b_rule}) — {_b_cnt} violation(s)")
            return 1

        if _total_failures > 0:
            Logs.pprint(
                'YELLOW',
                f"[code_metrics] Target '{_target_label}' PASSED with {_total_failures} non-blocking finding(s) "
                f"(no violated threshold marked as blocker in --params).")
        return 0


    def _generate_junit_xml(self, testsuites_element, junit_file_path):
        _xml_bytes = etree.tostring(
            testsuites_element,
            pretty_print=True,
            xml_declaration=True,
            encoding="utf-8")
        with open(
            junit_file_path,
            "wb") as _file_handle:
            _file_handle.write(_xml_bytes)
        print("generated junit report: %s" % junit_file_path)
        return 0


